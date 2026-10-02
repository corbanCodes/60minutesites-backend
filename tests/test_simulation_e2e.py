"""A whole campaign, start to finish, with no API keys.

This is the test that proves the pipeline: queue -> gate -> dial -> carrier
events -> transcript -> AI summary -> disposition -> lead stage -> note ->
follow-up task -> campaign stats.
"""
from datetime import datetime, timezone

import pytest

from app import Lead, Note, Task, db
from dialer import campaigns, compliance, simulate
from dialer.models import (Call, Campaign, CampaignLead, PhoneNumber,
                           Suppression)
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def ready_account(ctx):
    owner = make_user(name="Napkin Co", email="o@napkin.test", dialer=True)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18655550100"
    s.enforce_window = False
    s.recording_enabled = True
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550101",
                               twilio_sid="PNtest", pool="rep", state="active",
                               area_code="865"))
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550102",
                               twilio_sid="PNtest2", pool="ai", state="active",
                               area_code="865", elevenlabs_phone_id="pn_1"))
    db.session.commit()
    return owner, s


def _seed_leads(owner, s, specs):
    """specs: list of (last_digit, name). Last digit drives the outcome."""
    out = []
    for i, (digit, name) in enumerate(specs):
        lead = make_lead(owner_id=owner.id, name=name,
                         phone=f"865555{200 + i:03d}{digit}",
                         business=f"{name}'s Bar")
        from dialer.providers import registry
        r = registry.telephony(s).lookup(lead.phone_e164)
        lead.line_type = r["line_type"]
        lead.line_type_checked_at = _now()
        out.append(lead)
    db.session.commit()
    return out


def _campaign(owner, mode="power", **kw):
    c = Campaign(account_id=owner.id, name=f"{mode} test", mode=mode,
                 status="running", max_concurrent=2, started_at=_now(),
                 number_pool="rep" if mode != "ai" else "ai",
                 segment_json='{"has_phone": true}', **kw)
    db.session.add(c)
    db.session.commit()
    return c


# ------------------------------------------------------------ power dialer
def test_power_campaign_runs_to_completion(ready_account):
    owner, s = ready_account
    _seed_leads(owner, s, [("1", "Dana"), ("1", "Ray"), ("3", "Mel"),
                           ("4", "Sam"), ("2", "Kim")])
    camp = _campaign(owner, "power")
    res = campaigns.materialize(camp, s)
    assert res["added"] == 5

    out = simulate.run_campaign(camp, s)
    assert out["dialed"] == 5

    calls = Call.query.filter_by(campaign_id=camp.id).all()
    assert len(calls) == 5
    assert all(c.finalized_at for c in calls), "every call must finalize"

    outcomes = sorted(c.system_outcome for c in calls)
    assert outcomes == ["answered_human", "answered_human", "answered_machine",
                        "busy", "no_answer"]

    # whole-minute-per-leg billing, the way Twilio actually charges
    answered = [c for c in calls if c.system_outcome == "answered_human"]
    assert all(c.billable_minutes >= 1 for c in answered)
    assert all((c.cost_estimate or 0) > 0 for c in answered)


def test_a_connected_call_writes_everything_onto_the_lead(ready_account):
    owner, s = ready_account
    lead = _seed_leads(owner, s, [("1", "Dana")])[0]
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)

    call = Call.query.filter_by(lead_id=lead.id).first()
    assert call.transcript, "no transcript"
    assert call.summary, "no summary"
    assert call.score and 1 <= call.score <= 10
    assert call.qualification, "no qualification answers captured"

    db.session.refresh(lead)
    assert lead.call_count == 1
    assert lead.last_called_at is not None
    assert lead.last_outcome == call.disposition

    notes = Note.query.filter_by(lead_id=lead.id).all()
    kinds = {n.kind for n in notes}
    assert "call" in kinds, "no call note written"
    assert any(f"[call:{call.id}]" in n.body for n in notes)

    tasks = Task.query.filter_by(lead_id=lead.id).all()
    assert tasks, "no follow-up task created"
    assert tasks[0].due_at is not None


