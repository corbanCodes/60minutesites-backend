"""The seamless hand-off: we hold the line, so nothing is ever dialled.

Every earlier shape let the vendor dial something on the prospect's side
at the moment of hand-off, and whatever is dialled rings. The prospect
heard that ring, and it is the one thing left that marked the moment as a
transfer. So in owned mode WE place the prospect's call through Twilio,
the agent rides it as a media stream, and the hand-off is a redirect of an
already-answered call into our room: no dial, no ringback, the agent's
own voice saying the line as the room opens, ambience until the rep joins.
"""
import pytest

from app import Media, db
from dialer import agents as agents_mod, bridge, calls as calls_mod
from dialer.agents import build_prompt, transfer_config
from dialer.models import AiAgent, Call, CallEvent, PhoneNumber, Playbook
from dialer.providers import registry
from dialer.settings_store import get_settings
from dialer.tools import account_token
from tests.conftest import make_lead, make_user

LINE = "+18655550101"
AI = "+18655550102"
PROSPECT = "+18655558888"
HUMAN = "+14235550147"


class FakeTelephony:
    def __init__(self):
        self.created, self.redirected, self.configured, self.hungup = [], [], [], []
        self.current_voice_url = ""

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        self.created.append({"to": to, "from_": from_, "url": url,
                             "status_callback": status_callback, **kw})
        return {"ok": True, "sid": f"CAowned{len(self.created)}"}

    def redirect_call(self, sid, twiml):
        self.redirected.append({"sid": sid, "twiml": twiml})
        return {"ok": True}

    def configure_number(self, sid, voice_url, status_callback):
        self.configured.append(sid)
        return {"ok": True}

    def fetch_number(self, sid):
        return {"ok": True, "voice_url": "", "status_callback": ""}

    def hangup(self, sid):
        self.hungup.append(sid)
        return {"ok": True}


class FakeVoiceAgent:
    def __init__(self):
        self.upserts, self.registered, self.spoken, self.outbound = [], [], [], []

    def upsert_agent(self, agent, prompt, tools, **kw):
        self.upserts.append({"prompt": prompt, "tools": tools, **kw})
        return {"ok": True, "agent_id": agent.elevenlabs_agent_id or "ag_new"}

    def speak(self, text, voice_id, model_id=None):
        self.spoken.append({"text": text, "voice_id": voice_id})
        return {"ok": True, "audio": b"ID3fakemp3", "mimetype": "audio/mpeg"}

    def register_call(self, agent_id, from_number, to_number, direction,
                      variables=None):
        self.registered.append({"agent_id": agent_id, "from": from_number,
                                "to": to_number, "direction": direction,
                                "variables": variables or {}})
        return {"ok": True, "twiml": '<?xml version="1.0"?><Response>'
                                     '<Connect><Stream url="wss://x"/></Connect>'
                                     '</Response>'}

    def outbound_call(self, *a, **kw):
        self.outbound.append((a, kw))
        return {"ok": True, "conversation_id": "conv_vendor", "call_sid": "CAvendor"}

    def get_agent(self, agent_id):
        return {"ok": True}

    def list_voices(self, limit=40):
        return {"ok": True, "voices": []}


@pytest.fixture
def world(ctx, client, monkeypatch):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.enforce_window = False
    s.ai_callback_number = ""
    db.session.add(PhoneNumber(account_id=owner.id, e164=LINE, pool="rep",
                               state="active", twilio_sid="PN" + "a" * 32,
                               friendly_name="Rep line", area_code="865"))
    db.session.add(PhoneNumber(account_id=owner.id, e164=AI, pool="ai",
                               state="active", twilio_sid="PN" + "b" * 32,
                               friendly_name="AI line", area_code="865",
                               elevenlabs_phone_id="pn_1"))
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer on a decision maker.")
    db.session.add(pb)
    db.session.flush()
    agent = AiAgent(account_id=owner.id, name="John — venue calls",
                    direction="outbound", active=True, playbook_id=pb.id,
                    transfer_handoff="owned", transfer_to_number=HUMAN,
                    transfer_style="custom",
                    transfer_line="Oh, sorry — you're cutting out a bit, one second.",
                    voice_id="v1", elevenlabs_agent_id="ag_1")
    db.session.add(agent)
    db.session.commit()
    tel, va = FakeTelephony(), FakeVoiceAgent()
    monkeypatch.setattr(registry, "telephony", lambda settings: tel)
    monkeypatch.setattr(registry, "voice_agent", lambda settings: va)
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, agent, tel, va, client


