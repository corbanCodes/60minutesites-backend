"""The gate. Every dial passes through can_dial() and the decision is frozen
onto the Call row as evidence.

Design note, deliberately: the AI line-type gate is ON by default and an
owner/admin can switch it OFF with a typed attestation, which is audit-logged
with their user id and a timestamp. That mirrors how Twilio and the voice-agent
vendors do it -- the platform supplies the control and the evidence trail, the
operator makes the call about their own list. A gate that cannot be configured
just gets worked around outside the product, where nothing is logged.
"""
import json
from datetime import datetime, timedelta, timezone

import phonenumbers

from dialer import tz

# Reasons are stable strings: the UI maps them to copy, tests assert on them.
REASONS = {
    "ok": "Cleared to dial.",
    "no_phone": "No usable phone number on this lead.",
    "bad_phone": "That phone number isn't dialable.",
    "do_not_call": "This lead is marked do-not-call.",
    "suppressed": "This number is on your do-not-call list.",
    "outside_window": "Outside the calling window in the lead's local time.",
    "state_blocked": "AI calling is switched off for this state.",
    "state_window": "Outside this state's calling hours.",
    "line_type_restricted": "AI calling is limited to landlines, and this number "
                            "isn't one. A human can still dial it.",
    "line_type_unknown": "We haven't checked whether this is a mobile number yet.",
    "line_type_stale": "The line-type check on this number is out of date.",
    "no_disclosure": "Set the AI disclosure name and callback number first.",
    "daily_cap": "This lead has already been called the maximum times today.",
    "no_number": "No phone number available to dial from.",
}

HUMAN_MODES = {"manual", "power"}
AI_MODES = {"ai_outbound", "voicemail"}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------- numbers
def normalize(raw, region="US"):
    """Free-text phone -> (e164, phone_key, ok). phone_key is the 10-digit
    national number, which is what we match suppression on."""
    s = (raw or "").strip()
    if not s:
        return "", "", False
    try:
        parsed = phonenumbers.parse(s, region)
        if not phonenumbers.is_valid_number(parsed):
            raise phonenumbers.NumberParseException(0, "invalid")
        e164 = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        d = "".join(c for c in s if c.isdigit())
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        if len(d) != 10:
            return "", "", False
        e164 = "+1" + d
    key = "".join(c for c in e164 if c.isdigit())
    if len(key) == 11 and key.startswith("1"):
        key = key[1:]
    return e164, key, True


def enrich_lead(lead, force=False):
    """Fill phone_e164 / phone_key / timezone / state_code from the free-text
    phone. Cheap, offline, and safe to run on every lead."""
    if lead.phone_e164 and not force:
        return False
    e164, key, ok = normalize(lead.phone)
    if not ok:
        return False
    lead.phone_e164 = e164
    lead.phone_key = key
    if not lead.timezone:
        lead.timezone = tz.zone_for(e164)
    if not lead.state_code:
        lead.state_code = tz.state_for(e164)
    return True


# --------------------------------------------------------------------- gate
def _state_rule(state_code):
    if not state_code:
        return None
    from dialer.models import StateRule
    return StateRule.query.filter_by(state_code=state_code).first()


def _suppressed(account_id, phone_key):
    if not phone_key:
        return False
    from dialer.models import Suppression
    return Suppression.query.filter_by(
        account_id=account_id, phone_key=phone_key).first() is not None


def has_consent(lead):
    return (lead.consent_status or "none") in ("express", "written", "inbound",
                                               "existing_relationship")


def line_type_ok_for_ai(lead, settings):
    """-> (allowed, why). `why` records WHICH rule allowed or refused it, so
    the evidence on the call says more than 'ok'."""
    if has_consent(lead):
        return True, "consent"
    if not settings.gate_on:
        return True, "gate_off"
    lt = (lead.line_type or "").strip()
    if not lt:
        return False, "line_type_unknown"
    if lt in ("landline", "tollFree"):
        return True, "landline"
    if lt == "fixedVoip" and not settings.treat_voip_as_mobile:
        return True, "fixed_voip_allowed"
    return False, "line_type_restricted"


