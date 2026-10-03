"""The silent hand-off: our own conference, our own wait audio.

ElevenLabs offers three ways to hand a call to a person and none of them
is quiet. "blind" redirects the prospect's leg to dial the destination,
so they hear ringback. "conference" parks them in a Twilio conference that
ElevenLabs owns, and an unconfigured Twilio conference plays its default
classical playlist -- waitUrl is not ours to set. "sip_refer" needs a SIP
trunk, and every number here arrives through the native Twilio
integration. Verified against their spec on 2026-10-02.

So the vendor does not get the last leg. The agent blind-transfers to one
of the ACCOUNT'S OWN numbers -- one whose voice webhook points at this app
-- and this module answers it:

    prospect  --blind-->  our rep-pool number  --> our <Conference>
                                                    waitUrl = office ambience
                                                    (not Twilio's music)
    rep       <--  we dial them into the same room, they join, room starts

The prospect hears the room tone carry on and then a person. No ring,
because a conference generates none. No hold music, because the wait
audio is ours. When the rep hangs up the room ends.

What identifies a hand-off from an ordinary inbound call: a blind
transfer preserves the original caller ID, and on an outbound AI call the
original caller is the AI's own number. A member of the public cannot
call us FROM one of our numbers, so From being in the account's AI pool
is a hand-off. As a second signal, the prospect's number is on a live AI
call on this account.
"""
from datetime import datetime, timedelta, timezone

from app import db

from dialer.models import AiAgent, Call, PhoneNumber

# The room name carries the prospect's call SID, so the rep leg's status
# callback can find the prospect without any stored mapping -- there are
# several gunicorn workers and nothing in memory survives between them.
ROOM_PREFIX = "handoff-"
REP_RING_SECONDS = 20
LIVE_WINDOW = timedelta(minutes=20)

# Said only if the rep does not pick up. Short, plain, and it books a
# callback rather than leaving someone in a silent room.
NO_ANSWER_LINE = ("Sorry about that — we'll give you a call back "
                  "shortly. Thanks.")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def handoff_line(account_id):
    """The account's own number a hand-off is sent to, or None.

    It has to be a number whose voice webhook points at this app, which is
    every rep-pool number. An AI-pool number's inbound goes to ElevenLabs,
    so handing off to one of those would start a second AI conversation.
    """
    return (PhoneNumber.query
            .filter_by(account_id=account_id, pool="rep", state="active")
            .filter(PhoneNumber.twilio_sid.isnot(None))
            .filter(PhoneNumber.twilio_sid != "")
            .order_by(PhoneNumber.id.asc()).first())


def room_for(prospect_call_sid):
    return f"{ROOM_PREFIX}{prospect_call_sid}"


def prospect_sid_from(room):
    return room[len(ROOM_PREFIX):] if room.startswith(ROOM_PREFIX) else ""


def live_ai_call(account_id, caller_e164):
    """The in-progress AI call whose prospect is this number, if any."""
    since = _now() - LIVE_WINDOW
    return (Call.query
            .filter_by(account_id=account_id, mode="ai_outbound")
            .filter(Call.to_number == caller_e164)
            .filter(Call.started_at >= since)
            .filter(Call.status.notin_(("completed", "failed", "canceled",
                                        "busy", "no-answer")))
            .order_by(Call.started_at.desc()).first())


def detect(account_id, caller, called):
    """-> (agent, call) when this inbound call is a hand-off, else None.

    `caller` is Twilio's From on the inbound leg; `called` is our number.
    """
    line = handoff_line(account_id)
    if line is None or called != line.e164:
        return None

    from_ai_pool = (PhoneNumber.query
                    .filter_by(account_id=account_id, pool="ai",
                               e164=caller).first() is not None)
    call = None
    if from_ai_pool:
        # Caller ID preserved: From is the AI's number. The prospect is
        # whoever that number is currently talking to.
        since = _now() - LIVE_WINDOW
        call = (Call.query
                .filter_by(account_id=account_id, mode="ai_outbound",
                           from_number=caller)
                .filter(Call.started_at >= since)
                .filter(Call.status.notin_(("completed", "failed",
                                            "canceled", "busy",
                                            "no-answer")))
                .order_by(Call.started_at.desc()).first())
    else:
        call = live_ai_call(account_id, caller)
    if call is None and not from_ai_pool:
        return None

    agent = db.session.get(AiAgent, call.ai_agent_id) if (
        call and call.ai_agent_id) else None
    if agent is None:
        agent = (AiAgent.query
                 .filter_by(account_id=account_id, direction="outbound",
                            active=True)
                 .filter(AiAgent.transfer_handoff == "bridge")
                 .first())
    if agent is None:
        return None
    return agent, call


