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
        self.configured = []
        self.hungup = []

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        self.created.append({"to": to, "from_": from_, "url": url,
                             "status_callback": status_callback, **kw})
        return {"ok": True, "sid": "CArep1"}

    def redirect_call(self, sid, twiml):
        self.redirected.append({"sid": sid, "twiml": twiml})
        return {"ok": True}

    def configure_number(self, sid, voice_url, status_callback):
        self.configured.append({"sid": sid, "voice_url": voice_url,
                                "status_callback": status_callback})
        return {"ok": True}

    current_voice_url = ""

    def fetch_number(self, sid):
        return {"ok": True, "voice_url": self.current_voice_url,
                "status_callback": ""}

    def hangup(self, sid):
        self.hungup.append(sid)
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


def test_an_unknown_caller_id_during_a_live_ai_call_is_still_a_handoff(world):
    """The second live test. The webhook reached us, but From was neither
    the AI's number nor the prospect's -- ElevenLabs never documents what
    a blind transfer presents -- so the call fell through to the voicemail
    greeting. A call on the hand-off line while an AI call is live on a
    bridge agent IS the hand-off, whatever the caller ID says."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    found = bridge.detect(owner.id, "+12125550000", LINE)
    assert found is not None
    assert found[1].id == call.id


def test_anonymous_caller_id_is_handled_the_same_way(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    assert bridge.detect(owner.id, "anonymous", LINE) is not None
    assert bridge.detect(owner.id, "", LINE) is not None


def test_the_fallback_needs_a_live_call_on_a_bridge_agent(world):
    """An ordinary inbound caller minutes after the AI call ended must
    still get the ordinary treatment."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    call.status = "completed"
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is None


def test_the_fallback_ignores_agents_not_on_the_bridge(world):
    owner, s, agent, fake, client = world
    agent.transfer_handoff = "blind"
    db.session.commit()
    live_call(owner, s, agent)
    assert bridge.detect(owner.id, "+12125550000", LINE) is None


def test_the_fallback_window_covers_a_whole_conversation(world):
    """A 5-minute window measured from row creation cut off any call that
    reached the decision maker after minute four and a half. started_at is
    stamped before the vendor even dials."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    call.started_at = bridge._now() - bridge.LIVE_WINDOW / 2
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is not None
    call.started_at = bridge._now() - bridge.LIVE_WINDOW * 2
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is None


def test_two_live_bridge_calls_means_no_guessing(world):
    """Bridging a guess would hand a stranger to the rep as the prospect."""
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    lead2 = make_lead(owner_id=owner.id, phone="+18655557777")
    c2 = calls_mod.start_call(owner.id, lead2, "ai_outbound", s,
                              from_number=AI, ai_agent=agent)
    c2.status = "in-progress"
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is None
    # ...but a caller ID that matches one of them still works.
    assert bridge.detect(owner.id, PROSPECT, LINE)[1].to_number == PROSPECT


def test_a_call_the_vendor_already_marked_completed_is_still_a_handoff(world):
    """The race behind "Thanks for calling NapkinAds". A blind transfer ends
    the ElevenLabs conversation the instant it fires; their post-call
    webhook marks the Call completed before Twilio reaches /voice with the
    transferred leg. Every signal used to exclude completed calls."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    call.status = "completed"
    call.ended_at = bridge._now()
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is not None
    assert bridge.detect(owner.id, PROSPECT, LINE) is not None
    assert bridge.detect(owner.id, AI, LINE) is not None