def can_dial(lead, mode, settings, account_id, now=None, campaign=None):
    """-> dict evidence. {'ok': bool, 'reason': str, ...}

    Called inside the queue-claim transaction AND again immediately before the
    vendor call, so a suppression that lands mid-campaign still stops the dial.
    """
    now = now or _now()
    ev = {"mode": mode, "at": now.isoformat(), "lead_id": getattr(lead, "id", None)}

    # 1. a dialable number
    if not lead.phone_e164:
        enrich_lead(lead)
    if not lead.phone_e164:
        return dict(ev, ok=False, reason="no_phone")
    ev["to"] = lead.phone_e164

    # 2. suppression -- applies to every mode, including a human dialing
    if lead.do_not_call:
        return dict(ev, ok=False, reason="do_not_call")
    if _suppressed(account_id, lead.phone_key):
        return dict(ev, ok=False, reason="suppressed")

    # 3. calling window, in the LEAD's local time
    zone = lead.timezone or tz.zone_for(lead.phone_e164)
    ev["tz"] = zone
    start, end = settings.window_start, settings.window_end
    if settings.smart_window:
        start, end = tz.smart_window(getattr(lead, "business_type", ""))
    rule = _state_rule(lead.state_code) if settings.honor_state_rules else None
    if rule:
        ev["state"] = rule.state_code
        if rule.window_start:
            start = max(start, rule.window_start)
        if rule.window_end:
            end = min(end, rule.window_end)
        if rule.no_sunday and tz.local_now(zone).isoweekday() == 7:
            return dict(ev, ok=False, reason="state_window", state=rule.state_code)
    ev["window"] = f"{start}-{end}"
    if settings.enforce_window:
        inside, local = tz.in_window(zone, start, end, settings.window_weekdays)
        ev["local_time"] = local.strftime("%Y-%m-%d %H:%M %Z")
        if not inside:
            return dict(ev, ok=False, reason="outside_window")

    # 4. per-state daily frequency cap
    if rule and rule.max_calls_per_day:
        from app import db
        from dialer.models import Call
        since = now - timedelta(hours=24)
        n = db.session.query(Call.id).filter(
            Call.lead_id == lead.id, Call.started_at >= since).count()
        if n >= rule.max_calls_per_day:
            return dict(ev, ok=False, reason="daily_cap", cap=rule.max_calls_per_day)

    # 5. human modes stop here -- a live human voice is not an artificial voice
    if mode in HUMAN_MODES:
        return dict(ev, ok=True, reason="ok", line_type=lead.line_type or "unchecked")

    # 6. AI modes: disclosure must be configured
    if settings.disclose_ai and not (settings.ai_disclosure_name
                                     or settings.ai_disclosure_text):
        return dict(ev, ok=False, reason="no_disclosure")

    # 7. AI modes: state overlay
    if rule and rule.ai_outbound in ("block", "counsel"):
        return dict(ev, ok=False, reason="state_blocked", state=rule.state_code,
                    posture=rule.ai_outbound)

    # 8. AI modes: the line-type gate
    allowed, why = line_type_ok_for_ai(lead, settings)
    ev["line_type"] = lead.line_type or "unchecked"
    ev["consent"] = lead.consent_status or "none"
    ev["unlocked_by"] = why if allowed else ""
    if why == "gate_off":
        ev["gate_override"] = True
        ev["attestation"] = (settings.gate_attestation or "")[:300]
    if why == "consent":
        # A restricted line type dialled on the strength of a consent record:
        # name the record, because this is the pair an auditor asks for.
        from dialer.models import ConsentRecord
        rec = (ConsentRecord.query
               .filter_by(account_id=account_id, lead_id=lead.id)
               .filter(ConsentRecord.revoked_at.is_(None))
               .order_by(ConsentRecord.captured_at.desc()).first())
        ev["consent_kind"] = lead.consent_status
        ev["consent_source"] = (lead.consent_source or "")[:200]
        if rec is not None:
            ev["consent_record_id"] = rec.id
            ev["consent_captured_at"] = (rec.captured_at.isoformat()
                                         if rec.captured_at else "")
    if not allowed:
        return dict(ev, ok=False, reason=why)
    if (settings.gate_on and not has_consent(lead)
            and lead.line_type_checked_at and settings.line_type_max_age_days):
        age = (now - lead.line_type_checked_at).days
        ev["line_type_age_days"] = age
        if age > settings.line_type_max_age_days:
            return dict(ev, ok=False, reason="line_type_stale")

    return dict(ev, ok=True, reason="ok")


def explain(evidence):
    return REASONS.get((evidence or {}).get("reason", ""), "Not cleared to dial.")


