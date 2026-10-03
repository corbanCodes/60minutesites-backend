"""One timeline for a hand-off: server, Twilio and the rep's browser.

A night was spent reconstructing what a hand-off did from Railway's HTTP
log, which has paths and timestamps and nothing else. The questions that
actually mattered -- what From did the transferred leg carry, which
detection signal fired, where did the rep leg go, what did the SDK do in
the browser and when -- were all answerable only by adding a log line and
running another live test.

So every step now writes a CallEvent with the full payload, the browser
posts what the SDK is doing, and one page merges them in time order with
millisecond stamps and a plain-text dump to paste. The owner records the
call on his side; the two clocks line up on the "voice_in" row.

Nothing here changes behaviour. It only remembers.
"""
import json
from datetime import datetime, timedelta, timezone

from app import db

from dialer.models import Call, CallEvent, WebhookInbox

WINDOW = timedelta(minutes=30)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _jsonable(obj):
    try:
        return json.dumps(obj, default=str)[:6000]
    except Exception:
        return json.dumps(str(obj))[:6000]


def record(account_id, kind, detail="", payload=None, call_id=None):
    """Write one trace row. Never raises: a trace must not break a call."""
    try:
        db.session.add(CallEvent(
            call_id=call_id, account_id=account_id, kind=f"trace:{kind}",
            detail=str(detail)[:300],
            payload=_jsonable(payload) if payload is not None else ""))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def current_handoff_call(account_id):
    """The call most recently handed off on this account, if any."""
    since = _now() - WINDOW
    ev = (CallEvent.query
          .filter_by(account_id=account_id)
          .filter(CallEvent.kind.in_(("handoff", "trace:detect")))
          .filter(CallEvent.at >= since)
          .order_by(CallEvent.at.desc()).first())
    if ev is None or not ev.call_id:
        return None
    return db.session.get(Call, ev.call_id)


def timeline(account_id, call=None):
    """-> list of {at, src, kind, detail, payload} in time order.

    Everything on the call, plus every browser row and Twilio inbox row on
    the account inside the call's window. The browser rows carry no call
    id of their own because the SDK does not know ours.
    """
    call = call or current_handoff_call(account_id)
    rows = []
    if call is not None:
        start = (call.started_at or _now()) - timedelta(minutes=2)
        end = max(call.ended_at or _now(), _now() if not call.ended_at
                  else call.ended_at) + timedelta(minutes=3)
        for e in CallEvent.query.filter_by(call_id=call.id).all():
            rows.append(_row(e.at, "server", e.kind, e.detail, e.payload))
    else:
        start = _now() - WINDOW
        end = _now() + timedelta(minutes=1)

    acct_events = (CallEvent.query
                   .filter_by(account_id=account_id)
                   .filter(CallEvent.call_id.is_(None))
                   .filter(CallEvent.at >= start, CallEvent.at <= end).all())
    for e in acct_events:
        src = "browser" if e.kind.startswith("trace:browser") else "server"
        rows.append(_row(e.at, src, e.kind, e.detail, e.payload))

    inbox = (WebhookInbox.query
             .filter_by(account_id=account_id)
             .filter(WebhookInbox.received_at >= start,
                     WebhookInbox.received_at <= end).all())
    for w in inbox:
        rows.append(_row(w.received_at, w.source or "hook",
                         f"inbox:{w.kind}", w.dedupe_key or "", w.payload))

    rows.sort(key=lambda r: r["at"] or datetime.min)
    t0 = next((r["at"] for r in rows
               if r["kind"] in ("trace:voice_in", "handoff")), None)
    for r in rows:
        r["rel"] = ((r["at"] - t0).total_seconds()
                    if (t0 and r["at"]) else None)
    return rows


def _row(at, src, kind, detail, payload):
    return {"at": at, "src": src, "kind": kind or "", "detail": detail or "",
            "payload": payload or ""}


def as_text(rows):
    """The paste-able form."""
    out = []
    for r in rows:
        stamp = r["at"].strftime("%H:%M:%S.%f")[:-3] if r["at"] else "?"
        rel = f"{r['rel']:+8.3f}s" if r["rel"] is not None else "        "
        line = f"{stamp} {rel} [{r['src']:7}] {r['kind']:28} {r['detail']}"
        if r["payload"]:
            line += f"\n{'':32}{r['payload'][:1500]}"
        out.append(line)
    return "\n".join(out)
