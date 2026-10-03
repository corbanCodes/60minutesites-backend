"""The works, seconds after the call, with no worker running.

Railway runs the web process and nothing else. Every webhook was written
to the inbox and never read, so no transcript, summary, recording or
grade ever reached a call page. The hooks now fold each event in as it
arrives, and the pages poll until the last piece lands.
"""
import pytest

from app import Note, db
from dialer import calls as calls_mod
from dialer.models import Call, CallEvent
from dialer.providers import registry
from dialer.results import results_for
from dialer.tools import account_token, run_tool
from tests.test_owned_handoff import world, placed_call, PROSPECT  # noqa: F401


def kinds(call_id):
    return [e.kind for e in CallEvent.query.filter_by(call_id=call_id)
            .order_by(CallEvent.at, CallEvent.id)]


def post_call(client, call, summary="Reached the owner and handed over."):
    return client.post("/dialer/hooks/elevenlabs/post-call", json={"data": {
        "conversation_id": "conv_x", "agent_id": "ag_1",
        "conversation_initiation_client_data": {
            "dynamic_variables": {"hq_call_id": str(call.id)}},
        "transcript": [{"role": "agent", "message": "Hi, can I speak with the owner?"},
                       {"role": "user", "message": "Speaking."}],
        "analysis": {"transcript_summary": summary},
        "metadata": {"call_duration_secs": 33}}})


def status(client, owner, call, st, **extra):
    return client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                       data={"CallSid": call.twilio_sid, "CallStatus": st, **extra})


class GradingLLM:
    def complete(self, system, user, max_tokens=800, json_mode=False):
        assert "grade only the human" in user
        return {"ok": True, "data": {"score": 8, "reasons": ["Warm open"],
                                     "advice": "Ask for the booking sooner.",
                                     "handoff_moment": "Seamless; not noticed.",
                                     "prospect_said": "Wants napkins next week."}}


class STT:
    def transcribe(self, audio, mimetype="audio/mpeg", dual_channel=False):
        return {"ok": True, "text": "agent: Hi, can I speak with the owner?\n"
                                    "prospect: Speaking.\nagent: Oh, okay. Thanks.\n"
                                    "rep: Hey, this is Corban with NapkinAds."}


def _graded_world(world, monkeypatch):
    owner, s, agent, tel, va, client = world
    tel.fetch_recording = lambda sid: {"ok": True, "content": b"RIFF", "mimetype": "audio/wav"}
    monkeypatch.setattr(registry, "llm", lambda settings: GradingLLM())
    monkeypatch.setattr(registry, "transcriber", lambda settings: STT())
    monkeypatch.setattr(registry, "simulating", lambda settings=None: True)
    return owner, s, agent, tel, va, client