def placed_call(owner, s, agent, sid="CAowned1"):
    lead = make_lead(owner_id=owner.id, phone=PROSPECT)
    call = calls_mod.start_call(owner.id, lead, "ai_outbound", s,
                                from_number=AI, ai_agent=agent)
    call.twilio_sid = sid
    call.status = "in-progress"
    db.session.commit()
    return call


# ------------------------------------------------ the vendor gets no dialler
def test_owned_mode_gives_the_vendor_no_transfer_tool(world):
    owner, s, agent, tel, va, client = world
    assert transfer_config(agent, s) is None
    assert agents_mod.transfer_number(s, agent) == ""


def test_the_prompt_tells_it_to_call_our_tool_and_say_nothing(world):
    owner, s, agent, tel, va, client = world
    p = build_prompt(agent, s)
    assert "set_disposition" in p and '"handoff"' in p
    assert "say nothing more" in p
    assert "transfer_to_number tool" not in p
    assert "cutting out a bit" in p


def test_a_sync_resends_the_tools_so_the_vendor_transfer_tool_is_wiped(world):
    """Webhook tools only ever went on create; an update must carry them in
    owned mode because the array rebuilds the whole tool set -- which is
    exactly how the vendor's transfer tool is removed."""
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    up = va.upserts[-1]
    assert up["force_tools"] is True
    assert up["transfer"] is None
    names = [t["name"] for t in up["tools"]]
    assert "set_disposition" in names
    disp = next(t for t in up["tools"] if t["name"] == "set_disposition")
    props = disp["api_schema"]["request_body_schema"]["properties"]
    assert "handoff" in props["disposition"]["enum"]
    assert props["hq_call_id"]["dynamic_variable"] == "hq_call_id"


def test_every_tool_carries_our_own_call_id(world):
    from dialer.tools import TOOL_SPECS
    for spec in TOOL_SPECS:
        assert "hq_call_id" in spec["parameters"]["properties"], spec["name"]


# ------------------------------------------------------- the spoken line
def test_a_sync_pre_synthesises_the_line_in_the_agents_voice(world):
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    assert va.spoken == [{"text": agent.transfer_line, "voice_id": "v1"}]
    a = db.session.get(AiAgent, agent.id)
    assert a.handoff_line_media_id
    media = db.session.get(Media, a.handoff_line_media_id)
    assert media.data == b"ID3fakemp3" and media.mimetype == "audio/mpeg"


def test_the_line_is_made_once_per_voice_and_wording(world):
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    agents_mod.sync_agent(agent, s)
    assert len(va.spoken) == 1
    agent.transfer_line = "Oh, okay. Thanks."
    db.session.commit()
    agents_mod.sync_agent(agent, s)
    assert len(va.spoken) == 2


def test_the_line_is_served_for_twilio(world):
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    a = db.session.get(AiAgent, agent.id)
    r = client.get(f"/dialer/handoff-line/{a.handoff_line_media_id}")
    assert r.status_code == 200 and r.mimetype == "audio/mpeg"
    assert r.data == b"ID3fakemp3"


# ---------------------------------------------------- placing the call
def test_the_test_call_is_placed_by_us_with_the_connect_url(world):
    owner, s, agent, tel, va, client = world
    client.post("/dialer/test-call", follow_redirects=True,
                data={"to_number": PROSPECT, "agent_id": agent.id})
    assert va.outbound == [], "the vendor must not place an owned call"
    assert len(tel.created) == 1
    leg = tel.created[0]
    assert leg["to"] == PROSPECT and leg["from_"] == AI
    call = Call.query.filter_by(account_id=owner.id, mode="ai_outbound").one()
    assert leg["url"].endswith(f"/twilio/ai/{call.id}/connect")
    assert call.twilio_sid == "CAowned1"


