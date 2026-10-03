"""The silent hand-off, end to end, with the vendor stubbed out.

ElevenLabs has no quiet way to hand a call to a person: blind rings,
conference plays Twilio's classical playlist from a conference ElevenLabs
owns, sip_refer needs a SIP trunk. Verified against their spec. So the AI
blind-transfers to one of OUR rep-pool numbers, we answer it instantly,
park the prospect in our own room with office ambience as the wait audio,
and ring the rep into the same room.

The shape under test is exactly the setup test call: an AI outbound call
from the AI-pool number to the owner's phone, handed off to a second
phone. Everything that reaches Twilio is captured rather than sent.
"""
import pytest

from app import db
from dialer import bridge, calls as calls_mod
from dialer.agents import (human_number, transfer_collides, transfer_config,
                           transfer_number)
from dialer.models import AiAgent, Call, CallEvent, PhoneNumber, Playbook
from dialer.providers import registry
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user

LINE = "+18655550101"       # rep pool: its voice webhook points at us
AI = "+18655550102"         # AI pool: the number the agent calls from
PROSPECT = "+18655558888"   # the phone the AI rang (in the test, Corban's)
HUMAN = "+14235550147"      # the second phone the rep answers on


class FakeTelephony:
    def __init__(self):
        self.created = []
        self.redirected = []

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        self.created.append({"to": to, "from_": from_, "url": url,
                             "status_callback": status_callback, **kw})
        return {"ok": True, "sid": "CArep1"}

    def redirect_call(self, sid, twiml):
        self.redirected.append({"sid": sid, "twiml": twiml})
        return {"ok": True}


@pytest.fixture
def world(ctx, client, monkeypatch):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.enforce_window = False
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
                    transfer_handoff="bridge", transfer_to_number=HUMAN,
                    elevenlabs_agent_id="ag_1")
    db.session.add(agent)
    db.session.commit()
    fake = FakeTelephony()
    monkeypatch.setattr(registry, "telephony", lambda settings: fake)
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, agent, fake, client


def live_call(owner, s, agent):
    """What the setup test call creates: AI rings the prospect."""
    lead = make_lead(owner_id=owner.id, phone=PROSPECT)
    call = calls_mod.start_call(owner.id, lead, "ai_outbound", s,
                                from_number=AI, ai_agent=agent)
    call.status = "in-progress"
    db.session.commit()
    return call


def handoff(client, owner, sid="CAprospect1", frm=AI, to=LINE):
    return client.post(f"/dialer/hooks/twilio/{owner.id}/voice",
                       data={"From": frm, "To": to, "CallSid": sid}
                       ).get_data(as_text=True)


