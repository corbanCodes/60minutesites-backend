"""Absolute webhook URLs that work inside a request AND inside the worker.

Flask's url_for(_external=True) needs either a request context or SERVER_NAME,
and the worker process has neither. Setting SERVER_NAME globally changes
routing for the whole app, so instead the hook paths -- which are fixed and few
-- are built by hand against the configured public origin.
"""
import os


def origin():
    """https://<the host this HQ is reachable at>, no trailing slash.

    Railway terminates TLS and forwards plain HTTP, so anything derived from
    request.url says http:// and a Twilio signature check would never match.
    hq_origin() in app.py already honours X-Forwarded-Proto; PUBLIC_URL is the
    override the worker uses, since it has no request at all.
    """
    env = (os.environ.get("PUBLIC_URL") or os.environ.get("HQ_ORIGIN") or "").strip()
    if env:
        return env.rstrip("/")
    try:
        from flask import has_request_context
        if has_request_context():
            from app import hq_origin
            return hq_origin().rstrip("/")
    except Exception:
        pass
    host = (os.environ.get("CANONICAL_HOST") or "").strip()
    if host:
        return f"https://{host}".rstrip("/")
    return "http://localhost:5062"


def hook(path):
    return f"{origin()}/dialer/hooks{path}"


def twilio_outgoing(account_id, call_id=None):
    url = hook(f"/twilio/{account_id}/outgoing")
    return f"{url}?call_id={call_id}" if call_id else url


def twilio_voice(account_id):
    return hook(f"/twilio/{account_id}/voice")


def twilio_status(account_id):
    return hook(f"/twilio/{account_id}/status")


def twilio_bridge_rep(account_id, room):
    """Status callback for the rep's leg of a silent hand-off."""
    return hook(f"/twilio/{account_id}/bridge/{room}/rep")


def handoff_wait(account_id):
    """The looping wait-audio TwiML a parked prospect hears."""
    return hook(f"/twilio/{account_id}/bridge/wait")


def twilio_amd(call_id):
    return hook(f"/twilio/amd/{call_id}")


def twilio_recording(account_id):
    return hook(f"/twilio/recording/{account_id}")


def twilio_voicemail(call_id):
    return hook(f"/twilio/voicemail/{call_id}")


def elevenlabs_post_call():
    return hook("/elevenlabs/post-call")


def elevenlabs_init():
    return hook("/elevenlabs/init")


def elevenlabs_tool(name):
    return hook(f"/elevenlabs/tools/{name}")


def voicemail_media(drop_id):
    return f"{origin()}/dialer/vm/{drop_id}"