def test_a_call_that_ended_a_while_ago_is_not_a_handoff(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    call.status = "completed"
    call.ended_at = bridge._now() - bridge.ENDED_GRACE * 3
    db.session.commit()
    assert bridge.detect(owner.id, "+12125550000", LINE) is None


def test_the_post_call_webhook_landing_first_does_not_lose_the_handoff(world):
    """End to end: the vendor's post-call hook is processed, THEN the
    transferred leg arrives."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    call.elevenlabs_conversation_id = "conv1"
    db.session.commit()
    client.post("/dialer/hooks/elevenlabs/post-call", json={"data": {
        "conversation_id": "conv1", "agent_id": "ag_1",
        "transcript": [{"role": "agent", "message": "Oh, okay. Thanks."}],
        "metadata": {"call_duration_secs": 40}}})
    from dialer import processor
    processor.process_all(account_id=owner.id)
    assert db.session.get(Call, call.id).status == "completed"

    body = handoff(client, owner, frm="+12125550000")
    assert "<Conference" in body
    assert "Thanks for calling" not in body


def test_the_full_hook_bridges_an_unknown_caller_id(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    body = handoff(client, owner, frm="+12125550000")
    assert "<Conference" in body
    assert "Thanks for calling" not in body
    assert len(fake.created) == 1


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
    assert f'waitUrl="' in body and f"/twilio/{owner.id}/bridge/wait" in body
    assert "handoff-office.mp3" not in body, (
        "a bare file at waitUrl plays once then silence; it must be the "
        "looping document")
    assert 'waitMethod="GET"' in body
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


def test_a_phone_rep_leg_carries_machine_detection(world):
    """Voicemail answers like a person would, and would start the room and
    read the rep's greeting to the prospect."""
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    handoff(client, owner)
    leg = fake.created[0]
    assert leg["machine_detection"] == "Enable"
    assert leg["async_amd"] is True
    assert leg["amd_status_callback"].endswith(
        f"/twilio/{owner.id}/bridge/handoff-CAprospect1/amd")
    assert leg["timeout"] == 15


def test_a_browser_rep_leg_has_no_machine_detection(world):
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    db.session.commit()
    present(owner.id, owner.id)
    live_call(owner, s, agent)
    handoff(client, owner)
    assert "machine_detection" not in fake.created[0]


def test_the_room_is_stored_on_the_call_that_was_handed_off(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    assert db.session.get(Call, call.id).conference_name == "handoff-CAprospect1"


def test_voicemail_picking_up_the_rep_frees_the_prospect_and_drops_the_leg(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/amd",
                data={"AnsweredBy": "machine_start", "CallSid": "CArep1"})
    assert fake.redirected[0]["sid"] == "CAprospect1"
    assert bridge.NO_ANSWER_LINE in fake.redirected[0]["twiml"]
    assert fake.hungup == ["CArep1"]
    assert db.session.get(Call, call.id).disposition == "callback"


def test_a_human_answering_the_rep_leg_is_left_alone(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/amd",
                data={"AnsweredBy": "human", "CallSid": "CArep1"})
    assert fake.redirected == [] and fake.hungup == []


def test_a_failed_handoff_is_booked_on_the_right_call_not_the_newest(world):
    """The old fallback stamped the callback on whichever AI call was
    newest. With two live calls that is somebody else's lead."""
    owner, s, agent, fake, client = world
    first = live_call(owner, s, agent)
    handoff(client, owner, sid="CAfirst")            # room handoff-CAfirst
    lead2 = make_lead(owner_id=owner.id, phone="+18655557777")
    newer = calls_mod.start_call(owner.id, lead2, "ai_outbound", s,
                                 from_number=AI, ai_agent=agent)
    newer.status = "in-progress"
    db.session.commit()
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAfirst/rep",
                data={"CallStatus": "no-answer", "CallSid": "CArep1"})
    assert db.session.get(Call, first.id).disposition == "callback"
    assert not db.session.get(Call, newer.id).disposition


def test_a_second_leg_for_the_same_call_does_not_ring_the_rep_again(world):
    """A vendor that believes its transfer failed retries it, and Twilio
    retries webhooks. On one live test that was a new leg every thirteen
    seconds for eight minutes. One rep leg per hand-off."""
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    first = handoff(client, owner, sid="CAfirst")
    again = handoff(client, owner, sid="CAsecond")
    assert len(fake.created) == 1, "the rep was rung twice"
    assert "handoff-CAfirst" in first
    assert "handoff-CAfirst" in again, "the retry joins the existing room"
    kinds = [e.kind for e in CallEvent.query.filter_by(call_id=call.id)]
    assert "handoff_repeat" in kinds


def test_a_leg_long_after_the_first_handoff_rings_again(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner, sid="CAfirst")
    ev = (CallEvent.query.filter_by(call_id=call.id, kind="handoff")
          .order_by(CallEvent.at.desc()).first())
    ev.at = bridge._now() - bridge.REPEAT_WINDOW * 2
    db.session.commit()
    handoff(client, owner, sid="CAsecond")
    assert len(fake.created) == 2


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


# --------------------------------------------------- who the rep leg rings
def present(owner_id, user_id, fresh=True, available=True):
    from dialer.models import RepPresence
    from datetime import timedelta
    p = RepPresence(account_id=owner_id, user_id=user_id, on_shift=True,
                    available_for_transfers=available,
                    last_seen_at=bridge._now() - (timedelta(seconds=10) if fresh
                                                  else timedelta(hours=5)))
    db.session.add(p)
    db.session.commit()
    return p


def test_a_typed_number_always_wins(world):
    owner, s, agent, fake, client = world
    present(owner.id, owner.id)
    assert bridge.rep_destination(s, owner.id, agent) == HUMAN


def test_with_no_number_the_browser_phone_rings_when_someone_is_there(world):
    """What "get me ready to answer in my UI" means: the browser is what
    shows the lead and the transcript as the call arrives."""
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    db.session.commit()
    present(owner.id, owner.id)
    assert bridge.rep_destination(s, owner.id, agent) == \
        f"client:t{owner.id}_u{owner.id}"


def test_a_stale_browser_presence_is_not_rung(world):
    """A tab closed yesterday still has a row. Ringing it rings nothing
    for twenty seconds and then apologises to the prospect."""
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    s.ai_callback_number = "+18655550199"
    db.session.commit()
    present(owner.id, owner.id, fresh=False)
    assert bridge.rep_destination(s, owner.id, agent) == "+18655550199"


def test_a_rep_marked_unavailable_is_not_rung(world):
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    s.ai_callback_number = "+18655550199"
    db.session.commit()
    present(owner.id, owner.id, available=False)
    assert bridge.rep_destination(s, owner.id, agent) == "+18655550199"


def test_number_mode_on_the_account_skips_the_browser(world):
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    s.transfer_mode = "number"
    s.transfer_number = "+18655550177"
    db.session.commit()
    present(owner.id, owner.id)
    assert bridge.rep_destination(s, owner.id, agent) == "+18655550177"


def test_the_browser_leg_is_a_client_call_into_the_room(world):
    owner, s, agent, fake, client = world
    agent.transfer_to_number = ""
    db.session.commit()
    present(owner.id, owner.id)
    live_call(owner, s, agent)
    handoff(client, owner)
    assert fake.created[0]["to"] == f"client:t{owner.id}_u{owner.id}"
    assert "handoff-CAprospect1" in fake.created[0]["twiml"]


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


# ----------------------------------------------- the webhook on the line
def test_ensure_line_points_the_rep_lines_webhook_at_this_app(world):
    """The first live test: transfer fired, ElevenLabs dialled the rep
    line, Twilio said "an application error has occurred", and no request
    ever reached /voice. The number's webhook was not ours. It is set by
    the app now, not assumed."""
    owner, s, agent, fake, client = world
    r = bridge.ensure_line(s, owner.id)
    assert r["ok"] is True
    assert r["line"].e164 == LINE
    assert len(fake.configured) == 1
    c = fake.configured[0]
    assert c["sid"] == "PN" + "a" * 32
    assert c["voice_url"].endswith(f"/dialer/hooks/twilio/{owner.id}/voice")
    assert c["status_callback"].endswith(
        f"/dialer/hooks/twilio/{owner.id}/status")


def test_ensure_line_leaves_a_line_already_pointed_here_alone(world):
    owner, s, agent, fake, client = world
    from dialer import urls
    fake.current_voice_url = urls.twilio_voice(owner.id)
    r = bridge.ensure_line(s, owner.id)
    assert r["ok"] is True and r["changed"] is False
    assert fake.configured == []


def test_ensure_line_keeps_the_old_webhook_on_the_row(world):
    """An imported number may be the customer's main line running their
    own IVR. The URL it had is kept so it can be put back."""
    owner, s, agent, fake, client = world
    fake.current_voice_url = "https://their-ivr.example.com/answer"
    bridge.ensure_line(s, owner.id)
    line = PhoneNumber.query.filter_by(e164=LINE).one()
    assert "their-ivr.example.com/answer" in (line.notes or "")
    assert len(fake.configured) == 1


def test_ensure_line_never_touches_an_ai_number(world):
    owner, s, agent, fake, client = world
    bridge.ensure_line(s, owner.id)
    assert all(c["sid"] != "PN" + "b" * 32 for c in fake.configured)


def test_ensure_line_with_no_rep_number_says_so(world):
    owner, s, agent, fake, client = world
    PhoneNumber.query.filter_by(e164=LINE).delete()
    db.session.commit()
    r = bridge.ensure_line(s, owner.id)
    assert r["ok"] is False and r["line"] is None
    assert fake.configured == []


def test_saving_an_agent_on_the_bridge_repoints_the_line(world):
    owner, s, agent, fake, client = world
    client.post(f"/dialer/agents/{agent.id}", follow_redirects=True,
                data={"name": agent.name, "transfer_handoff": "bridge"})
    assert any(c["sid"] == "PN" + "a" * 32 for c in fake.configured)


class FakeVoiceAgent:
    def __init__(self):
        self.upserts = []

    def upsert_agent(self, agent, prompt, tools, **kw):
        self.upserts.append(kw)
        return {"ok": True, "agent_id": agent.elevenlabs_agent_id or "ag_new"}

    def list_voices(self, limit=40):
        return {"ok": True, "voices": []}

    def get_agent(self, agent_id):
        return {"ok": True}


def test_choosing_the_bridge_on_plain_save_still_tells_the_vendor(world, monkeypatch):
    """The destination lives at ElevenLabs and only a sync puts it there.
    Switching to the bridge and pressing Save left the vendor dialling the
    old destination: a normal ring, hold music, no bridge."""
    owner, s, agent, fake, client = world
    va = FakeVoiceAgent()
    monkeypatch.setattr(registry, "voice_agent", lambda settings: va)
    agent.transfer_handoff = "blind"
    db.session.commit()
    client.post(f"/dialer/agents/{agent.id}", follow_redirects=True,
                data={"name": agent.name, "transfer_handoff": "bridge"})
    assert va.upserts, "no sync reached the vendor"
    dest = va.upserts[-1]["transfer"]["params"]["transfers"][0]
    assert dest["transfer_destination"]["phone_number"] == LINE
    assert dest["transfer_type"] == "blind"


def test_saving_an_agent_on_blind_leaves_the_line_alone(world):
    owner, s, agent, fake, client = world
    client.post(f"/dialer/agents/{agent.id}", follow_redirects=True,
                data={"name": agent.name, "transfer_handoff": "blind"})
    assert fake.configured == []


def test_installing_the_guide_repoints_the_line(world):
    owner, s, agent, fake, client = world
    client.post("/dialer/playbooks/napkin", follow_redirects=True,
                data={"transfer_to": HUMAN})
    assert any(c["sid"] == "PN" + "a" * 32 for c in fake.configured)


def test_moving_a_number_into_the_rep_pool_repoints_its_webhook(world):
    """The root cause. A number imported to ElevenLabs for the AI pool had
    its voice URL rewritten to ElevenLabs, and moving it back to reps left
    that in place, so every inbound call on it -- hand-off or not -- went
    to the wrong place."""
    owner, s, agent, fake, client = world
    n = PhoneNumber.query.filter_by(e164=AI).one()
    client.post(f"/dialer/numbers/{n.id}/pool", follow_redirects=True,
                data={"pool": "rep"})
    assert any(c["sid"] == "PN" + "b" * 32 and
               c["voice_url"].endswith(f"/twilio/{owner.id}/voice")
               for c in fake.configured)


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


def test_the_wait_document_plays_the_ambience_and_loops_forever(world):
    """Twilio loops hold audio one documented way: a TwiML document that
    ends in a blank <Redirect/>. Anything else goes silent after one play."""
    owner, s, agent, fake, client = world
    body = client.get(f"/dialer/hooks/twilio/{owner.id}/bridge/wait"
                      ).get_data(as_text=True)
    assert "<Play>" in body and "handoff-office.mp3" in body
    assert "<Redirect/>" in body
    for banned in ("<Dial", "<Gather", "<Hangup", "<Record"):
        assert banned not in body, "not permitted inside a waitUrl document"


def test_the_wait_document_is_served_without_a_signature(world):
    """A failed waitUrl request means the conference is never established,
    so this must answer even when Twilio's signature cannot be checked."""
    owner, s, agent, fake, client = world
    r = client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/wait")
    assert r.status_code == 200


def test_the_choice_is_on_the_agent_page_with_the_line_named(world):
    owner, s, agent, fake, client = world
    body = client.get(f"/dialer/agents/{agent.id}").get_data(as_text=True)
    assert "no ring, no hold music" in body
    assert "hand-off line is" in body


def test_a_sample_number_is_never_the_handoff_line(world):
    """Sample rows have invented SIDs and the lowest ids, so a plain
    first() would hand a live prospect to a 555 number."""
    owner, s, agent, fake, client = world
    from dialer.demo import DEMO_PREFIX
    # Put the sample at a LOWER id than the only real rep line.
    PhoneNumber.query.filter_by(e164=LINE).delete()
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550001",
                               twilio_sid="PNdemo0001", pool="rep",
                               state="active",
                               friendly_name=DEMO_PREFIX + "Sample"))
    db.session.commit()
    db.session.add(PhoneNumber(account_id=owner.id, e164="+14405550101",
                               twilio_sid="PN" + "c" * 32, pool="rep",
                               state="active", friendly_name="Real line"))
    db.session.commit()
    sample = PhoneNumber.query.filter_by(e164="+18655550001").one()
    real = PhoneNumber.query.filter_by(e164="+14405550101").one()
    assert sample.id < real.id
    assert bridge.handoff_line(owner.id).e164 == "+14405550101"
