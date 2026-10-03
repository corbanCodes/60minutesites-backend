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

from sqlalchemy import or_

from app import db

from dialer.models import AiAgent, Call, CallEvent, PhoneNumber

# The room name carries the prospect's call SID, so the rep leg's status
# callback can find the prospect without any stored mapping -- there are
# several gunicorn workers and nothing in memory survives between them.
ROOM_PREFIX = "handoff-"
# 15, not 20: a carrier rolls an unanswered mobile to voicemail at 15-30s,
# and Twilio may add a 5s buffer. The ring must give up first.
REP_RING_SECONDS = 15
LIVE_WINDOW = timedelta(minutes=20)
# A blind transfer ENDS the ElevenLabs conversation the instant it fires,
# so their post-call webhook can land -- and mark the Call completed --
# before Twilio has even reached our voice hook with the transferred leg.
# A call that ended within this grace is still "live" for detection.
ENDED_GRACE = timedelta(minutes=2)
TERMINAL = ("completed", "failed", "canceled", "busy", "no-answer")
# A second transferred leg for the SAME call inside this window joins the
# room already made for it and does not ring the rep again. Twilio retries
# a webhook, and a vendor that believes its transfer failed retries the
# transfer -- on one live test that was a new leg every thirteen seconds
# for eight minutes. One rep leg per hand-off, full stop.
REPEAT_WINDOW = timedelta(seconds=90)

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
    rows = (PhoneNumber.query
            .filter_by(account_id=account_id, pool="rep", state="active")
            .filter(PhoneNumber.twilio_sid.isnot(None))
            .filter(PhoneNumber.twilio_sid != "")
            .order_by(PhoneNumber.id.asc()).all())
    # Sample numbers have invented SIDs and sit at the lowest ids. Handing a
    # live prospect to one would have the vendor dial a 555 number.
    return next((n for n in rows if not n.is_placeholder), None)


def ensure_line(settings, account_id):
    """Point the hand-off line's Twilio voice webhook at this app.

    -> {"ok", "line", "error"}. The bridge is only as good as the webhook
    on the number it lands on, and that webhook is not ours to assume: a
    number that was ever in the AI pool had its voice URL rewritten to
    ElevenLabs when it was imported, and a pool move back to reps did not
    rewrite it. On the first live test the transfer fired, ElevenLabs
    dialled the rep line, and Twilio played "an application error has
    occurred" because the URL on that number was not this app's. No
    request ever reached /voice. So the app sets it, every time the bridge
    is chosen, rather than hoping.
    """
    line = handoff_line(account_id)
    if line is None:
        return {"ok": False, "line": None, "error": "no rep-pool number"}
    from dialer.providers import registry
    from dialer import urls
    tel = registry.telephony(settings)
    want = urls.twilio_voice(account_id)
    # Look first. A number imported from an existing Twilio account may be
    # the customer's main line running their own IVR; overwriting that in
    # silence on an agent save would be a disaster with no undo. If it is
    # already ours, nothing to do; if it is somebody's, the old URL is kept
    # on the row so it can be put back.
    cur = tel.fetch_number(line.twilio_sid) if hasattr(tel, "fetch_number") \
        else {"ok": False}
    if cur.get("ok") and (cur.get("voice_url") or "") == want:
        return {"ok": True, "line": line, "error": "", "changed": False}
    old_url = (cur.get("voice_url") or "") if cur.get("ok") else ""
    if old_url:
        stamp = _now().strftime("%Y-%m-%d %H:%M")
        line.notes = ((line.notes or "").rstrip() +
                      f"\n[{stamp}] voice webhook was {old_url} before the "
                      f"hand-off bridge pointed it at this app.").strip()
        db.session.commit()
    r = tel.configure_number(line.twilio_sid, want,
                             urls.twilio_status(account_id))
    return {"ok": bool(r.get("ok")), "line": line,
            "error": r.get("error") or "", "changed": True}


def room_for(prospect_call_sid):
    return f"{ROOM_PREFIX}{prospect_call_sid}"


def prospect_sid_from(room):
    return room[len(ROOM_PREFIX):] if room.startswith(ROOM_PREFIX) else ""


def _live_calls(account_id):
    """AI calls that are, for hand-off purposes, still happening.

    Non-terminal, OR ended within ENDED_GRACE: the vendor marks the call
    over the moment the transfer fires, which is before the transferred
    leg reaches us.
    """
    now = _now()
    return (Call.query
            .filter_by(account_id=account_id, mode="ai_outbound")
            .filter(Call.started_at >= now - LIVE_WINDOW)
            .filter(or_(Call.status.notin_(TERMINAL),
                        Call.ended_at >= now - ENDED_GRACE)))


