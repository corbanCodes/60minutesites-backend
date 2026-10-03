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
          "set_disposition": _disposition,
          "schedule_callback": _schedule}.get(name)
    if fn is None:
        return {"ok": False, "error": "unknown tool"}, 404
    try:
        return fn(account_id, body or {})
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _call_from(account_id, body):
    """The call a tool call belongs to: by our own id first, then the
    vendor's conversation id. When both are present and the call did not
    yet know its conversation id, remember it -- the post-call webhook
    needs it."""
    call = None
    raw = body.get("hq_call_id")
    try:
        cid = int(str(raw).strip()) if raw not in (None, "") else None
    except (TypeError, ValueError):
        cid = None
    if cid:
        call = db.session.get(Call, cid)
        if call is not None and call.account_id != account_id:
            call = None
    conv = (body.get("conversation_id") or "").strip()
    if call is None and conv:
        call = Call.query.filter_by(elevenlabs_conversation_id=conv).first()
    if call is not None and conv and not call.elevenlabs_conversation_id:
        call.elevenlabs_conversation_id = conv[:64]
        db.session.commit()
    return call


def _find_lead(account_id, body):
    call = _call_from(account_id, body)
    if call is not None and call.lead_id:
        return db.session.get(Lead, call.lead_id)
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


PRIORITY = {"manager": -30, "specific": -20, "soon": -20, "window": -10,
            "day": -5, "vague": 0}


def _schedule(account_id, body):
    """"Call back around 4" becomes the next call, not a line in a note.

    The guide's one hard requirement: a time a venue gives us must create
    the next outbound call, in the venue's own time zone. The campaign row
    is parked until that minute and outranks a plain redial; the lead
    keeps the manager's name and the words they used; a task shows it on
    the CRM. A test call with no campaign gets the task and the lead
    fields, which is what the next test call reads.
    """
    from dialer import tz, when
    from dialer.models import CampaignLead
    call = _call_from(account_id, body)
    lead = _find_lead(account_id, body)
    if lead is None:
        return {"ok": False, "error": "no lead"}
    said = (body.get("when") or "").strip()[:200]
    name = (body.get("manager_name") or "").strip()[:120]
    by = "manager" if (body.get("asked_by") or "").strip() == "manager" else "staff"
    zone = (lead.timezone or "").strip() or tz.zone_for(lead.phone_e164 or lead.phone)
    at, kind, pretty = when.resolve(said, zone)
    if name:
        lead.decision_maker = name
    lead.callback_said = said
    if at is None:
        db.session.add(Note(lead_id=lead.id, kind="ai_summary",
                            body=f"[AI, during the call] No clear time for a "
                                 f"callback; they said \"{said}\""
                                 + (f"; decision maker: {name}" if name else "")))
        db.session.commit()
        return {"ok": True, "scheduled": False,
                "message": "No clear time in that. If you have not already, "
                           "ask once for a time of day; otherwise say we will "
                           "try again another time, and end the call."}
    lead.callback_at = at
    if call is not None:
        call.callback_at = at
    who = name or lead.decision_maker or "the manager"
    where = lead.business or lead.name or ""
    db.session.add(Task(owner_id=account_id, lead_id=lead.id, kind="Call",
                        due_at=at,
                        title=(f"Call {who} back" + (f" at {where}" if where else "")
                               + f" \u2014 they said: {said}")[:240]))
    db.session.add(Note(lead_id=lead.id, kind="ai_summary",
                        body=f"[AI, during the call] Callback booked for {pretty}: "
                             f"they said \"{said}\""
                             + (f"; decision maker: {name}" if name else "")
                             + (" (asked for by the manager)" if by == "manager" else "")))
    if call is not None and call.campaign_lead_id:
        cl = db.session.get(CampaignLead, call.campaign_lead_id)
        if cl is not None:
            cl.state = "deferred"
            cl.next_attempt_at = at
            cl.position = PRIORITY["manager" if by == "manager" else kind]
            cl.skip_reason = f"callback: {said}"[:120]
    db.session.commit()
    return {"ok": True, "scheduled": True, "for": pretty, "kind": kind,
            "message": f"Booked for {pretty}. Say the time back once, thank "
                       f"them, set the disposition, and end the call."}


