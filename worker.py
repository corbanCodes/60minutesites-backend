"""Background worker for the dialer. Runs as its own Railway service.

WHY THIS IS A SEPARATE PROCESS
------------------------------
The web service answers carrier webhooks and must return in milliseconds, so
everything slow -- transcription, the LLM pass, the retry clock, the queue --
is deferred to a row in `webhook_inbox` and picked up here. Putting this loop
inside gunicorn would run it once per worker process, which double-dials.

WHY NOT RAILWAY CRON
--------------------
Railway's cron has a five-minute floor, is UTC-only, and silently skips a run
whose predecessor is still going. A power or AI campaign has to react inside a
few seconds, "the lead's local 9am" is not a UTC concept, and a skipped run
leaves `claimed` queue rows stranded until their lease expires. None of those
are survivable here, so this is a long-running process instead.

RAILWAY SETUP
-------------
  1. New service -> deploy from this same repo (same branch as the web app).
  2. Start command:        python worker.py
  3. Variables (reference the web service's, do not retype them):
        DATABASE_URL   ${{Postgres.DATABASE_URL}}   same database as web
        SECRET_KEY     ${{web.SECRET_KEY}}          must MATCH web: the AI
                                                    tool tokens are derived
                                                    from it
        FERNET_KEYS    ${{web.FERNET_KEYS}}         must MATCH web, or every
                                                    stored vendor key fails
                                                    to decrypt here
        PUBLIC_URL     ${{web.PUBLIC_URL}}          webhook URLs handed to
                                                    Twilio/ElevenLabs must
                                                    point at the WEB service
  4. Restart policy: ALWAYS. This process is expected to run forever; a crash
     loop with backoff is correct, a stopped worker is a silently dead dialer.
  5. Leave the healthcheck empty and expose no port -- it serves no HTTP.
  6. Optional: DIALER_DISABLED=1 parks the worker without a redeploy,
     DIALER_SIMULATION=1 runs it against the fake carrier.

Shutdown: Railway sends SIGTERM and then SIGKILL after the draining window.
This finishes the pass it is in and then exits, because a half-finished pass
would leave a `claimed` queue row that nobody owns until its lease runs out.

Manual use:
    python worker.py --once              one pass, then exit (also used by tests)
    python worker.py --account 7         limit every pass to one account
"""
import argparse
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

from app import app, db

# One pass every ~3s: fast enough that a rep never watches a spinner, slow
# enough that an idle account costs a handful of cheap queries a minute.
SLEEP_SECONDS = 3.0
# Housekeeping is minutes-scale work; running it every pass would be waste.
SLOW_EVERY = 60
# A heartbeat on a quiet account, so "no output" always means "not running".
HEARTBEAT_EVERY = 200
MAX_BACKOFF = 60.0
IDLE_SLEEP = 30.0

# Statuses Twilio will never move off on its own.
TRUSTHUB_SETTLED = ("twilio-approved", "approved", "business",
                    "twilio-rejected", "failed")

_stop = False
_stop_reason = ""


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def log(event, detail=""):
    """One line, greppable, never multi-line: these go to Railway's log search
    and a wrapped line is a line nobody finds again."""
    stamp = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[worker] {event}"
    if detail:
        line += " " + detail
    print(f"{line} at={stamp}", flush=True)


# ------------------------------------------------------------------ signals
def _on_signal(signum, _frame):
    global _stop, _stop_reason
    if _stop:
        return
    _stop = True
    try:
        _stop_reason = signal.Signals(signum).name
    except ValueError:
        _stop_reason = str(signum)
    log("draining", f"signal={_stop_reason} finishing=current-pass")


def _install_signals():
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass  # not the main thread; the caller owns shutdown


def _sleep(seconds):
    """Sleep in slices so a SIGTERM during the idle gap is not a 60s wait."""
    deadline = time.monotonic() + max(0.0, float(seconds))
    while not _stop and time.monotonic() < deadline:
        time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))


# -------------------------------------------------------------------- work
def one_pass(account_id=None, counter=0, force_slow=False):
    """Everything the worker owes the system once. Returns a stats dict.

    Deliberately ordered: inbox first so a campaign ticks against the freshest
    call state, leases last so a row released by this pass is available to the
    next one rather than sitting idle for three seconds.
    """
    from dialer import campaigns as campaigns_mod
    from dialer import processor
    from dialer.models import Campaign
    from dialer.settings_store import get_settings

    stats = {"inbox": 0, "inbox_failed": 0, "campaigns": 0, "dialed": 0,
             "skipped": 0, "deferred": 0, "released": 0, "slow": False}

    inbox = processor.process_all(account_id=account_id, limit=50)
    stats["inbox"] = inbox.get("processed", 0)
    stats["inbox_failed"] = inbox.get("failed", 0)
    if stats["inbox"] or stats["inbox_failed"]:
        log("inbox", f"processed={stats['inbox']} failed={stats['inbox_failed']}")

    # Power campaigns are driven by the rep's browser -- the rep IS the
    # concurrency limit, and dialing one from here would ring a prospect with
    # nobody on the line.
    q = Campaign.query.filter(Campaign.status == "running",
                              Campaign.mode.in_(["ai", "voicemail"]))
    if account_id is not None:
        q = q.filter(Campaign.account_id == account_id)
    for campaign in q.all():
        settings = get_settings(campaign.account_id, create=False)
        if settings is None:
            log("tick", f"campaign={campaign.id} skipped=no-settings")
            continue
        res = campaigns_mod.tick(campaign, settings, worker="worker")
        stats["campaigns"] += 1
        stats["dialed"] += res.get("dialed", 0)
        stats["skipped"] += res.get("skipped", 0)
        stats["deferred"] += res.get("deferred", 0)
        if any(res.get(k) for k in ("dialed", "skipped", "deferred")):
            log("tick", f"campaign={campaign.id} mode={campaign.mode} "
                        f"dialed={res.get('dialed', 0)} "
                        f"skipped={res.get('skipped', 0)} "
                        f"deferred={res.get('deferred', 0)}")

    stats["released"] = campaigns_mod.sweep_expired_leases(account_id) or 0
    if stats["released"]:
        log("leases", f"released={stats['released']}")

    if force_slow or counter % SLOW_EVERY == 0:
        stats["slow"] = True
        stats.update(slow_pass(account_id))
    return stats


