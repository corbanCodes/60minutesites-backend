"""Carrier and vendor webhooks.

Two rules here, both load-bearing:
  1. Validate the signature, write the payload to webhook_inbox, return 204.
     Never call a vendor API or an LLM inside a webhook -- Twilio allows 15
     seconds and retries once, and this app runs two gunicorn workers.
  2. Be idempotent. Retries are byte-identical, so dedupe_key is the only way
     to tell a replay from a new event.

The TwiML-returning routes are the exception: they must answer with XML, so
they do one indexed lookup and build a static document.
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, request, url_for

from app import db

from dialer.models import Call, CallEvent, DialerSettings, PhoneNumber, WebhookInbox

hooks_bp = Blueprint("dialer_hooks", __name__, url_prefix="/dialer/hooks")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _xml(body):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>{body}',
                    mimetype="text/xml")


def _settings(account_id):
    return DialerSettings.query.filter_by(account_id=account_id).first()


def _public_url():
    """Railway terminates TLS and forwards plain HTTP, so request.url says
    http:// and Twilio's signature -- computed over the https URL it called --
    would never match. Rebuild it from the forwarded headers."""
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    if not proto and not host:
        return request.url
    proto = proto or "https"
    host = host or request.host
    return f"{proto}://{host}{request.full_path.rstrip('?')}"


def _verify_twilio(settings):
    """-> bool. In simulation the fake validator accepts everything."""
    from dialer.providers import registry
    sig = request.headers.get("X-Twilio-Signature", "")
    if registry.simulating(settings):
        return True
    if not settings:
        return False
    try:
        return bool(registry.telephony(settings).validate_signature(
            sig, _public_url(), request.form.to_dict()))
    except Exception:
        return False


def _inbox(account_id, source, kind, dedupe_key, payload, signature_ok=True):
    """Idempotent write. Returns False when this exact event was already seen."""
    if dedupe_key and WebhookInbox.query.filter_by(dedupe_key=dedupe_key).first():
        return False
    db.session.add(WebhookInbox(
        account_id=account_id, source=source, kind=kind,
        dedupe_key=dedupe_key[:200] if dedupe_key else None,
        signature_ok=signature_ok,
        payload=json.dumps(payload)[:200000]))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return True


# ------------------------------------------------------------- Twilio: TwiML
@hooks_bp.route("/twilio/<int:account_id>/outgoing", methods=["POST", "GET"])
def twilio_outgoing(account_id):
    """The TwiML App's voice URL: what a browser-initiated call should do."""
    s = _settings(account_id)
    if not _verify_twilio(s):
        abort(403)
    to = request.values.get("To") or request.values.get("to") or ""
    call_id = request.values.get("call_id", type=int)
    conf = request.values.get("conf", "")
    call = db.session.get(Call, call_id) if call_id else None

    # A rep joining their shift conference.
    if conf:
        return _xml(
            f'<Response><Dial><Conference startConferenceOnEnter="true" '
            f'endConferenceOnExit="true" beep="false" '
            f'jitterBufferSize="small">{conf}</Conference></Dial></Response>')

    caller_id = (call.from_number if call else "") or request.values.get(
        "From", "")
    announce = ""
    if s and s.recording_enabled and s.recording_announce and s.announce_text:
        announce = f'<Say voice="alice">{s.announce_text}</Say>'
        if call:
            call.announce_played_at = _now()
            db.session.commit()
    record = ' record="record-from-answer-dual"' if (
        s and s.recording_enabled) else ""
    from dialer import urls
    status_cb = urls.twilio_status(account_id)
    limit = (s.max_call_seconds if s else 600) or 600
    return _xml(
        f'<Response>{announce}<Dial callerId="{caller_id}" timeLimit="{limit}"'
        f'{record} answerOnBridge="true" action="{status_cb}">'
        f'<Number statusCallback="{status_cb}" '
        f'statusCallbackEvent="initiated ringing answered completed">'
        f'{to}</Number></Dial></Response>')


