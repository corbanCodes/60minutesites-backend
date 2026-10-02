"""Tools the AI agent can call mid-conversation.

Each is a small, fast CRM operation. They are authenticated with a per-account
token passed as a header, which ElevenLabs injects from a secret variable --
so the token never appears in the prompt or in a webhook payload.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app import Lead, Note, Task, db

from dialer.models import Call, DialerSettings


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def account_token(account_id):
    """Deterministic per-account token derived from the app secret."""
    import os
    secret = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
    return hmac.new(secret.encode(), f"hq-tool:{account_id}".encode(),
                    hashlib.sha256).hexdigest()[:40]


def _account_from_token(token):
    if not token:
        return None
    for s in DialerSettings.query.all():
        if hmac.compare_digest(account_token(s.account_id), token):
            return s.account_id
    return None


def run_tool(name, body, token):
    account_id = _account_from_token(token)
    if account_id is None:
        return {"ok": False, "error": "unauthorized"}, 403
    fn = {"lookup_lead": _lookup, "log_note": _note, "book_followup": _followup,
          "set_disposition": _disposition}.get(name)
    if fn is None:
        return {"ok": False, "error": "unknown tool"}, 404
    try:
        return fn(account_id, body or {})
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _find_lead(account_id, body):
    if body.get("lead_id"):
        lead = db.session.get(Lead, int(body["lead_id"]))
        if lead and lead.owner_id == account_id:
            return lead
    phone = body.get("phone") or body.get("phone_number") or ""
    if phone:
        from dialer.compliance import normalize
        _, key, ok = normalize(phone)
        if ok:
            return Lead.query.filter_by(owner_id=account_id,
                                        phone_key=key).first()
    conv = body.get("conversation_id")
    if conv:
        call = Call.query.filter_by(elevenlabs_conversation_id=conv).first()
        if call and call.lead_id:
            return db.session.get(Lead, call.lead_id)
    return None


def _lookup(account_id, body):
    lead = _find_lead(account_id, body)
    if lead is None:
        return {"ok": True, "found": False,
                "message": "No record for this number yet."}
    notes = (Note.query.filter_by(lead_id=lead.id)
             .order_by(Note.created_at.desc()).limit(3).all())
    return {"ok": True, "found": True, "name": lead.name,
            "business": lead.business, "business_type": lead.business_type,
            "status": lead.status, "prior_calls": lead.call_count or 0,
            "recent_notes": [n.body[:300] for n in notes]}


def _note(account_id, body):
    lead = _find_lead(account_id, body)
    text = (body.get("note") or body.get("text") or "").strip()
    if lead is None or not text:
        return {"ok": False, "error": "need a lead and some text"}
    db.session.add(Note(lead_id=lead.id, kind="ai_summary",
                        body=f"[AI, during the call] {text[:4000]}"))
    db.session.commit()
    return {"ok": True}


def _followup(account_id, body):
    lead = _find_lead(account_id, body)
    title = (body.get("title") or "Follow up").strip()[:240]
    if lead is None:
        return {"ok": False, "error": "no lead"}
    try:
        days = max(0, min(int(body.get("in_days", 1)), 90))
    except (TypeError, ValueError):
        days = 1
    due = (_now() + timedelta(days=days)).replace(hour=16, minute=0, second=0,
                                                  microsecond=0)
    db.session.add(Task(owner_id=account_id, lead_id=lead.id, title=title,
                        kind="Follow-up", due_at=due))
    db.session.commit()
    return {"ok": True, "due": due.isoformat()}


def _disposition(account_id, body):
    from dialer import calls as calls_mod
    from dialer.settings_store import get_settings
    conv = body.get("conversation_id")
    call = Call.query.filter_by(elevenlabs_conversation_id=conv).first() \
        if conv else None
    if call is None:
        lead = _find_lead(account_id, body)
        if lead is not None:
            call = (Call.query.filter_by(lead_id=lead.id)
                    .order_by(Call.started_at.desc()).first())
    if call is None:
        return {"ok": False, "error": "no call"}
    disp = (body.get("disposition") or "").strip()
    calls_mod.set_disposition(call, disp, settings=get_settings(account_id))
    db.session.commit()
    return {"ok": True, "disposition": call.disposition}


# ElevenLabs validates every property in a tool's request body and rejects
# the whole agent unless each one sets description, dynamic_variable,
# is_system_provided, constant_value or is_omitted. A bare {"type": "string"}
# fails the agent sync with a wall of schema paths, so every field below
# carries a description -- which the model reads anyway, and which is the
# difference between a tool it uses correctly and one it guesses at.
CONVERSATION_ID = {
    "type": "string",
    "description": "The id of this conversation. Always include it; it is "
                   "how we match what you say to the right call and the "
                   "right person.",
}

TOOL_SPECS = [
    {"name": "lookup_lead", "description":
     "Look up what we already know about the person you are speaking to. "
     "Call this at the start if you need their history.",
     "parameters": {"type": "object", "properties": {
         "phone": {"type": "string",
                   "description": "The phone number you dialled, in full "
                                  "international form such as +18655550101."},
         "conversation_id": CONVERSATION_ID}}},
    {"name": "log_note", "description":
     "Write something you learned onto the lead's record.",
     "parameters": {"type": "object", "properties": {
         "note": {"type": "string",
                  "description": "What you learned, in one or two plain "
                                 "sentences. Include any day or time they "
                                 "gave you for a callback, in their words."},
         "conversation_id": CONVERSATION_ID},
         "required": ["note"]}},
    {"name": "book_followup", "description":
     "Schedule a follow-up task when they ask to be called back later.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string",
                   "description": "What the person picking this up should "
                                  "do, such as \"Call Dana back about the "
                                  "napkin programme\"."},
         "in_days": {"type": "integer",
                     "description": "How many days from today, as a whole "
                                    "number. Use 1 for tomorrow."},
         "conversation_id": CONVERSATION_ID}, "required": ["title"]}},
    {"name": "set_disposition", "description":
     "Record the outcome. Use dnc immediately if they ask not to be called "
     "again.",
     "parameters": {"type": "object", "properties": {
         "disposition": {
             "type": "string",
             "description": "How the call ended. Use callback when they "
                            "asked to be reached another time, qualified "
                            "when they are the right person and interested, "
                            "and dnc the moment they ask not to be called.",
             "enum": ["dm_reached", "gatekeeper", "callback", "meeting_set",
                      "qualified", "not_interested", "voicemail_left",
                      "wrong_number", "dnc"]},
         "conversation_id": CONVERSATION_ID}, "required": ["disposition"]}},
]