def live_ai_call(account_id, caller_e164):
    """The live AI call whose prospect is this number, if any."""
    return (_live_calls(account_id)
            .filter(Call.to_number == caller_e164)
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
        call = (_live_calls(account_id)
                .filter(Call.from_number == caller)
                .order_by(Call.started_at.desc()).first())
    else:
        call = live_ai_call(account_id, caller)

    if call is None and not from_ai_pool:
        # Neither caller-ID signal matched. ElevenLabs does not document
        # what From a blind transfer presents, and on the first live test
        # it was neither the AI's number nor the prospect's -- so the
        # hand-off fell through to the voicemail greeting. A call landing
        # on the hand-off line while an AI call is live on an agent set to
        # the bridge IS the hand-off, whatever the caller ID says. The
        # window is short so an unrelated inbound call minutes later is
        # not mistaken for one.
        call = live_bridge_call(account_id)
        if call is None:
            _warn(f"call to hand-off line {called} from {caller} matched "
                  f"no live AI call; treated as ordinary inbound")
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


def live_bridge_call(account_id):
    """The one live AI call on an agent set to the bridge, or None.

    Exactly one. With two live calls there is no honest way to say which
    prospect this leg is without a caller ID that matches, and bridging
    a guess would hand a stranger to the rep as if they were the prospect.
    The 20-minute window is the same one the caller-ID signals use; a
    5-minute one measured from row creation cut off any conversation that
    reached the decision maker after minute four and a half.
    """
    bridge_agents = [a.id for a in AiAgent.query.filter_by(
        account_id=account_id).filter(AiAgent.transfer_handoff == "bridge")]
    if not bridge_agents:
        return None
    rows = (_live_calls(account_id)
            .filter(Call.ai_agent_id.in_(bridge_agents))
            .order_by(Call.started_at.desc()).limit(2).all())
    if len(rows) != 1:
        if rows:
            _warn(f"{len(rows)} live bridge calls; refusing to guess")
        return None
    return rows[0]


def _warn(msg):
    try:
        from flask import current_app
        current_app.logger.warning("[bridge] %s", msg)
    except Exception:
        pass


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


PRESENCE_FRESH = timedelta(minutes=2)


def softphone_target(account_id):
    """-> "client:<identity>" for a rep whose browser phone is open and
    marked available, or "". Presence has to be fresh: a tab closed
    yesterday still has a row, and ringing it would ring nothing for
    twenty seconds and then apologise to the prospect."""
    from dialer.models import RepPresence
    since = _now() - PRESENCE_FRESH
    rep = (RepPresence.query
           .filter_by(account_id=account_id, available_for_transfers=True)
           .filter(RepPresence.current_call_id.is_(None))
           .filter(RepPresence.last_seen_at >= since)
           .order_by(RepPresence.last_seen_at.desc()).first())
    return f"client:t{account_id}_u{rep.user_id}" if rep else ""


def own_numbers(account_id):
    """Every E.164 this account holds at Twilio, any pool, any state."""
    return {n.e164 for n in PhoneNumber.query.filter_by(account_id=account_id)
            if n.e164}


def is_own_number(account_id, e164):
    """A hand-off destination that is one of the account's own numbers
    cannot work: the AI line answers with a second AI, the rep line
    answers with this app. On a live test the destination was the rep
    line itself, so the bridge dialled the rep line FROM the rep line,
    reached its own voicemail greeting, and machine detection -- quite
    correctly -- called it a machine."""
    from dialer.compliance import normalize
    e, _, ok = normalize(e164 or "")
    return bool(ok and e in own_numbers(account_id))


def _mark_busy(account_id, client, busy):
    """Hold or release the browser rep so two hand-offs never land on one
    person at once. The identity is t<account>_u<user>."""
    from dialer.models import RepPresence
    try:
        uid = int(client.rsplit("_u", 1)[1])
    except (IndexError, ValueError):
        return
    rep = RepPresence.query.filter_by(account_id=account_id, user_id=uid).first()
    if rep is None:
        return
    rep.current_call_id = -1 if busy else None
    db.session.commit()


def rep_destination(settings, account_id, agent):
    """Where the rep leg goes.

    The browser phone first, whenever one is open, available and seen in
    the last two minutes: it is what shows the rep the lead and the
    transcript as the call arrives, and for a one-person account it IS
    the second phone. Then a number typed on the agent, then the
    account-wide number. One of the account's own numbers is never a
    destination, typed or not.
    """
    if (settings.transfer_mode or "") != "number":
        client = softphone_target(account_id)
        if client:
            return client
    own = (getattr(agent, "transfer_to_number", "") or "").strip()
    if own and not is_own_number(account_id, own):
        return own
    from dialer.agents import human_number
    number = human_number(settings, agent)
    if number and is_own_number(account_id, number):
        return ""
    return number


def ring_rep(settings, account_id, agent, room, caller_id):
    """Dial the human into the room. -> provider result dict."""
    from dialer.providers import registry
    from dialer import urls
    to = rep_destination(settings, account_id, agent)
    if not to:
        return {"ok": False, "error": "no human destination"}
    if to.startswith("client:"):
        _mark_busy(account_id, to, True)
    extra = {}
    if not to.startswith("client:"):
        # A phone that is off, in Do Not Disturb or out of coverage rolls
        # to voicemail, and voicemail ANSWERS -- which would start the
        # room and play the rep's greeting to the prospect. Asynchronous
        # machine detection lets a human join at once and lets us pull
        # the prospect out if a machine picked up instead.
        extra = {"machine_detection": "Enable", "async_amd": True,
                 "amd_status_callback": urls.twilio_bridge_amd(account_id,
                                                               room)}
    return registry.telephony(settings).create_call(
        to=to, from_=caller_id, twiml=rep_twiml(room),
        timeout=REP_RING_SECONDS,
        status_callback=urls.twilio_bridge_rep(account_id, room), **extra)


def try_bridge(account_id, settings, caller, called, call_sid):
    """-> TwiML string when this call is a hand-off, else None.

    Answers the prospect into the room and rings the rep in the same
    request, so the two legs start within milliseconds of each other.
    """
    found = detect(account_id, caller, called)
    if found is None:
        return None
    agent, call = found
    if call is not None and call.conference_name:
        last = (CallEvent.query
                .filter_by(call_id=call.id, kind="handoff")
                .order_by(CallEvent.at.desc()).first())
        if last is not None and last.at >= _now() - REPEAT_WINDOW:
            from dialer.calls import event
            event(call, "handoff_repeat",
                  f"another leg from {caller or '?'} for a hand-off already "
                  f"in progress; joined {call.conference_name}, rep not rung "
                  f"again")
            db.session.commit()
            return prospect_twiml(call.conference_name, account_id)
    room = room_for(call_sid)
    line = handoff_line(account_id)
    r = ring_rep(settings, account_id, agent, room,
                 caller_id=line.e164 if line else caller)
    if call is not None:
        from dialer.calls import event
        # The room on the row is how the rep leg's callbacks find THIS
        # call later. Guessing "the most recent AI call" instead stamped
        # a failed hand-off onto whichever lead happened to be newest.
        call.conference_name = room
        event(call, "handoff",
              f"from {caller or '?'} bridged into {room}; rep leg to "
              f"{rep_destination(settings, account_id, agent)} "
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
    bridged. The prospect is still in the room hearing office ambience.
    """
    if status in ("completed", "no-answer", "busy", "failed", "canceled"):
        _release_all_busy(account_id)
    if status not in ("no-answer", "busy", "failed", "canceled"):
        return False
    return free_prospect(settings, account_id, room, f"rep leg {status}")


def _release_all_busy(account_id):
    """The rep leg carries no identity in its callback, and a one-person
    account has one rep; releasing every bridge-held rep on the account
    is correct for that and harmless otherwise, because the hold only
    ever lasts the length of one leg."""
    from dialer.models import RepPresence
    for rep in RepPresence.query.filter_by(account_id=account_id,
                                           current_call_id=-1):
        rep.current_call_id = None
    db.session.commit()


def machine_answered(settings, account_id, room, answered_by, rep_sid):
    """Asynchronous machine detection says voicemail picked up the rep leg.

    The prospect is pulled out of the room FIRST, then the rep leg is hung
    up. The other order would end the room under the prospect (the rep leg
    carries endConferenceOnExit) before the apology could be said.
    """
    if not (answered_by or "").startswith("machine"):
        return False
    freed = free_prospect(settings, account_id, room,
                          f"rep leg answered by {answered_by}")
    if rep_sid:
        from dialer.providers import registry
        registry.telephony(settings).hangup(rep_sid)
    return freed


def free_prospect(settings, account_id, room, reason):
    """Say one short line to the parked prospect and let them go, and book
    the callback on the call that was actually handed off."""
    sid = prospect_sid_from(room)
    if not sid:
        return False
    from dialer.providers import registry
    registry.telephony(settings).redirect_call(sid, no_answer_twiml())
    call = Call.query.filter_by(account_id=account_id,
                                conference_name=room).first()
    if call is None:
        _warn(f"no call carries room {room}; prospect freed, nothing booked")
        return True
    from dialer.calls import event, set_disposition
    event(call, "handoff_failed", f"{reason}; prospect told we will call back")
    if not call.disposition:
        set_disposition(call, "callback", settings=settings)
    db.session.commit()
    return True