# ------------------------------------------------------ no worker needed
def test_the_post_call_webhook_lands_on_the_call_at_once(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    post_call(client, call)
    c = db.session.get(Call, call.id)
    assert c.transcript.startswith("agent: Hi")
    assert c.summary == "Reached the owner and handed over."
    assert c.status == "completed" and c.finalized_at


def test_a_status_event_lands_at_once_too(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    status(client, owner, call, "completed", CallDuration="95")
    c = db.session.get(Call, call.id)
    assert c.status == "completed" and c.duration_s == 95 and c.ended_at


def test_a_row_that_fails_is_kept_with_its_error(world, monkeypatch):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    from dialer import processor
    monkeypatch.setattr(processor, "_twilio", lambda row, p: 1 / 0)
    status(client, owner, call, "completed")
    from dialer.models import WebhookInbox
    row = WebhookInbox.query.filter_by(account_id=owner.id).order_by(WebhookInbox.id.desc()).first()
    assert row.processed_at is None and "division" in row.error and row.attempts == 1


# ---------------------------------------------- the AI part is not the end
def test_the_ai_ending_does_not_end_a_handed_off_call(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    run_tool("set_disposition", {"disposition": "handoff", "hq_call_id": str(call.id)},
             account_token(owner.id))
    post_call(client, call)
    c = db.session.get(Call, call.id)
    assert c.status == "in-progress" and c.ended_at is None
    assert c.transcript and c.summary
    assert "ai_part_done" in kinds(call.id)
    assert not c.finalized_at
    status(client, owner, call, "completed", CallDuration="240")
    c = db.session.get(Call, call.id)
    assert c.status == "completed" and c.duration_s == 240 and c.finalized_at


# ---------------------------------------------------------- the grade
def test_the_recording_is_transcribed_and_the_human_part_graded(world, monkeypatch):
    owner, s, agent, tel, va, client = _graded_world(world, monkeypatch)
    call = placed_call(owner, s, agent)
    run_tool("set_disposition", {"disposition": "handoff", "hq_call_id": str(call.id)},
             account_token(owner.id))
    post_call(client, call)
    status(client, owner, call, "completed", CallDuration="240")
    client.post(f"/dialer/hooks/twilio/recording/{owner.id}",
                data={"CallSid": call.twilio_sid, "RecordingSid": "RE1",
                      "RecordingUrl": "https://api.twilio.com/x", "RecordingDuration": "240"})
    c = db.session.get(Call, call.id)
    assert c.recording_sid == "RE1"
    assert "rep: Hey, this is Corban" in c.handoff_transcript
    assert c.handoff_score == 8
    assert c.handoff_coaching["advice"] == "Ask for the booking sooner."
    assert "handoff_graded" in kinds(call.id)


def test_without_a_key_the_grade_says_why_it_stopped(world, monkeypatch):
    owner, s, agent, tel, va, client = world
    monkeypatch.setattr(registry, "simulating", lambda settings=None: False)
    s.llm_key_enc = None
    db.session.commit()
    call = placed_call(owner, s, agent)
    run_tool("set_disposition", {"disposition": "handoff", "hq_call_id": str(call.id)},
             account_token(owner.id))
    call = db.session.get(Call, call.id)
    call.recording_sid, call.status = "RE1", "completed"
    db.session.commit()
    calls_mod.grade_handoff(call, s)
    r = results_for(db.session.get(Call, call.id))
    assert r["handoff_score"] is None
    assert r["pending_grade"].startswith("Not graded: no transcription key")
    assert "the grade" not in r["pending"]


def test_grading_twice_does_not_pay_twice(world, monkeypatch):
    owner, s, agent, tel, va, client = _graded_world(world, monkeypatch)
    calls = []
    class Counting(GradingLLM):
        def complete(self, *a, **k):
            calls.append(1)
            return super().complete(*a, **k)
    monkeypatch.setattr(registry, "llm", lambda settings: Counting())
    call = placed_call(owner, s, agent)
    run_tool("set_disposition", {"disposition": "handoff", "hq_call_id": str(call.id)},
             account_token(owner.id))
    call = db.session.get(Call, call.id)
    call.recording_sid, call.status = "RE1", "completed"
    db.session.commit()
    calls_mod.grade_handoff(call, s)
    calls_mod.grade_handoff(call, s)
    assert len(calls) == 1


# --------------------------------------------------------- the pages
def test_the_results_feed_has_the_works(world, monkeypatch):
    owner, s, agent, tel, va, client = _graded_world(world, monkeypatch)
    call = placed_call(owner, s, agent)
    run_tool("log_note", {"note": "Mike is the owner, in after 4.",
                          "hq_call_id": str(call.id)}, account_token(owner.id))
    run_tool("set_disposition", {"disposition": "handoff", "hq_call_id": str(call.id)},
             account_token(owner.id))
    r = client.get(f"/dialer/calls/{call.id}/results.json").get_json()
    assert r["ok"] and r["handed_off"] and r["notes"] == ["Mike is the owner, in after 4."]
    assert "the call to end" in r["pending"]
    assert r["pending_grade"] == "Graded once the recording arrives."
    post_call(client, call)
    status(client, owner, call, "completed", CallDuration="240")
    client.post(f"/dialer/hooks/twilio/recording/{owner.id}",
                data={"CallSid": call.twilio_sid, "RecordingSid": "RE1",
                      "RecordingUrl": "https://api.twilio.com/x", "RecordingDuration": "240"})
    r2 = client.get(f"/dialer/calls/{call.id}/results.json").get_json()
    assert r2["handoff_score"] == 8 and r2["has_recording"] and r2["pending"] == []
    assert r2["version"] > r["version"]
    body = client.get(f"/dialer/calls/{call.id}").get_data(as_text=True)
    assert "The hand-off" in body and "8/10" in body
    assert "Notes the AI took" in body and "Mike is the owner" in body
    assert "rep: Hey, this is Corban" in body


def test_the_call_page_polls_while_pieces_are_still_landing(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    body = client.get(f"/dialer/calls/{call.id}").get_data(as_text=True)
    assert "results.json" in body and "Still waiting for" in body
    status(client, owner, call, "completed", CallDuration="10")
    post_call(client, call)
    call = db.session.get(Call, call.id)
    call.recording_sid = "RE1"
    db.session.commit()
    body = client.get(f"/dialer/calls/{call.id}").get_data(as_text=True)
    assert "Still waiting for" not in body


def test_the_test_page_shows_the_last_test_call_live(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    body = client.get("/dialer/setup/12").get_data(as_text=True)
    assert f'data-call-id="{call.id}"' in body and "results.json" in body


def test_another_account_cannot_read_the_feed(world, ctx):
    owner, s, agent, tel, va, client = world
    from tests.conftest import make_user
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = Call(account_id=other.id, mode="ai_outbound", direction="outbound",
                  to_number="+12125550000", status="queued")
    db.session.add(theirs)
    db.session.commit()
    assert client.get(f"/dialer/calls/{theirs.id}/results.json").status_code == 403


# ------------------------------------------------------- the recording
def test_an_owned_test_call_is_recorded_from_the_answer(world):
    owner, s, agent, tel, va, client = world
    from dialer.models import PhoneNumber
    ai = PhoneNumber.query.filter_by(account_id=owner.id, e164="+18655550102").one()
    client.post("/dialer/test-call", data={"to_number": PROSPECT, "agent_id": agent.id,
                                           "from_number_id": ai.id})
    leg = tel.created[-1]
    assert leg["record"] is True
    assert "/twilio/recording/" in leg["recording_status_callback"]