@hooks_bp.route("/twilio/<int:account_id>/voice", methods=["POST", "GET"])
def twilio_voice(account_id):
    """Someone called one of this account's numbers."""
    s = _settings(account_id)
    if not _verify_twilio(s):
        abort(403)
    called = request.values.get("To", "")
    caller = request.values.get("From", "")
    number = PhoneNumber.query.filter_by(account_id=account_id,
                                         e164=called).first()
    _inbox(account_id, "twilio", "inbound",
           f"inbound:{request.values.get('CallSid', '')}",
           request.values.to_dict())

    from dialer.inbound import route_inbound
    return _xml(route_inbound(account_id, s, number, caller, called,
                              request.values.get("CallSid", "")))


@hooks_bp.route("/twilio/voicemail/<int:call_id>", methods=["POST", "GET"])
def twilio_voicemail(call_id):
    """A voicemail-blast leg answered. AMD decides whether to play or hang up."""
    call = db.session.get(Call, call_id)
    if call is None:
        return _xml("<Response><Hangup/></Response>")
    s = _settings(call.account_id)
    if not _verify_twilio(s):
        abort(403)
    answered_by = request.values.get("AnsweredBy", "")
    if answered_by.startswith("machine"):
        return _xml(_drop_twiml(call))
    # A person picked up. Say who is calling rather than dead air, then stop.
    who = (s.ai_disclosure_name or "our team") if s else "our team"
    return _xml(f'<Response><Say voice="alice">Sorry to trouble you — this is '
                f'{who}. We will call back at a better time.</Say>'
                f'<Hangup/></Response>')


def _drop_twiml(call):
    from dialer.models import Campaign, VoicemailDrop
    camp = db.session.get(Campaign, call.campaign_id) if call.campaign_id else None
    drop_id = camp.voicemail_drop_id if camp else None
    drop = db.session.get(VoicemailDrop, drop_id) if drop_id else None
    if drop is None:
        return "<Response><Hangup/></Response>"
    if not drop.media_id:
        # A drop row with no audio behind it plays silence. Marking the call
        # "voicemail dropped" anyway is the worst possible outcome: the rep
        # moves on believing they left a message, the lead never hears one,
        # and the follow-up is scheduled against a conversation that did not
        # happen. Say nothing and leave the flag alone.
        call.error = (call.error or "") or "voicemail drop has no audio"
        db.session.commit()
        return "<Response><Hangup/></Response>"
    from dialer import urls
    url = urls.voicemail_media(drop.id)
    call.voicemail_dropped = True
    db.session.commit()
    return f"<Response><Play>{url}</Play><Hangup/></Response>"


# --------------------------------------------------------- Twilio: events
@hooks_bp.route("/twilio/<int:account_id>/status", methods=["POST"])
def twilio_status(account_id):
    s = _settings(account_id)
    ok = _verify_twilio(s)
    p = request.form.to_dict()
    sid = p.get("CallSid", "")
    status = p.get("CallStatus") or p.get("DialCallStatus") or ""
    _inbox(account_id, "twilio", f"status:{status}", f"{sid}:{status}", p, ok)
    return "", 204


@hooks_bp.route("/twilio/amd/<int:call_id>", methods=["POST"])
def twilio_amd(call_id):
    call = db.session.get(Call, call_id)
    if call is None:
        return "", 204
    p = request.form.to_dict()
    _inbox(call.account_id, "twilio", "amd",
           f"amd:{p.get('CallSid', call_id)}", p)
    return "", 204


@hooks_bp.route("/twilio/recording/<int:account_id>", methods=["POST"])
def twilio_recording(account_id):
    p = request.form.to_dict()
    _inbox(account_id, "twilio", "recording",
           f"rec:{p.get('RecordingSid', '')}", p)
    return "", 204


