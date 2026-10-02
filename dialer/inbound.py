"""What happens when someone calls one of your numbers.

Order of preference: a live rep who is available, then the AI agent, then
voicemail. After hours it goes straight to the AI, which can still qualify and
book a callback. A number that was used for outbound and later parked keeps
answering, because the people who were called have it in their phone.
"""
from datetime import datetime, timezone

from flask import url_for

from app import Lead, Note, db

from dialer import tz
from dialer.compliance import normalize
from dialer.models import AiAgent, RepPresence


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def available_reps(account_id):
    return (RepPresence.query
            .filter_by(account_id=account_id, available_for_transfers=True)
            .filter(RepPresence.current_call_id.is_(None))
            .order_by(RepPresence.last_seen_at.desc()).limit(10).all())


def within_hours(settings):
    if settings is None or not settings.enforce_window:
        return True
    zone = "America/New_York"
    inside, _ = tz.in_window(zone, settings.window_start, settings.window_end,
                             settings.window_weekdays)
    return inside


def find_or_create_lead(account_id, caller, called):
    """An inbound caller is a lead whether or not we've met them."""
    e164, key, ok = normalize(caller)
    if not ok:
        return None
    lead = Lead.query.filter_by(owner_id=account_id, phone_key=key).first()
    if lead is not None:
        return lead
    lead = Lead(owner_id=account_id, name=f"Caller {e164[-4:]}", phone=e164,
                phone_e164=e164, phone_key=key, source="Inbound call",
                status="New", timezone=tz.zone_for(e164),
                state_code=tz.state_for(e164),
                consent_status="inbound", consent_source=f"called {called}",
                consent_at=_now())
    db.session.add(lead)
    db.session.flush()
    db.session.add(Note(lead_id=lead.id, kind="system",
                        body=f"Called in to {called}. They started the "
                             f"conversation, so this number is consented."))
    db.session.commit()
    return lead


def route_inbound(account_id, settings, number, caller, called, call_sid):
    """-> a TwiML document string."""
    lead = find_or_create_lead(account_id, caller, called)
    purpose = (number.purpose if number else "both")
    parked = bool(number and number.state == "parked")

    # 1. a human, if one is free and it is a working hour
    if purpose in ("inbound", "both") and not parked and within_hours(settings):
        reps = available_reps(account_id)
        if reps:
            clients = "".join(
                f"<Client><Identity>t{account_id}_u{r.user_id}</Identity></Client>"
                for r in reps[:10])
            from dialer import urls
            action = urls.twilio_status(account_id)
            return (f'<Response><Dial timeout="20" answerOnBridge="true" '
                    f'action="{action}">{clients}</Dial>'
                    f'{_ai_or_voicemail(account_id, settings, lead)}</Response>')

    return f"<Response>{_ai_or_voicemail(account_id, settings, lead)}</Response>"


def _ai_or_voicemail(account_id, settings, lead):
    """Fallback chain as a TwiML fragment."""
    agent = (AiAgent.query
             .filter_by(account_id=account_id, direction="inbound", active=True)
             .first())
    if agent and agent.elevenlabs_agent_id and settings \
            and (settings.has_elevenlabs or settings.simulation):
        from dialer.providers import registry
        va = registry.voice_agent(settings)
        r = va.register_call(agent.elevenlabs_agent_id, "", "", "inbound",
                             variables=_vars(lead))
        if r.get("ok") and r.get("twiml"):
            inner = r["twiml"]
            # register_call returns a whole document; unwrap it so it can be
            # nested after a <Dial> that did not connect
            inner = inner.replace("<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "")
            inner = inner.replace("<Response>", "").replace("</Response>", "")
            return inner
    who = (settings.ai_disclosure_name if settings else "") or "our team"
    from dialer import urls
    rec_url = urls.twilio_recording(account_id)
    return (f'<Say voice="alice">Thanks for calling {who}. Nobody is free right '
            f'now — leave a message after the tone and we will call you back.'
            f'</Say><Record maxLength="120" playBeep="true" '
            f'recordingStatusCallback="{rec_url}"/><Hangup/>')


def _vars(lead):
    if lead is None:
        return {}
    return {"lead_name": lead.name or "there",
            "first_name": (lead.name or "there").split(" ")[0],
            "business": lead.business or "", "is_known": "true",
            "lead_status": lead.status or "New",
            "prior_calls": str(lead.call_count or 0)}
