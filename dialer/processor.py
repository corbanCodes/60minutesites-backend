"""Turns queued webhook rows into call state.

Runs in the worker, and inline in tests. Kept separate from the HTTP handlers
so a slow LLM call can never hold a carrier connection open.
"""
import json
from datetime import datetime, timedelta, timezone

from app import db

from dialer.models import Call, WebhookInbox

MAX_ATTEMPTS = 5


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pending(account_id=None, limit=50):
    q = (WebhookInbox.query.filter(WebhookInbox.processed_at.is_(None),
                                   WebhookInbox.attempts < MAX_ATTEMPTS)
         .order_by(WebhookInbox.received_at))
    if account_id is not None:
        q = q.filter(WebhookInbox.account_id == account_id)
    return q.limit(limit).all()


def process_all(account_id=None, limit=50):
    done = failed = 0
    for row in pending(account_id, limit):
        row.attempts = (row.attempts or 0) + 1
        try:
            handle(row)
            row.processed_at = _now()
            row.error = ""
            done += 1
        except Exception as e:
            row.error = str(e)[:400]
            failed += 1
        db.session.commit()
    return {"processed": done, "failed": failed}


def handle(row):
    payload = json.loads(row.payload or "{}")
    if row.source == "twilio":
        return _twilio(row, payload)
    if row.source == "elevenlabs":
        return _elevenlabs(row, payload)
    return None


# ------------------------------------------------------------------ twilio
def _find_call(payload, account_id=None):
    sid = payload.get("CallSid") or payload.get("ParentCallSid") or ""
    call = Call.query.filter_by(twilio_sid=sid).first() if sid else None
    if call is None and payload.get("ParentCallSid"):
        call = Call.query.filter_by(
            twilio_sid=payload["ParentCallSid"]).first()
    return call


def _twilio(row, p):
    from dialer import calls as calls_mod
    from dialer.settings_store import get_settings
    call = _find_call(p, row.account_id)
    if call is None:
        return None
    settings = get_settings(call.account_id)

    if row.kind.startswith("status:"):
        status = p.get("CallStatus") or p.get("DialCallStatus") or ""
        calls_mod.apply_status(
            call, status, answered_by=p.get("AnsweredBy"),
            duration=p.get("CallDuration") or p.get("DialCallDuration"),
            price=p.get("Price"))
        if p.get("RecordingSid"):
            call.recording_sid = p["RecordingSid"][:64]
            call.recording_url = (p.get("RecordingUrl") or "")[:500]
        db.session.commit()
        if status in ("completed", "busy", "no-answer", "failed", "canceled"):
            calls_mod.finalize(call, settings)
    elif row.kind == "amd":
        answered_by = p.get("AnsweredBy", "")
        calls_mod.apply_status(call, call.status or "in-progress",
                               answered_by=answered_by)
        db.session.commit()
    elif row.kind == "recording":
        call.recording_sid = (p.get("RecordingSid") or "")[:64]
        call.recording_url = (p.get("RecordingUrl") or "")[:500]
        call.recording_duration_s = int(float(p.get("RecordingDuration") or 0))
        db.session.commit()
        calls_mod.finalize(call, settings, force=not call.transcript)
    return call


# -------------------------------------------------------------- elevenlabs
def _elevenlabs(row, body):
    from dialer import calls as calls_mod
    from dialer.settings_store import get_settings
    data = body.get("data") or body
    conv = data.get("conversation_id") or data.get("conversationId") or ""
    call = Call.query.filter_by(elevenlabs_conversation_id=conv).first() \
        if conv else None
    if call is None:
        # A call WE placed never learned the vendor's conversation id up
        # front; the webhook echoes the dynamic variables we handed over,
        # and our own call id is one of them.
        cid = (((data.get("conversation_initiation_client_data") or {})
                .get("dynamic_variables") or {}).get("hq_call_id"))
        try:
            call = db.session.get(Call, int(cid)) if cid else None
        except (TypeError, ValueError):
            call = None
        if call is not None and conv and not call.elevenlabs_conversation_id:
            call.elevenlabs_conversation_id = conv[:64]
    if call is None:
        return None
    settings = get_settings(call.account_id)

    transcript = data.get("transcript")
    if isinstance(transcript, list):
        call.transcript = "\n".join(
            f"{t.get('role', '')}: {t.get('message', '')}" for t in transcript
            if t.get("message"))
    elif isinstance(transcript, str):
        call.transcript = transcript
    meta = data.get("metadata") or {}
    if meta.get("call_duration_secs"):
        call.duration_s = int(meta["call_duration_secs"])
        call.billable_minutes = max(1, (call.duration_s + 59) // 60)
    if meta.get("cost"):
        try:
            call.vendor_cost = float(meta["cost"]) / 100.0
        except (TypeError, ValueError):
            pass
    call.status = "completed"
    call.ended_at = call.ended_at or _now()
    if call.duration_s:
        call.answered_live = True
        call.system_outcome = call.system_outcome or "answered_human"
    analysis = data.get("analysis") or {}
    collected = analysis.get("data_collection_results") or {}
    if collected:
        flat = {k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in collected.items()}
        call.qualification_json = json.dumps(flat)
    if analysis.get("transcript_summary") and not call.summary:
        call.summary = str(analysis["transcript_summary"])[:4000]
    db.session.commit()
    calls_mod.finalize(call, settings)
    return call


# ------------------------------------------------------------ housekeeping
def reconcile_stale_calls(account_id=None, older_than_minutes=20, limit=50):
    """A webhook can be missed. Anything still open past its natural life gets
    checked against the carrier directly."""
    from dialer import calls as calls_mod
    from dialer.providers import registry
    from dialer.settings_store import get_settings
    cutoff = _now() - timedelta(minutes=older_than_minutes)
    q = Call.query.filter(Call.finalized_at.is_(None),
                          Call.started_at < cutoff,
                          Call.status.notin_(["completed", "failed", "canceled"]))
    if account_id is not None:
        q = q.filter(Call.account_id == account_id)
    fixed = 0
    for call in q.limit(limit):
        settings = get_settings(call.account_id)
        if call.twilio_sid:
            r = registry.telephony(settings).fetch_call(call.twilio_sid)
            if r.get("ok"):
                calls_mod.apply_status(call, r.get("status", "completed"),
                                       answered_by=r.get("answered_by"),
                                       duration=r.get("duration"),
                                       price=r.get("price"))
        else:
            call.status = "failed"
            call.system_outcome = "failed"
            call.error = call.error or "No carrier id — the dial never left."
        db.session.commit()
        calls_mod.finalize(call, settings)
        fixed += 1
    return fixed


def apply_retention(account_id=None, limit=200):
    """Delete vendor recordings past the account's retention window. The call
    row, transcript and evidence stay."""
    from dialer.models import DialerSettings
    from dialer.providers import registry
    deleted = 0
    accounts = ([DialerSettings.query.filter_by(account_id=account_id).first()]
                if account_id is not None else DialerSettings.query.all())
    for s in [a for a in accounts if a]:
        days = s.retention_days or 90
        cutoff = _now() - timedelta(days=days)
        rows = (Call.query.filter(Call.account_id == s.account_id,
                                  Call.recording_sid != "",
                                  Call.recording_deleted_at.is_(None),
                                  Call.started_at < cutoff).limit(limit).all())
        if not rows:
            continue
        tel = registry.telephony(s)
        for call in rows:
            r = tel.delete_recording(call.recording_sid)
            if r.get("ok"):
                call.recording_deleted_at = _now()
                call.recording_url = ""
                deleted += 1
        db.session.commit()
    return deleted