def ambience_url():
    """The audio file itself."""
    from dialer import urls
    return f"{urls.origin()}/static-admin/handoff-office.mp3"


def wait_url(account_id):
    """What waitUrl points at: a TwiML document, NOT the file.

    Twilio documents looping only one way: a TwiML document that ends in a
    <Redirect/> with a blank URL. A bare MP3 at waitUrl is played once and
    then "silence will be played" -- so a hand-off that outlasted the clip
    would go dead quiet. Verified against the <Conference> docs.
    """
    from dialer import urls
    return urls.handoff_wait(account_id)


def wait_twiml():
    """Play the ambience, then start again. Blank <Redirect/> loops."""
    return (f'<Response><Play>{ambience_url()}</Play><Redirect/></Response>')


def prospect_twiml(room, account_id):
    """Park the prospect in the room with our wait audio.

    startConferenceOnEnter="false": the room does not start until the rep
    joins, and until then the prospect hears waitUrl. beep off, because a
    beep is the one thing more jarring than music. waitMethod GET so the
    looping document is fetched the way Twilio caches static media.
    """
    return (f'<Response><Dial><Conference beep="false" '
            f'startConferenceOnEnter="false" endConferenceOnExit="false" '
            f'waitUrl="{wait_url(account_id)}" waitMethod="GET">'
            f'{room}</Conference></Dial></Response>')


def rep_twiml(room):
    """The rep's leg: join the room, start it, and end it on hang-up."""
    return (f'<Response><Dial><Conference beep="false" '
            f'startConferenceOnEnter="true" endConferenceOnExit="true">'
            f'{room}</Conference></Dial></Response>')


def ring_rep(settings, account_id, agent, room, caller_id):
    """Dial the human into the room. -> provider result dict."""
    from dialer.agents import human_number
    from dialer.providers import registry
    from dialer import urls
    to = human_number(settings, agent)
    if not to:
        return {"ok": False, "error": "no human destination"}
    return registry.telephony(settings).create_call(
        to=to, from_=caller_id, twiml=rep_twiml(room),
        timeout=REP_RING_SECONDS,
        status_callback=urls.twilio_bridge_rep(account_id, room))


def try_bridge(account_id, settings, caller, called, call_sid):
    """-> TwiML string when this call is a hand-off, else None.

    Answers the prospect into the room and rings the rep in the same
    request, so the two legs start within milliseconds of each other.
    """
    found = detect(account_id, caller, called)
    if found is None:
        return None
    agent, call = found
    room = room_for(call_sid)
    line = handoff_line(account_id)
    r = ring_rep(settings, account_id, agent, room,
                 caller_id=line.e164 if line else caller)
    if call is not None:
        from dialer.calls import event
        event(call, "handoff",
              f"bridged into {room}; rep leg "
              f"{'placed' if r.get('ok') else 'FAILED: ' + str(r.get('error'))}")
        db.session.commit()
    if not r.get("ok"):
        # Nobody to dial. Do not leave them in a silent room.
        return no_answer_twiml()
    return prospect_twiml(room, account_id)


def no_answer_twiml():
    return (f'<Response><Say voice="alice">{NO_ANSWER_LINE}</Say>'
            f'<Hangup/></Response>')


def rep_leg_ended(settings, account_id, room, status):
    """The rep's leg finished without connecting: free the prospect.

    Twilio reports no-answer, busy, failed or canceled for a leg that never
    bridged. The prospect is still in the room hearing office ambience, so
    they are redirected to one short line and a hang-up, and the AI call is
    marked for a callback.
    """
    if status not in ("no-answer", "busy", "failed", "canceled"):
        return False
    sid = prospect_sid_from(room)
    if not sid:
        return False
    from dialer.providers import registry
    registry.telephony(settings).redirect_call(sid, no_answer_twiml())
    call = Call.query.filter_by(account_id=account_id, twilio_sid=sid).first()
    if call is None:
        # The AI call row holds ElevenLabs' SID, not the transferred leg's.
        call = (Call.query
                .filter_by(account_id=account_id, mode="ai_outbound")
                .filter(Call.started_at >= _now() - LIVE_WINDOW)
                .order_by(Call.started_at.desc()).first())
    if call is not None:
        from dialer.calls import event
        event(call, "handoff_failed", f"rep leg {status}; prospect told we "
                                      f"will call back")
        if not call.disposition:
            call.disposition = "callback"
        db.session.commit()
    return True