# -------------------------------------------------------------- ElevenLabs
@hooks_bp.route("/elevenlabs/post-call", methods=["POST"])
def elevenlabs_post_call():
    """Transcript + analysis for a finished AI conversation.

    The tenant is resolved from the agent id BEFORE the body is trusted, so we
    know which secret to check the signature against.
    """
    raw = request.get_data(as_text=True)
    try:
        body = json.loads(raw or "{}")
    except ValueError:
        return "", 204
    data = body.get("data") or body
    conv_id = (data.get("conversation_id") or data.get("conversationId") or "")
    agent_id = data.get("agent_id") or data.get("agentId") or ""

    call = Call.query.filter_by(elevenlabs_conversation_id=conv_id).first() \
        if conv_id else None
    account_id = call.account_id if call else None
    if account_id is None and agent_id:
        from dialer.models import AiAgent
        a = AiAgent.query.filter_by(elevenlabs_agent_id=agent_id).first()
        account_id = a.account_id if a else None

    s = _settings(account_id) if account_id else None
    sig_ok = True
    if s:
        from dialer.providers import registry
        if not registry.simulating(s):
            secret = s.secret("elevenlabs_webhook_secret")
            sig_ok = bool(secret) and registry.voice_agent(s).verify_signature(
                raw, request.headers.get("elevenlabs-signature", ""), secret)
    if not sig_ok:
        return "", 403
    _inbox(account_id, "elevenlabs", "post_call",
           f"el:{conv_id}:{data.get('event_timestamp', '')}", body, sig_ok)
    return "", 204


@hooks_bp.route("/elevenlabs/init", methods=["POST"])
def elevenlabs_init():
    """Called while the phone is still ringing: hand the agent its CRM context.

    This one must be fast -- the caller is waiting on it -- so it does a single
    indexed lookup and falls back to a complete default on any error. A missing
    variable is a failure for ElevenLabs, so the dict is always whole.
    """
    try:
        body = request.get_json(silent=True) or {}
        caller = body.get("caller_id") or body.get("from_number") or ""
        called = body.get("called_number") or body.get("to_number") or ""
        base = {"lead_name": "there", "first_name": "there", "business": "",
                "business_type": "", "city": "", "state": "",
                "prior_calls": "0", "last_note": "", "lead_status": "New",
                "is_known": "false"}
        number = PhoneNumber.query.filter_by(e164=called).first()
        if number is not None:
            from dialer.compliance import normalize
            _, key, ok = normalize(caller)
            if ok:
                from app import Lead
                lead = Lead.query.filter_by(owner_id=number.account_id,
                                            phone_key=key).first()
                if lead is not None:
                    base.update({
                        "lead_name": lead.name or "there",
                        "first_name": (lead.name or "there").split(" ")[0],
                        "business": lead.business or "",
                        "business_type": lead.business_type or "",
                        "state": lead.state_code or "",
                        "prior_calls": str(lead.call_count or 0),
                        "lead_status": lead.status or "New",
                        "is_known": "true"})
        return {"type": "conversation_initiation_client_data",
                "dynamic_variables": base}
    except Exception:
        return {"type": "conversation_initiation_client_data",
                "dynamic_variables": {
                    "lead_name": "there", "first_name": "there", "business": "",
                    "business_type": "", "city": "", "state": "",
                    "prior_calls": "0", "last_note": "", "lead_status": "New",
                    "is_known": "false"}}


@hooks_bp.route("/elevenlabs/tools/<name>", methods=["POST"])
def elevenlabs_tool(name):
    """Mid-call tools the agent can call: look a lead up, leave a note, book a
    follow-up, set the outcome."""
    from dialer.tools import run_tool
    body = request.get_json(silent=True) or {}
    token = request.headers.get("X-HQ-Token", "")
    return run_tool(name, body, token)


@hooks_bp.route("/ping")
def ping():
    return "", 204