def slow_pass(account_id=None):
    """Minutes-scale housekeeping: the things that fix a missed webhook, honour
    the retention promise, and chase Twilio for a verification result."""
    from dialer import processor
    out = {"reconciled": 0, "recordings_deleted": 0, "trusthub": 0}
    out["reconciled"] = processor.reconcile_stale_calls(account_id) or 0
    out["recordings_deleted"] = processor.apply_retention(account_id) or 0
    out["trusthub"] = refresh_trust_hub(account_id) or 0
    log("slow", f"reconciled={out['reconciled']} "
                f"recordings_deleted={out['recordings_deleted']} "
                f"trusthub={out['trusthub']}")
    return out


def refresh_trust_hub(account_id=None):
    """Poll Twilio for any Business Profile still in review.

    Twilio sends no webhook when a profile is approved, and an un-approved
    profile is the difference between two simultaneous calls and real
    throughput -- so the only way an account finds out is if something asks.
    """
    from dialer.models import TrustHubBundle
    from dialer.providers import registry
    from dialer.settings_store import get_settings

    q = TrustHubBundle.query.filter(
        db.or_(TrustHubBundle.status.is_(None),
               TrustHubBundle.status.notin_(TRUSTHUB_SETTLED)))
    if account_id is not None:
        q = q.filter(TrustHubBundle.account_id == account_id)
    rows = q.limit(50).all()
    if not rows:
        return 0

    checked = 0
    for bundle in rows:
        settings = get_settings(bundle.account_id, create=False)
        if settings is None:
            continue
        try:
            r = registry.telephony(settings).customer_profiles()
        except Exception as e:                      # a vendor outage is not
            r = {"ok": False, "error": str(e)[:300]}  # a reason to stop
        bundle.last_checked_at = _now()
        bundle.next_check_at = _now() + timedelta(hours=6)
        if r.get("ok"):
            bundle.status = str(r.get("status") or bundle.status or "")[:24]
            bundle.failure_json = ""
            if bundle.kind in ("", "pcp", None):
                settings.twilio_pcp_status = bundle.status or "none"
                settings.twilio_pcp_checked_at = _now()
        else:
            bundle.failure_json = json.dumps({"error": r.get("error", "")})
        checked += 1
    db.session.commit()
    return checked


# -------------------------------------------------------------------- loop
def run_forever(account_id=None):
    from dialer import disabled

    failures = 0
    passes = 0
    idled = False
    while not _stop:
        if disabled():
            if not idled:
                log("disabled", "reason=DIALER_DISABLED work=none "
                                f"sleeping={int(IDLE_SLEEP)}s")
                idled = True
            _sleep(IDLE_SLEEP)
            continue
        if idled:
            log("resumed", "reason=DIALER_DISABLED-cleared")
            idled = False

        began = time.monotonic()
        try:
            stats = one_pass(account_id, passes)
            failures = 0
            busy = (stats["inbox"] or stats["dialed"] or stats["skipped"]
                    or stats["deferred"] or stats["released"])
            if busy:
                log("pass", f"n={passes} ms={int((time.monotonic() - began) * 1000)} "
                            f"campaigns={stats['campaigns']} "
                            f"dialed={stats['dialed']} inbox={stats['inbox']}")
            elif passes % HEARTBEAT_EVERY == 0:
                log("heartbeat", f"n={passes} idle=true")
        except Exception:
            # A single bad row must never take the dialer down for everybody.
            failures += 1
            try:
                db.session.rollback()
            except Exception:
                pass
            log("error", f"pass={passes} consecutive_failures={failures}")
            traceback.print_exc()
        finally:
            db.session.remove()

        passes += 1
        if failures:
            delay = min(MAX_BACKOFF, SLEEP_SECONDS * (2 ** failures))
            log("backoff", f"seconds={delay:.0f} failures={failures}")
        else:
            delay = SLEEP_SECONDS
        _sleep(delay)
    return passes


# --------------------------------------------------------------------- cli
def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="worker.py", description="60MS dialer background worker.")
    p.add_argument("--once", action="store_true",
                   help="run a single pass (including housekeeping) and exit")
    p.add_argument("--account", type=int, default=None, metavar="ID",
                   help="limit the pass to one account id")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    _install_signals()
    log("start", f"once={bool(args.once)} "
                 f"account={args.account if args.account is not None else 'all'} "
                 f"pid={os.getpid()} sleep={SLEEP_SECONDS}s")

    with app.app_context():
        from dialer import disabled
        if args.once:
            if disabled():
                log("disabled", "reason=DIALER_DISABLED work=none")
                log("stop", "passes=0 reason=once")
                return 0
            try:
                stats = one_pass(args.account, counter=0, force_slow=True)
            except Exception:
                log("error", "pass=0 fatal=true")
                traceback.print_exc()
                return 1
            finally:
                db.session.remove()
            log("stop", f"passes=1 reason=once inbox={stats['inbox']} "
                        f"campaigns={stats['campaigns']} "
                        f"dialed={stats['dialed']}")
            return 0

        passes = run_forever(args.account)
    log("stop", f"passes={passes} reason={_stop_reason or 'loop-exit'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
