"""The gate. These tests are the reason the feature can ship."""
import pytest
from datetime import datetime, timedelta, timezone

from app import db
from dialer import compliance
from dialer.models import ConsentRecord, StateRule, Suppression
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def acct(ctx):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18655550100"
    s.enforce_window = False          # window is tested on its own
    db.session.commit()
    return owner, s


def _lead(owner, phone, **kw):
    lead = make_lead(owner_id=owner.id, phone=phone, **kw)
    return lead


# ------------------------------------------------------------- line types
@pytest.mark.parametrize("last,expected_line_type,ai_allowed", [
    ("1", "landline", True),
    ("6", "mobile", False),
    ("7", "nonFixedVoip", False),
    ("8", "fixedVoip", False),
])
def test_ai_is_limited_to_landlines(acct, last, expected_line_type, ai_allowed):
    owner, s = acct
    lead = _lead(owner, f"865555123{last}")
    from dialer.providers import registry
    r = registry.telephony(s).lookup(lead.phone_e164)
    lead.line_type = r["line_type"]
    lead.line_type_checked_at = _now()
    db.session.commit()
    assert lead.line_type == expected_line_type

    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is ai_allowed, ev
    if not ai_allowed:
        assert ev["reason"] == "line_type_restricted"
    # a human may always dial it
    assert compliance.can_dial(lead, "power", s, owner.id)["ok"] is True


def test_unknown_line_type_blocks_ai_but_not_a_human(acct):
    owner, s = acct
    lead = _lead(owner, "8655551231")
    assert not lead.line_type
    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "line_type_unknown"
    assert compliance.can_dial(lead, "manual", s, owner.id)["ok"]


def test_stale_line_type_check_blocks_ai(acct):
    owner, s = acct
    lead = _lead(owner, "8655551231")
    lead.line_type = "landline"
    lead.line_type_checked_at = _now() - timedelta(days=90)
    db.session.commit()
    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "line_type_stale"


def test_consent_unlocks_a_mobile_for_ai(acct):
    owner, s = acct
    lead = _lead(owner, "8655551236")
    lead.line_type = "mobile"
    lead.line_type_checked_at = _now()
    db.session.commit()
    assert compliance.can_dial(lead, "ai_outbound", s, owner.id)["ok"] is False

    compliance.record_consent(owner.id, lead, kind="written",
                              source="signed form", text="Opted in on the web")
    db.session.commit()
    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is True
    assert ConsentRecord.query.count() == 1


def test_owner_can_switch_the_gate_off_and_it_is_recorded(acct):
    """The override exists on purpose: the operator owns the list and the
    decision, and the evidence says so."""
    owner, s = acct
    lead = _lead(owner, "8655551236")
    lead.line_type = "mobile"
    lead.line_type_checked_at = _now()
    db.session.commit()
    assert compliance.can_dial(lead, "ai_outbound", s, owner.id)["ok"] is False

    s.gate_ai_line_type = False
    s.gate_attestation = "We have written consent for every number on this list."
    s.gate_ai_line_type_off_at = _now()
    s.gate_ai_line_type_off_by = owner.id
    db.session.commit()

    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is True
    assert ev["gate_override"] is True
    assert "written consent" in ev["attestation"]


# ----------------------------------------------------------- suppression
def test_suppression_blocks_every_mode_including_a_human(acct):
    owner, s = acct
    lead = _lead(owner, "8655551231")
    lead.line_type = "landline"
    lead.line_type_checked_at = _now()
    db.session.commit()
    assert compliance.can_dial(lead, "power", s, owner.id)["ok"]

    compliance.suppress(owner.id, lead.phone_key, reason="asked to stop",
                        source="rep", lead=lead)
    db.session.commit()
    for mode in ("manual", "power", "ai_outbound", "voicemail"):
        ev = compliance.can_dial(lead, mode, s, owner.id)
        assert ev["ok"] is False
        assert ev["reason"] in ("suppressed", "do_not_call")


def test_suppression_is_idempotent_and_scoped_to_one_account(acct):
    owner, s = acct
    other = make_user(name="Other", email="x@n.test", dialer=True)
    lead = _lead(owner, "8655551231")
    compliance.suppress(owner.id, lead.phone_key, lead=lead)
    compliance.suppress(owner.id, lead.phone_key, lead=lead)
    db.session.commit()
    assert Suppression.query.filter_by(account_id=owner.id).count() == 1
    assert Suppression.query.filter_by(account_id=other.id).count() == 0


def test_suppression_pulls_the_lead_out_of_running_queues(acct):
    owner, s = acct
    from dialer.models import Campaign, CampaignLead
    lead = _lead(owner, "8655551231")
    camp = Campaign(account_id=owner.id, name="C", mode="power", status="running")
    db.session.add(camp)
    db.session.flush()
    db.session.add(CampaignLead(campaign_id=camp.id, lead_id=lead.id,
                                account_id=owner.id, state="queued"))
    db.session.commit()

    compliance.suppress(owner.id, lead.phone_key, lead=lead, source="rep")
    db.session.commit()
    row = CampaignLead.query.filter_by(campaign_id=camp.id).first()
    assert row.state == "skipped" and row.skip_reason == "do-not-call"