def test_disposition_moves_the_lead_stage(ready_account):
    owner, s = ready_account
    lead = _seed_leads(owner, s, [("1", "Dana")])[0]
    assert lead.status == "New"
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)
    db.session.refresh(lead)
    assert lead.status == "Qualified"   # the fake transcript qualifies


def test_a_won_client_is_never_demoted_by_a_bad_call(ready_account):
    owner, s = ready_account
    lead = _seed_leads(owner, s, [("1", "Dana")])[0]
    lead.status = "Client"
    db.session.commit()
    from dialer import calls as calls_mod
    call = calls_mod.start_call(owner.id, lead, "power", s, owner.id)
    db.session.commit()
    calls_mod.set_disposition(call, "not_interested", settings=s)
    db.session.commit()
    db.session.refresh(lead)
    assert lead.status == "Client"


# --------------------------------------------------------------- AI lane
def test_ai_campaign_only_dials_the_landlines(ready_account):
    owner, s = ready_account
    from dialer.models import AiAgent
    agent = AiAgent(account_id=owner.id, name="Screener", direction="outbound",
                    elevenlabs_agent_id="ag_test", voice_id="sim-rachel")
    db.session.add(agent)
    db.session.commit()

    # three landlines (…1) and two mobiles (…6)
    _seed_leads(owner, s, [("1", "Dana"), ("6", "Cell One"), ("1", "Ray"),
                           ("6", "Cell Two"), ("1", "Mel")])
    camp = _campaign(owner, "ai", ai_agent_id=agent.id)
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)

    dialed = Call.query.filter_by(campaign_id=camp.id).all()
    assert len(dialed) == 3, "a mobile number was dialed by the AI"
    assert all(c.line_type_at_dial == "landline" for c in dialed)

    skipped = CampaignLead.query.filter_by(campaign_id=camp.id,
                                           state="skipped").all()
    assert len(skipped) == 2
    assert all(r.skip_reason == "line_type_restricted" for r in skipped)


def test_ai_calls_carry_the_disclosure_and_produce_a_transcript(ready_account):
    owner, s = ready_account
    from dialer.models import AiAgent
    agent = AiAgent(account_id=owner.id, name="Screener", direction="outbound",
                    elevenlabs_agent_id="ag_test", voice_id="sim-rachel")
    db.session.add(agent)
    db.session.commit()
    _seed_leads(owner, s, [("1", "Dana")])
    camp = _campaign(owner, "ai", ai_agent_id=agent.id)
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)

    call = Call.query.filter_by(campaign_id=camp.id).first()
    assert "NapkinAds" in call.disclosure_text
    assert "automated AI assistant" in call.disclosure_text
    assert call.elevenlabs_conversation_id
    assert "automated AI assistant" in call.transcript
    assert call.finalized_at


def test_gate_override_lets_the_ai_call_mobiles(ready_account):
    """The owner takes responsibility; the system records that they did."""
    owner, s = ready_account
    from dialer.models import AiAgent
    agent = AiAgent(account_id=owner.id, name="Screener", direction="outbound",
                    elevenlabs_agent_id="ag_test", voice_id="sim-rachel")
    db.session.add(agent)
    s.gate_ai_line_type = False
    s.gate_attestation = "Consent on file for this list."
    db.session.commit()

    _seed_leads(owner, s, [("6", "Cell One"), ("6", "Cell Two")])
    camp = _campaign(owner, "ai", ai_agent_id=agent.id)
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)

    calls = Call.query.filter_by(campaign_id=camp.id).all()
    assert len(calls) == 2
    assert all(c.gate.get("gate_override") for c in calls)
    assert all("Consent on file" in c.gate.get("attestation", "") for c in calls)


# ------------------------------------------------------------- behaviour
def test_an_opt_out_heard_on_a_call_suppresses_immediately(ready_account):
    owner, s = ready_account
    from dialer import calls as calls_mod
    lead = _seed_leads(owner, s, [("1", "Dana")])[0]
    call = calls_mod.start_call(owner.id, lead, "power", s, owner.id)
    call.transcript = "prospect: please take me off your list, do not call again"
    call.status = "completed"
    call.duration_s = 20
    db.session.commit()
    calls_mod.finalize(call, s)

    db.session.refresh(lead)
    assert call.revocation_detected is True
    assert call.disposition == "dnc"
    assert lead.do_not_call is True
    assert Suppression.query.filter_by(account_id=owner.id,
                                       phone_key=lead.phone_key).count() == 1