# -------------------------------------------------------------- suppression
def suppress(account_id, phone_key, reason="", source="manual", lead=None,
             call_id=None, user_id=None):
    """Immediate and idempotent. The law allows ten business days; doing it now
    is simpler and is what an auditor wants to see."""
    from app import db
    from dialer.models import Suppression
    if not phone_key:
        return None
    row = Suppression.query.filter_by(account_id=account_id,
                                      phone_key=phone_key).first()
    if row is None:
        row = Suppression(account_id=account_id, phone_key=phone_key,
                          reason=reason[:200], source=source,
                          lead_id=getattr(lead, "id", None), call_id=call_id,
                          created_by=user_id)
        db.session.add(row)
    if lead is not None:
        lead.do_not_call = True
        lead.opt_out_at = _now()
        lead.opt_out_source = source
    # pull the number out of every queue on this account, now
    from dialer.models import Campaign, CampaignLead
    if lead is not None:
        ids = [c.id for c in Campaign.query.filter_by(account_id=account_id)]
        if ids:
            (CampaignLead.query
             .filter(CampaignLead.campaign_id.in_(ids),
                     CampaignLead.lead_id == lead.id,
                     CampaignLead.state.in_(["queued", "deferred", "claimed"]))
             .update({"state": "skipped", "skip_reason": "do-not-call"},
                     synchronize_session=False))
    return row


def record_consent(account_id, lead, kind="express", source="", text="",
                   user_id=None, evidence_url=""):
    from app import db
    from dialer.models import ConsentRecord
    rec = ConsentRecord(account_id=account_id, lead_id=lead.id,
                        phone_key=lead.phone_key, kind=kind, source=source[:120],
                        text=text, evidence_url=evidence_url[:400],
                        created_by=user_id)
    db.session.add(rec)
    lead.consent_status = kind
    lead.consent_source = source[:120]
    lead.consent_at = _now()
    return rec


# ------------------------------------------------------------- state seeding
# Starting posture. Editable in Setup so a lawyer can change it without a deploy.
SEED_STATES = [
    # code, name, ai_outbound, win_start, win_end, max/day, identify_s, all_party, no_sunday, note
    ("CA", "California", "counsel", "", "", None, None, True, False,
     "AB 2905 requires an announcement that the voice is AI before a prerecorded "
     "message; Penal Code 632.7 makes recording any call touching a cell all-party. "
     "Have counsel clear autonomous AI openers here."),
    ("OK", "Oklahoma", "counsel", "08:00", "20:00", 3, None, False, False,
     "Mini-TCPA with no consumer-goods limit, so it can reach B2B calls."),
    ("MD", "Maryland", "allow", "08:00", "20:00", 3, None, True, False,
     "Stop the Spam Calls Act hours and frequency cap; all-party recording."),
    ("NJ", "New Jersey", "allow", "", "", None, 30, False, False,
     "Caller must self-identify within 30 seconds."),
    ("FL", "Florida", "allow", "08:00", "20:00", 3, None, True, False,
     "FTSA; all-party recording."),
    ("WA", "Washington", "allow", "", "", None, None, True, False, "All-party recording."),
    ("PA", "Pennsylvania", "allow", "", "", None, None, True, False, "All-party recording."),
    ("IL", "Illinois", "allow", "", "", None, None, True, False, "All-party recording."),
    ("MI", "Michigan", "allow", "", "", None, None, True, False, "All-party recording."),
    ("MT", "Montana", "allow", "", "", None, None, True, False, "All-party recording."),
    ("NH", "New Hampshire", "allow", "", "", None, None, True, False, "All-party recording."),
    ("NV", "Nevada", "allow", "", "", None, None, True, False, "All-party recording."),
    ("CT", "Connecticut", "allow", "", "", None, None, True, False, "All-party recording."),
    ("MA", "Massachusetts", "allow", "", "", None, None, True, False, "All-party recording."),
    ("MS", "Mississippi", "allow", "", "", None, None, False, True,
     "No solicitation calls on Sunday."),
]


def seed_state_rules():
    """Idempotent: inserts missing rows, never overwrites an edited one."""
    from app import db
    from dialer.models import StateRule
    added = 0
    for (code, name, ai, ws, we, cap, ident, allp, nosun, note) in SEED_STATES:
        if StateRule.query.filter_by(state_code=code).first():
            continue
        db.session.add(StateRule(
            state_code=code, name=name, ai_outbound=ai, window_start=ws,
            window_end=we, max_calls_per_day=cap, identify_within_seconds=ident,
            all_party_recording=allp, no_sunday=nosun, notes=note))
        added += 1
    if added:
        db.session.commit()
    return added


def all_party_state(state_code):
    rule = _state_rule(state_code)
    return bool(rule and rule.all_party_recording)
