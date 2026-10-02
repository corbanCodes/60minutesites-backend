"""Webhooks: signature handling, idempotency, and the inbox -> processor path."""
import json

import pytest

from app import Lead, db
from dialer import calls as calls_mod
from dialer.models import Call, PhoneNumber, WebhookInbox
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user


@pytest.fixture
def acct(ctx):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.enforce_window = False
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550101",
                               pool="rep", state="active", area_code="865"))
    db.session.commit()
    return owner, s


def _call(owner, s, phone="8655551231"):
    lead = make_lead(owner_id=owner.id, phone=phone)
    call = calls_mod.start_call(owner.id, lead, "power", s,
                                from_number="+18655550101")
    call.twilio_sid = "CAtest123"
    db.session.commit()
    return call


# ---------------------------------------------------------------- inbox
def test_status_webhook_is_accepted_and_queued(acct, client):
    owner, s = acct
    call = _call(owner, s)
    r = client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                    data={"CallSid": call.twilio_sid, "CallStatus": "ringing"})
    assert r.status_code == 204
    assert WebhookInbox.query.count() == 1
    assert WebhookInbox.query.first().kind == "status:ringing"


def test_the_same_event_twice_is_stored_once(acct, client):
    owner, s = acct
    call = _call(owner, s)
    payload = {"CallSid": call.twilio_sid, "CallStatus": "completed",
               "CallDuration": "42"}
    for _ in range(3):
        client.post(f"/dialer/hooks/twilio/{owner.id}/status", data=payload)
    assert WebhookInbox.query.count() == 1


def test_the_processor_folds_events_into_the_call(acct, client):
    owner, s = acct
    call = _call(owner, s)
    for status, extra in [("initiated", {}), ("ringing", {}),
                          ("in-progress", {"AnsweredBy": "human"}),
                          ("completed", {"CallDuration": "95"})]:
        client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                    data={"CallSid": call.twilio_sid, "CallStatus": status,
                          **extra})
    from dialer import processor
    res = processor.process_all(account_id=owner.id)
    assert res["failed"] == 0
    db.session.refresh(call)
    assert call.status == "completed"
    assert call.duration_s == 95
    assert call.billable_minutes == 2      # whole minutes, rounded up
    assert call.answered_live is True
    assert call.finalized_at is not None


def test_a_machine_answer_is_recorded_as_such(acct, client):
    owner, s = acct
    call = _call(owner, s, phone="8655551232")
    client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                data={"CallSid": call.twilio_sid, "CallStatus": "completed",
                      "AnsweredBy": "machine_end_beep", "CallDuration": "18"})
    from dialer import processor
    processor.process_all(account_id=owner.id)
    db.session.refresh(call)
    assert call.system_outcome == "answered_machine"
    assert call.answered_live is False


def test_an_unknown_call_sid_is_ignored_without_erroring(acct, client):
    owner, s = acct
    client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                data={"CallSid": "CAnope", "CallStatus": "completed"})
    from dialer import processor
    assert processor.process_all(account_id=owner.id)["failed"] == 0


# ------------------------------------------------------------- elevenlabs
def test_elevenlabs_post_call_fills_in_the_conversation(acct, client):
    owner, s = acct
    call = _call(owner, s)
    call.mode = "ai_outbound"
    call.elevenlabs_conversation_id = "cv_abc"
    db.session.commit()
    body = {"data": {
        "conversation_id": "cv_abc",
        "transcript": [{"role": "agent", "message": "Hi, this is an automated "
                                                    "AI assistant."},
                       {"role": "user", "message": "Sure, go ahead."}],
        "analysis": {"transcript_summary": "They were interested.",
                     "data_collection_results": {"tables": {"value": "40"}}},
        "metadata": {"call_duration_secs": 72, "cost": 13}}}
    r = client.post("/dialer/hooks/elevenlabs/post-call", json=body)
    assert r.status_code == 204
    from dialer import processor
    processor.process_all(account_id=owner.id)
    db.session.refresh(call)
    assert "automated AI assistant" in call.transcript
    assert call.duration_s == 72
    assert call.qualification.get("tables") == "40"
    assert call.finalized_at is not None


def test_the_init_webhook_always_returns_a_complete_variable_set(acct, client):
    owner, s = acct
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550199",
                               pool="ai", state="active"))
    make_lead(owner_id=owner.id, name="Dana Vance", phone="8655557777",
              business="The Tap Room")
    db.session.commit()

    known = client.post("/dialer/hooks/elevenlabs/init",
                        json={"caller_id": "+18655557777",
                              "called_number": "+18655550199"}).get_json()
    assert known["dynamic_variables"]["lead_name"] == "Dana Vance"
    assert known["dynamic_variables"]["is_known"] == "true"

    stranger = client.post("/dialer/hooks/elevenlabs/init",
                           json={"caller_id": "+12125551111",
                                 "called_number": "+18655550199"}).get_json()
    v = stranger["dynamic_variables"]
    assert v["is_known"] == "false"
    # every declared variable must be present or ElevenLabs treats it as a
    # failure rather than degrading
    assert set(v) == set(known["dynamic_variables"])