def _disposition(account_id, body):
    from dialer import calls as calls_mod
    from dialer.settings_store import get_settings
    call = _call_from(account_id, body)
    if call is None:
        lead = _find_lead(account_id, body)
        if lead is not None:
            call = (Call.query.filter_by(lead_id=lead.id)
                    .order_by(Call.started_at.desc()).first())
    if call is None:
        return {"ok": False, "error": "no call"}
    disp = (body.get("disposition") or "").strip()
    settings = get_settings(account_id)
    if disp == "handoff":
        # The seamless hand-off. The call is ours, so it is moved into the
        # room right now; the agent's stream ends as the call leaves it.
        from dialer.bridge import handoff_owned
        r = handoff_owned(call, settings)
        if r.get("ok"):
            calls_mod.set_disposition(call, "transferred", settings=settings)
            db.session.commit()
            return {"ok": True, "disposition": "transferred",
                    "message": "Handing over now. Say nothing more."}
        return {"ok": False, "error": r.get("error", "hand-off failed"),
                "message": "Nobody on the team is free. Say: \"It looks like "
                           "our team is tied up at the moment. What's the "
                           "best time for someone from our team to call you "
                           "back?\" Then schedule_callback with asked_by "
                           "manager, set_disposition callback, and end."}
    calls_mod.set_disposition(call, disp, settings=settings)
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


# Our own call id, filled in by ElevenLabs from the dynamic variables we
# hand it when WE place the call. The vendor's conversation id is not known
# to us until a tool call or the post-call webhook carries it, so this is
# the key every tool and the post-call hook look up first. dynamic_variable
# means the platform fills it, not the model.
# Exactly ONE of description / dynamic_variable / is_system_provided /
# constant_value / is_omitted per property, or ElevenLabs rejects the whole
# agent: "Can only set one of". A description beside the dynamic_variable
# did exactly that on a live sync.
HQ_CALL_ID = {"type": "string", "dynamic_variable": "hq_call_id"}
TOOL_SPECS = [
    {"name": "lookup_lead", "description":
     "Look up what we already know about the person you are speaking to. "
     "Call this at the start if you need their history.",
     "parameters": {"type": "object", "properties": {
         "phone": {"type": "string",
                   "description": "The phone number you dialled, in full "
                                  "international form such as +18655550101."},
         "conversation_id": CONVERSATION_ID, "hq_call_id": HQ_CALL_ID}}},
    {"name": "log_note", "description":
     "Write something you learned onto the lead's record.",
     "parameters": {"type": "object", "properties": {
         "note": {"type": "string",
                  "description": "What you learned, in one or two plain "
                                 "sentences. Include any day or time they "
                                 "gave you for a callback, in their words."},
         "conversation_id": CONVERSATION_ID, "hq_call_id": HQ_CALL_ID},
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
         "conversation_id": CONVERSATION_ID, "hq_call_id": HQ_CALL_ID}, "required": ["title"]}},
    {"name": "schedule_callback", "description":
     "Book the next call for when the manager or owner will be in. Call this "
     "the moment they give you a day or time, in their words: it creates the "
     "next call by itself, in the venue's own time zone.",
     "parameters": {"type": "object", "properties": {
         "when": {"type": "string",
                  "description": "Exactly what they said about when, in their "
                                 "words: \"around 4\", \"after 5\", "
                                 "\"tomorrow at noon\", \"in 30 minutes\", "
                                 "\"Thursday morning\", \"between 3 and 6\"."},
         "manager_name": {"type": "string",
                          "description": "The manager or owner's name if anyone "
                                         "said it; otherwise leave it empty."},
         "asked_by": {"type": "string",
                      "description": "Who gave the time: manager if the decision "
                                     "maker asked for the call back themselves, "
                                     "otherwise staff.",
                      "enum": ["manager", "staff"]},
         "conversation_id": CONVERSATION_ID, "hq_call_id": HQ_CALL_ID},
         "required": ["when"]}},
    {"name": "set_disposition", "description":
     "Record the outcome. Use dnc immediately if they ask not to be called "
     "again.",
     "parameters": {"type": "object", "properties": {
         "disposition": {
             "type": "string",
             "description": "How the call ended. Use handoff THE INSTANT "
                            "you are speaking to a decision maker: it hands "
                            "the live call to a person and you say nothing "
                            "more. Use callback when they asked to be "
                            "reached another time, qualified when they are "
                            "the right person and interested, and dnc the "
                            "moment they ask not to be called. manager_busy "
                            "when they are in but cannot talk now; "
                            "business_closed when the business has shut down.",
             "enum": ["handoff", "dm_reached", "gatekeeper", "callback",
                      "meeting_set", "qualified", "not_interested",
                      "voicemail_left", "wrong_number", "dnc",
                      "manager_busy", "business_closed"]},
         "conversation_id": CONVERSATION_ID, "hq_call_id": HQ_CALL_ID}, "required": ["disposition"]}},
]