# ------------------------------------------------------------ recognising it
def test_a_call_from_our_own_ai_number_to_our_rep_line_is_a_handoff(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    found = bridge.detect(owner.id, AI, LINE)
    assert found is not None
    assert found[0].id == agent.id
    assert found[1].id == call.id


def test_the_prospects_own_number_on_a_live_ai_call_is_also_a_handoff(world):
    """Second signal, in case the carrier presents the prospect rather than
    the AI's number as From."""
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    assert bridge.detect(owner.id, PROSPECT, LINE) is not None


def test_a_stranger_calling_the_rep_line_is_not_a_handoff(world):
    owner, s, agent, fake, client = world
    assert bridge.detect(owner.id, "+12125550000", LINE) is None


def test_a_call_to_any_number_but_the_line_is_not_a_handoff(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    assert bridge.detect(owner.id, AI, AI) is None


def test_the_line_is_a_rep_number_never_an_ai_number(world):
    """An AI-pool number's inbound goes to ElevenLabs. Handing off to one
    would start a second AI conversation."""
    owner, s, agent, fake, client = world
    assert bridge.handoff_line(owner.id).e164 == LINE


# ------------------------------------------------------- what the vendor dials
def test_the_vendor_is_told_to_dial_our_line_blind(world):
    owner, s, agent, fake, client = world
    cfg = transfer_config(agent, s)["params"]["transfers"][0]
    assert cfg["transfer_destination"]["phone_number"] == LINE
    assert cfg["transfer_type"] == "blind"


def test_the_person_is_still_the_person(world):
    owner, s, agent, fake, client = world
    assert transfer_number(s, agent) == LINE
    assert human_number(s, agent) == HUMAN


def test_with_no_rep_line_it_falls_back_to_ringing_the_person(world):
    owner, s, agent, fake, client = world
    PhoneNumber.query.filter_by(e164=LINE).delete()
    db.session.commit()
    cfg = transfer_config(agent, s)["params"]["transfers"][0]
    assert cfg["transfer_destination"]["phone_number"] == HUMAN
    assert cfg["transfer_type"] == "blind"


def test_the_collision_check_is_against_the_person_not_the_line(world):
    """Testing on the phone the rep will answer on is still the trap."""
    owner, s, agent, fake, client = world
    assert transfer_collides(agent, s, HUMAN) is True
    assert transfer_collides(agent, s, LINE) is False


# ----------------------------------------------------------- the two legs
def test_the_prospect_is_parked_with_our_ambience_not_twilios_music(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    body = handoff(client, owner)
    assert "<Conference" in body
    assert 'waitUrl="' in body and "handoff-office.mp3" in body
    assert 'startConferenceOnEnter="false"' in body
    assert 'beep="false"' in body
    assert "handoff-CAprospect1" in body
    assert "<Say" not in body, "nothing is announced to the prospect"
    assert "<Record" not in body and "<Client" not in body


def test_the_rep_is_rung_into_the_same_room_in_the_same_request(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    handoff(client, owner)
    assert len(fake.created) == 1
    leg = fake.created[0]
    assert leg["to"] == HUMAN
    assert leg["from_"] == LINE
    assert leg["timeout"] == bridge.REP_RING_SECONDS
    assert "handoff-CAprospect1" in leg["twiml"]
    assert 'startConferenceOnEnter="true"' in leg["twiml"]
    assert 'endConferenceOnExit="true"' in leg["twiml"]
    assert leg["status_callback"].endswith(
        f"/twilio/{owner.id}/bridge/handoff-CAprospect1/rep")


def test_the_handoff_is_recorded_on_the_ai_call(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    kinds = [e.kind for e in CallEvent.query.filter_by(call_id=call.id)]
    assert "handoff" in kinds


def test_a_handoff_never_creates_a_lead_or_reaches_voicemail(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    from app import Lead
    before = Lead.query.filter_by(owner_id=owner.id).count()
    body = handoff(client, owner)
    assert Lead.query.filter_by(owner_id=owner.id).count() == before
    assert "leave a message" not in body


def test_an_ordinary_caller_still_gets_the_ordinary_treatment(world):
    owner, s, agent, fake, client = world
    body = handoff(client, owner, sid="CAin9", frm="+12125550000")
    assert "<Conference" not in body
    assert fake.created == []


# ------------------------------------------------------- when nobody picks up
def test_a_rep_who_does_not_answer_frees_the_prospect_politely(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/rep",
                data={"CallStatus": "no-answer", "CallSid": "CArep1"})
    assert len(fake.redirected) == 1
    assert fake.redirected[0]["sid"] == "CAprospect1"
    assert bridge.NO_ANSWER_LINE in fake.redirected[0]["twiml"]
    assert "<Hangup/>" in fake.redirected[0]["twiml"]
    assert db.session.get(Call, call.id).disposition == "callback"


@pytest.mark.parametrize("status", ["initiated", "ringing", "answered",
                                    "in-progress", "completed"])
def test_a_rep_leg_that_is_fine_is_left_alone(world, status):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/rep",
                data={"CallStatus": status, "CallSid": "CArep1"})
    assert fake.redirected == []


def test_no_person_to_ring_does_not_strand_them_in_a_silent_room(world):
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    s.ai_callback_number = ""
    s.transfer_mode = ""
    db.session.commit()
    live_call(owner, s, agent)
    body = handoff(client, owner)
    assert bridge.NO_ANSWER_LINE in body
    assert "<Conference" not in body


# ------------------------------------------------------------ the install
def test_installing_the_guide_chooses_the_bridge_when_a_line_exists(world):
    owner, s, agent, fake, client = world
    client.post("/dialer/playbooks/napkin", follow_redirects=True,
                data={"transfer_to": HUMAN})
    from dialer import napkin
    pb = Playbook.query.filter_by(account_id=owner.id, name=napkin.NAME).one()
    a = AiAgent.query.filter_by(playbook_id=pb.id).one()
    assert a.transfer_handoff == "bridge"


# ------------------------------------------------------------ the ambience
def test_the_ambience_loop_is_served_where_the_room_expects_it(world):
    owner, s, agent, fake, client = world
    r = client.get("/static-admin/handoff-office.mp3")
    assert r.status_code == 200
    assert r.mimetype in ("audio/mpeg", "audio/mp3")
    assert bridge.ambience_url().endswith("/static-admin/handoff-office.mp3")


def test_the_choice_is_on_the_agent_page_with_the_line_named(world):
    owner, s, agent, fake, client = world
    body = client.get(f"/dialer/agents/{agent.id}").get_data(as_text=True)
    assert "no ring, no hold music" in body
    assert "hand-off line is" in body