def test_a_broken_init_request_still_returns_usable_defaults(acct, client):
    r = client.post("/dialer/hooks/elevenlabs/init", json={"nonsense": True})
    v = r.get_json()["dynamic_variables"]
    assert v["lead_name"] and v["is_known"] == "false"


# ------------------------------------------------------------------ tools
def test_the_agent_tools_need_the_account_token(acct, client):
    owner, s = acct
    make_lead(owner_id=owner.id, name="Dana", phone="8655551231")
    r = client.post("/dialer/hooks/elevenlabs/tools/lookup_lead",
                    json={"phone": "+18655551231"})
    body = r.get_json() if r.is_json else {}
    assert body.get("ok") is False or r.status_code == 403


def test_lookup_note_followup_and_disposition_all_work(acct, client):
    owner, s = acct
    from dialer.tools import account_token
    from app import Note, Task
    lead = make_lead(owner_id=owner.id, name="Dana", phone="8655551231")
    call = _call(owner, s)
    call.elevenlabs_conversation_id = "cv_tools"
    call.lead_id = lead.id
    db.session.commit()
    hdr = {"X-HQ-Token": account_token(owner.id)}

    r = client.post("/dialer/hooks/elevenlabs/tools/lookup_lead",
                    json={"phone": "+18655551231"}, headers=hdr).get_json()
    assert r["found"] is True and r["name"] == "Dana"

    client.post("/dialer/hooks/elevenlabs/tools/log_note",
                json={"phone": "+18655551231", "note": "Wants a sample pack"},
                headers=hdr)
    assert Note.query.filter(Note.body.contains("sample pack")).count() == 1

    client.post("/dialer/hooks/elevenlabs/tools/book_followup",
                json={"phone": "+18655551231", "title": "Send samples",
                      "in_days": 2}, headers=hdr)
    assert Task.query.filter_by(title="Send samples").count() == 1

    client.post("/dialer/hooks/elevenlabs/tools/set_disposition",
                json={"conversation_id": "cv_tools", "disposition": "dnc"},
                headers=hdr)
    db.session.refresh(lead)
    assert lead.do_not_call is True


def test_one_accounts_token_cannot_read_another_accounts_lead(acct, client):
    owner, s = acct
    other = make_user(name="Other", email="x@n.test", dialer=True)
    get_settings(other.id)
    make_lead(owner_id=owner.id, name="Private", phone="8655551231")
    from dialer.tools import account_token
    r = client.post("/dialer/hooks/elevenlabs/tools/lookup_lead",
                    json={"phone": "+18655551231"},
                    headers={"X-HQ-Token": account_token(other.id)}).get_json()
    assert r["found"] is False


# ----------------------------------------------------------------- inbound
def test_an_inbound_call_creates_a_consented_lead(acct, client):
    owner, s = acct
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550150",
                               pool="rep", state="active", purpose="both"))
    db.session.commit()
    r = client.post(f"/dialer/hooks/twilio/{owner.id}/voice",
                    data={"From": "+18655558888", "To": "+18655550150",
                          "CallSid": "CAin1"})
    assert r.status_code == 200
    assert "<Response>" in r.get_data(as_text=True)
    lead = Lead.query.filter_by(owner_id=owner.id, phone_key="8655558888").first()
    assert lead is not None
    assert lead.source == "Inbound call"
    # they rang us, so this number is consented for a call back
    assert lead.consent_status == "inbound"


def test_an_inbound_call_with_no_rep_falls_through_to_voicemail(acct, client):
    owner, s = acct
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550150",
                               pool="rep", state="active"))
    db.session.commit()
    body = client.post(f"/dialer/hooks/twilio/{owner.id}/voice",
                       data={"From": "+18655558888", "To": "+18655550150",
                             "CallSid": "CAin2"}).get_data(as_text=True)
    assert "<Record" in body or "Say" in body


# ---------------------------------------------------------------- outgoing
def test_outgoing_twiml_announces_recording_and_records(acct, client):
    owner, s = acct
    s.recording_enabled = True
    s.recording_announce = True
    s.announce_text = "This call may be recorded."
    db.session.commit()
    body = client.post(f"/dialer/hooks/twilio/{owner.id}/outgoing",
                       data={"To": "+18655551231"}).get_data(as_text=True)
    assert "This call may be recorded." in body
    assert 'record="record-from-answer-dual"' in body
    assert "<Dial" in body


def test_a_rep_joining_a_shift_gets_a_conference(acct, client):
    owner, s = acct
    body = client.post(f"/dialer/hooks/twilio/{owner.id}/outgoing",
                       data={"conf": "t1_rep2_shift"}).get_data(as_text=True)
    assert "<Conference" in body and "t1_rep2_shift" in body
    assert 'endConferenceOnExit="true"' in body