# --------------------------------------------------------------- windows
def test_calling_window_uses_the_leads_timezone(acct):
    owner, s = acct
    s.enforce_window = True
    s.window_start, s.window_end = "09:00", "17:00"
    db.session.commit()
    lead = _lead(owner, "8655551231")
    lead.line_type, lead.line_type_checked_at = "landline", _now()
    lead.timezone = "America/New_York"
    db.session.commit()

    ev = compliance.can_dial(lead, "power", s, owner.id)
    assert "tz" in ev and ev["tz"] == "America/New_York"
    assert "local_time" in ev or ev["ok"]


def test_a_closed_window_blocks_and_names_the_reason(acct):
    owner, s = acct
    s.enforce_window = True
    s.window_start, s.window_end = "03:00", "03:01"   # essentially never
    db.session.commit()
    lead = _lead(owner, "8655551231")
    ev = compliance.can_dial(lead, "power", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "outside_window"
    assert "Outside the calling window" in compliance.explain(ev)


# ---------------------------------------------------------- state rules
def test_california_blocks_autonomous_ai_by_default(acct):
    owner, s = acct
    lead = _lead(owner, "3105551231")        # a CA area code
    lead.line_type, lead.line_type_checked_at = "landline", _now()
    db.session.commit()
    assert lead.state_code == "CA"
    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "state_blocked"
    # the same lead is fine for a human
    assert compliance.can_dial(lead, "power", s, owner.id)["ok"]


def test_a_lawyer_can_unblock_a_state_without_a_deploy(acct):
    owner, s = acct
    lead = _lead(owner, "3105551231")
    lead.line_type, lead.line_type_checked_at = "landline", _now()
    db.session.commit()
    rule = StateRule.query.filter_by(state_code="CA").first()
    rule.ai_outbound = "allow"
    db.session.commit()
    assert compliance.can_dial(lead, "ai_outbound", s, owner.id)["ok"] is True


def test_missing_disclosure_blocks_ai(acct):
    owner, s = acct
    s.ai_disclosure_name = ""
    s.ai_disclosure_text = ""
    db.session.commit()
    lead = _lead(owner, "8655551231")
    lead.line_type, lead.line_type_checked_at = "landline", _now()
    db.session.commit()
    ev = compliance.can_dial(lead, "ai_outbound", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "no_disclosure"


# ------------------------------------------------------------- evidence
def test_the_decision_is_recorded_on_the_call(acct):
    owner, s = acct
    from dialer import calls as calls_mod
    lead = _lead(owner, "8655551231")
    lead.line_type, lead.line_type_checked_at = "landline", _now()
    db.session.commit()
    call = calls_mod.start_call(owner.id, lead, "ai_outbound", s, owner.id)
    db.session.commit()
    assert call.gate["ok"] is True
    assert call.line_type_at_dial == "landline"
    assert "NapkinAds" in call.disclosure_text
    assert call.gate["tz"]


def test_no_phone_is_refused_before_anything_else(acct):
    owner, s = acct
    lead = make_lead(owner_id=owner.id, phone="not a number")
    ev = compliance.can_dial(lead, "power", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "no_phone"


# ----------------------------------- the evidence has to name its own reason
def test_evidence_says_which_rule_allowed_the_dial(acct):
    owner, s = acct
    landline = _lead(owner, "8655551231")
    landline.line_type, landline.line_type_checked_at = "landline", _now()
    db.session.commit()
    ev = compliance.can_dial(landline, "ai_outbound", s, owner.id)
    assert ev["ok"] and ev["unlocked_by"] == "landline"

    mobile = _lead(owner, "8655551246", name="Cell")
    mobile.line_type, mobile.line_type_checked_at = "mobile", _now()
    db.session.commit()
    compliance.record_consent(owner.id, mobile, kind="written",
                              source="Trade-show card, signed")
    db.session.commit()
    ev2 = compliance.can_dial(mobile, "ai_outbound", s, owner.id)
    assert ev2["ok"] and ev2["unlocked_by"] == "consent"
    assert ev2["consent_kind"] == "written"
    assert "Trade-show" in ev2["consent_source"]
    assert ev2.get("consent_record_id")


def test_a_mobile_with_no_consent_is_still_refused(acct):
    owner, s = acct
    mobile = _lead(owner, "8655551246")
    mobile.line_type, mobile.line_type_checked_at = "mobile", _now()
    db.session.commit()
    ev = compliance.can_dial(mobile, "ai_outbound", s, owner.id)
    assert ev["ok"] is False and ev["reason"] == "line_type_restricted"
    assert ev["unlocked_by"] == ""