def test_finalize_is_idempotent(ready_account):
    owner, s = ready_account
    lead = _seed_leads(owner, s, [("1", "Dana")])[0]
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)
    call = Call.query.filter_by(lead_id=lead.id).first()
    notes_before = Note.query.filter_by(lead_id=lead.id).count()
    count_before = lead.call_count

    from dialer import calls as calls_mod
    calls_mod.finalize(call, s)
    calls_mod.finalize(call, s)
    db.session.refresh(lead)
    assert Note.query.filter_by(lead_id=lead.id).count() == notes_before
    assert lead.call_count == count_before


def test_two_workers_never_claim_the_same_lead(ready_account):
    owner, s = ready_account
    _seed_leads(owner, s, [("1", f"L{i}") for i in range(6)])
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    a = campaigns.claim(camp, n=3, worker="w1")
    b = campaigns.claim(camp, n=3, worker="w2")
    assert len({x.id for x in a} & {x.id for x in b}) == 0
    assert len(a) + len(b) == 6


def test_an_abandoned_claim_returns_to_the_queue(ready_account):
    owner, s = ready_account
    _seed_leads(owner, s, [("1", "Dana")])
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    [cl] = campaigns.claim(camp, n=1, worker="rep-who-closed-the-tab")
    from datetime import timedelta
    cl.lease_until = _now() - timedelta(minutes=1)
    db.session.commit()
    assert campaigns.sweep_expired_leases(owner.id) == 1
    assert db.session.get(CampaignLead, cl.id).state == "queued"


def test_numbers_rotate_and_respect_their_daily_cap(ready_account):
    owner, s = ready_account
    n = PhoneNumber.query.filter_by(account_id=owner.id, pool="rep").first()
    n.daily_cap = 2
    db.session.commit()
    _seed_leads(owner, s, [("1", f"L{i}") for i in range(4)])
    camp = _campaign(owner, "power")
    camp.max_concurrent = 1
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)
    assert Call.query.filter_by(campaign_id=camp.id).count() <= 2


def test_campaign_stats_and_auto_finish(ready_account):
    owner, s = ready_account
    _seed_leads(owner, s, [("1", "Dana"), ("4", "Sam")])
    camp = _campaign(owner, "power")
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)
    db.session.refresh(camp)
    assert camp.stats["dials"] == 2
    assert camp.stats["connects"] == 1
    assert camp.status == "done"
    assert camp.finished_at is not None


def test_the_ai_never_dials_a_restricted_line_without_a_reason(ready_account):
    """The invariant that matters: across a whole campaign, every AI call to
    anything other than a landline must carry either a consent record or a
    recorded owner override."""
    owner, s = ready_account
    from dialer.models import AiAgent
    agent = AiAgent(account_id=owner.id, name="Screener", direction="outbound",
                    elevenlabs_agent_id="ag_test", voice_id="sim-rachel")
    db.session.add(agent)
    db.session.commit()

    leads = _seed_leads(owner, s, [("1", "Land A"), ("6", "Cell A"),
                                   ("7", "Voip A"), ("1", "Land B"),
                                   ("6", "Cell B")])
    # one of the mobiles has written consent, which is the lawful case
    compliance.record_consent(owner.id, leads[1], kind="written",
                              source="Signed opt-in form")
    db.session.commit()

    camp = _campaign(owner, "ai", ai_agent_id=agent.id)
    campaigns.materialize(camp, s)
    simulate.run_campaign(camp, s)

    for call in Call.query.filter_by(campaign_id=camp.id).all():
        if call.line_type_at_dial in ("landline", "tollFree"):
            continue
        gate = call.gate
        assert gate.get("unlocked_by") in ("consent", "gate_off"), (
            f"{call.to_number} ({call.line_type_at_dial}) was dialled with "
            f"no consent and no override: {gate}")
    # two landlines plus the one consented mobile
    assert Call.query.filter_by(campaign_id=camp.id).count() == 3