def test_an_owned_call_does_not_need_the_number_imported_at_the_vendor(world):
    owner, s, agent, tel, va, client = world
    n = PhoneNumber.query.filter_by(e164=AI).one()
    n.elevenlabs_phone_id = ""
    db.session.commit()
    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": PROSPECT, "agent_id": agent.id}
                       ).get_data(as_text=True)
    assert "has not reached ElevenLabs" not in body
    assert len(tel.created) == 1


def test_a_campaign_places_owned_calls_the_same_way(world):
    owner, s, agent, tel, va, client = world
    from dialer import campaigns
    from dialer.models import Campaign
    camp = Campaign(account_id=owner.id, name="C", mode="ai",
                    ai_agent_id=agent.id, status="running")
    db.session.add(camp)
    db.session.flush()
    lead = make_lead(owner_id=owner.id, phone=PROSPECT)
    call = calls_mod.start_call(owner.id, lead, "ai_outbound", s,
                                from_number=AI, campaign=camp, ai_agent=agent)
    number = PhoneNumber.query.filter_by(e164=AI).one()
    assert campaigns._place(call, camp, s, number, lead) is True
    assert va.outbound == []
    assert tel.created[-1]["url"].endswith(f"/twilio/ai/{call.id}/connect")


# ---------------------------------------------------- the connect hook
def test_the_connect_hook_hands_the_answered_call_to_the_agent(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    r = client.post(f"/dialer/hooks/twilio/ai/{call.id}/connect",
                    data={"CallSid": "CAowned1", "CallStatus": "in-progress"})
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "<Connect>" in body and "<Stream" in body
    assert body.count("<?xml") == 1, "no doubled XML prologue"
    reg = va.registered[-1]
    assert reg["direction"] == "outbound"
    assert reg["from"] == AI and reg["to"] == PROSPECT
    assert reg["variables"]["hq_call_id"] == str(call.id)
    assert "lead_name" in reg["variables"]


def test_the_connect_hook_hangs_up_cleanly_if_the_vendor_refuses(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    va.register_call = lambda *a, **k: {"ok": False, "error": "nope"}
    body = client.post(f"/dialer/hooks/twilio/ai/{call.id}/connect",
                       data={"CallSid": "CAowned1"}).get_data(as_text=True)
    assert "<Hangup/>" in body
    assert db.session.get(Call, call.id).error == "nope"


def test_an_unknown_call_is_a_404_not_a_crash(world):
    owner, s, agent, tel, va, client = world
    assert client.post("/dialer/hooks/twilio/ai/999999/connect").status_code == 404


# ------------------------------------------------------- the hand-off
def tool(client, owner, body):
    return client.post("/dialer/hooks/elevenlabs/tools/set_disposition",
                       json=body, headers={"X-HQ-Token": account_token(owner.id)})


def test_our_tool_moves_the_answered_call_into_the_room_without_dialling(world):
    """The whole point. No create_call for the prospect, a redirect of the
    leg we already own, the line first, then the room."""
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    call = placed_call(owner, s, agent)
    r = tool(client, owner, {"disposition": "handoff",
                             "hq_call_id": str(call.id),
                             "conversation_id": "conv_live"}).get_json()
    assert r["ok"] is True
    assert "Say nothing more" in r["message"]

    assert len(tel.redirected) == 1
    red = tel.redirected[0]
    assert red["sid"] == "CAowned1"
    assert "<Play>" in red["twiml"] and "/dialer/handoff-line/" in red["twiml"]
    assert red["twiml"].index("<Play>") < red["twiml"].index("<Conference")
    assert 'startConferenceOnEnter="false"' in red["twiml"]
    assert "bridge/wait?room=handoff-CAowned1" in red["twiml"]

    legs = [c for c in tel.created if c.get("twiml")]
    assert len(legs) == 1 and legs[0]["to"] == HUMAN
    assert "handoff-CAowned1" in legs[0]["twiml"]

    c = db.session.get(Call, call.id)
    assert c.conference_name == "handoff-CAowned1"
    assert c.elevenlabs_conversation_id == "conv_live"
    assert c.disposition == "transferred"


def test_the_prospects_number_is_never_dialled_again(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    tool(client, owner, {"disposition": "handoff", "hq_call_id": str(call.id)})
    assert all(c["to"] != PROSPECT for c in tel.created)


def test_the_tool_firing_twice_does_not_ring_the_rep_twice(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    tool(client, owner, {"disposition": "handoff", "hq_call_id": str(call.id)})
    tool(client, owner, {"disposition": "handoff", "hq_call_id": str(call.id)})
    assert len([c for c in tel.created if c.get("twiml")]) == 1
    assert len(tel.redirected) == 1


def test_a_hand_off_with_nobody_to_ring_releases_the_prospect_politely(world):
    owner, s, agent, tel, va, client = world
    agent.transfer_to_number = ""
    db.session.commit()
    call = placed_call(owner, s, agent)
    r = tool(client, owner, {"disposition": "handoff",
                             "hq_call_id": str(call.id)}).get_json()
    assert r["ok"] is True
    assert bridge.NO_ANSWER_LINE in tel.redirected[0]["twiml"]


def test_the_browser_is_rung_when_it_is_open(world):
    owner, s, agent, tel, va, client = world
    from dialer.models import RepPresence
    db.session.add(RepPresence(account_id=owner.id, user_id=owner.id,
                               on_shift=True, available_for_transfers=True,
                               last_seen_at=bridge._now()))
    db.session.commit()
    call = placed_call(owner, s, agent)
    tool(client, owner, {"disposition": "handoff", "hq_call_id": str(call.id)})
    leg = [c for c in tel.created if c.get("twiml")][0]
    assert leg["to"] == f"client:t{owner.id}_u{owner.id}"


def test_a_tool_call_from_another_account_s_id_is_refused(world, ctx):
    owner, s, agent, tel, va, client = world
    other = make_user(name="Else", email="x@n.test", dialer=True)
    get_settings(other.id)
    db.session.commit()
    call = placed_call(owner, s, agent)
    r = client.post("/dialer/hooks/elevenlabs/tools/set_disposition",
                    json={"disposition": "handoff", "hq_call_id": str(call.id)},
                    headers={"X-HQ-Token": account_token(other.id)}).get_json()
    assert r["ok"] is False
    assert tel.redirected == []


# ------------------------------------------------- the post-call webhook
def test_the_post_call_webhook_finds_an_owned_call_by_our_id(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    assert not call.elevenlabs_conversation_id
    client.post("/dialer/hooks/elevenlabs/post-call", json={"data": {
        "conversation_id": "conv_after", "agent_id": "ag_1",
        "conversation_initiation_client_data": {
            "dynamic_variables": {"hq_call_id": str(call.id)}},
        "transcript": [{"role": "agent", "message": "Hi, can I speak with the owner?"}],
        "metadata": {"call_duration_secs": 33}}})
    from dialer import processor
    processor.process_all(account_id=owner.id)
    c = db.session.get(Call, call.id)
    assert c.status == "completed"
    assert c.elevenlabs_conversation_id == "conv_after"
    assert "speak with the owner" in (c.transcript or "")


# -------------------------------------------------------- the install
def test_the_guide_install_chooses_seamless(world):
    owner, s, agent, tel, va, client = world
    client.post("/dialer/playbooks/napkin", follow_redirects=True,
                data={"transfer_to": HUMAN})
    from dialer import napkin
    pb = Playbook.query.filter_by(account_id=owner.id, name=napkin.NAME).one()
    a = AiAgent.query.filter_by(playbook_id=pb.id).one()
    assert a.transfer_handoff == "owned"


def test_the_choice_is_on_the_agent_page(world):
    owner, s, agent, tel, va, client = world
    body = client.get(f"/dialer/agents/{agent.id}").get_data(as_text=True)
    assert "we hold the line" in body
