"""The JSON endpoints the phone talks to. No templates involved."""
import json

import pytest

from app import Lead, Note, db
from dialer.models import (Call, Campaign, CampaignLead, PhoneNumber,
                           RepPresence, Suppression, VoicemailDrop)
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user


@pytest.fixture
def floor(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, multi=True,
                      seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.enforce_window = False
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550101",
                               pool="rep", state="active", area_code="865"))
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, client


def _running_campaign(owner, s, n=3, digit="1"):
    from dialer import campaigns as camp_mod
    for i in range(n):
        make_lead(owner_id=owner.id, name=f"Lead {i}",
                  phone=f"865555{300 + i:03d}{digit}")
    c = Campaign(account_id=owner.id, name="Today", mode="power",
                 status="running", max_concurrent=1,
                 segment_json='{"has_phone": true}')
    db.session.add(c)
    db.session.commit()
    camp_mod.materialize(c, s)
    return c


def test_token_endpoint_returns_a_token(floor):
    owner, s, client = floor
    r = client.get("/dialer/token").get_json()
    assert r["ok"] and r["token"]
    assert r["identity"].startswith(f"t{owner.id}_u")
    assert r["simulating"] is True


def test_next_lead_claims_dials_and_returns_the_card(floor):
    owner, s, client = floor
    c = _running_campaign(owner, s)
    r = client.post("/dialer/next", data={"campaign_id": c.id}).get_json()
    assert r["ok"] is True
    assert r["lead"]["name"] == "Lead 0"
    assert r["lead"]["phone"].startswith("+1865")
    assert "notes" in r["lead"] and "tasks" in r["lead"]
    call = db.session.get(Call, r["call_id"])
    assert call.mode == "power" and call.agent_user_id == owner.id
    row = CampaignLead.query.filter_by(campaign_id=c.id,
                                       lead_id=r["lead_id"]).first()
    assert row.state == "dialing" and row.attempts == 1


def test_next_lead_skips_a_suppressed_number_and_says_why(floor):
    owner, s, client = floor
    c = _running_campaign(owner, s, n=1)
    lead = Lead.query.filter_by(owner_id=owner.id).first()
    from dialer import compliance
    compliance.suppress(owner.id, lead.phone_key, lead=lead, source="manual")
    db.session.commit()
    r = client.post("/dialer/next", data={"campaign_id": c.id}).get_json()
    assert r["ok"] is False
    assert r.get("done") or r.get("skipped")


def test_an_empty_queue_reports_done_rather_than_an_error(floor):
    owner, s, client = floor
    c = Campaign(account_id=owner.id, name="Empty", mode="power",
                 status="running", segment_json="{}")
    db.session.add(c)
    db.session.commit()
    r = client.post("/dialer/next", data={"campaign_id": c.id}).get_json()
    assert r["ok"] is False and r["done"] is True


def test_manual_dial_works_with_no_campaign_at_all(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual",
                    json={"to": "(865) 555-4001"}).get_json()
    assert r["ok"] is True
    call = db.session.get(Call, r["call_id"])
    assert call.mode == "manual" and call.campaign_id is None
    # an unknown number becomes a lead so the call has somewhere to live
    assert Lead.query.filter_by(owner_id=owner.id,
                                phone_key="8655554001").count() == 1


def test_manual_dial_reuses_an_existing_lead(floor):
    owner, s, client = floor
    lead = make_lead(owner_id=owner.id, name="Dana", phone="8655554002")
    r = client.post("/dialer/call/manual", json={"to": "865-555-4002"}).get_json()
    assert r["lead_id"] == lead.id
    assert r["lead"]["name"] == "Dana"


def test_manual_dial_refuses_a_suppressed_number(floor):
    owner, s, client = floor
    lead = make_lead(owner_id=owner.id, name="Dana", phone="8655554003")
    from dialer import compliance
    compliance.suppress(owner.id, lead.phone_key, lead=lead)
    db.session.commit()
    r = client.post("/dialer/call/manual", json={"to": "8655554003"})
    assert r.status_code == 400
    assert "do-not-call" in r.get_json()["error"].lower()


def test_manual_dial_rejects_rubbish(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual", json={"to": "hello"})
    assert r.status_code == 400
    assert "dialable" in r.get_json()["error"]


def test_notes_autosave(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual", json={"to": "8655554004"}).get_json()
    client.post(f"/dialer/call/{r['call_id']}/notes",
                json={"notes": "Asked for a sample pack"})
    assert "sample pack" in db.session.get(Call, r["call_id"]).notes_draft


def test_disposition_writes_the_note_and_moves_the_lead(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual", json={"to": "8655554005"}).get_json()
    out = client.post(f"/dialer/call/{r['call_id']}/disposition",
                      json={"disposition": "meeting_set",
                            "notes": "Booked for Tuesday"}).get_json()
    assert out["ok"] is True
    lead = db.session.get(Lead, r["lead_id"])
    assert lead.status == "Qualified"
    bodies = " ".join(n.body for n in Note.query.filter_by(lead_id=lead.id))
    assert "Booked for Tuesday" in bodies


def test_marking_do_not_call_suppresses_immediately(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual", json={"to": "8655554006"}).get_json()
    client.post(f"/dialer/call/{r['call_id']}/disposition",
                json={"disposition": "dnc"})
    lead = db.session.get(Lead, r["lead_id"])
    assert lead.do_not_call is True
    assert Suppression.query.filter_by(account_id=owner.id,
                                       phone_key=lead.phone_key).count() == 1


def test_voicemail_drop_ends_the_call_and_frees_the_rep(floor):
    owner, s, client = floor
    db.session.add(VoicemailDrop(account_id=owner.id, name="Standard",
                                 is_default=True))
    db.session.commit()
    r = client.post("/dialer/call/manual", json={"to": "8655554007"}).get_json()
    out = client.post(f"/dialer/call/{r['call_id']}/drop-voicemail",
                      json={}).get_json()
    assert out["ok"] is True and out["dropped"] == "Standard"
    call = db.session.get(Call, r["call_id"])
    assert call.voicemail_dropped is True
    assert call.disposition == "voicemail_left"
    assert db.session.get(RepPresence,
                          RepPresence.query.first().id).current_call_id is None


def test_dropping_without_a_recording_says_what_to_do(floor):
    owner, s, client = floor
    r = client.post("/dialer/call/manual", json={"to": "8655554008"}).get_json()
    out = client.post(f"/dialer/call/{r['call_id']}/drop-voicemail", json={})
    assert out.status_code == 400
    assert "Record a voicemail in Setup" in out.get_json()["error"]


def test_presence_toggles_and_releases_claims_on_sign_off(floor):
    owner, s, client = floor
    c = _running_campaign(owner, s, n=2)
    client.post("/dialer/presence", json={"on_shift": True, "available": True})
    client.post("/dialer/next", data={"campaign_id": c.id})
    client.post("/dialer/presence", json={"on_shift": False})
    p = RepPresence.query.first()
    assert p.on_shift is False and p.current_call_id is None


def test_an_agent_can_dial_but_a_viewer_cannot(floor):
    owner, s, client = floor
    make_user(name="Rep", email="rep@n.test", role="agent", account_id=owner.id)
    make_user(name="Watcher", email="v@n.test", role="viewer",
              account_id=owner.id)

    client.get("/logout")
    client.post("/login", data={"email": "rep@n.test", "password": "pw123456"})
    assert client.post("/dialer/call/manual",
                       json={"to": "8655554009"}).status_code == 200

    client.get("/logout")
    client.post("/login", data={"email": "v@n.test", "password": "pw123456"})
    assert client.post("/dialer/call/manual",
                       json={"to": "8655554010"}).status_code == 403


def test_two_reps_pulling_at_once_never_get_the_same_lead(floor):
    owner, s, client = floor
    c = _running_campaign(owner, s, n=4)
    make_user(name="Rep", email="rep@n.test", role="agent", account_id=owner.id)
    first = client.post("/dialer/next", data={"campaign_id": c.id}).get_json()

    from app import app as flask_app
    second_client = flask_app.test_client()
    second_client.post("/login", data={"email": "rep@n.test",
                                       "password": "pw123456"})
    second = second_client.post("/dialer/next",
                                data={"campaign_id": c.id}).get_json()
    assert first["ok"] and second["ok"]
    assert first["lead_id"] != second["lead_id"]
