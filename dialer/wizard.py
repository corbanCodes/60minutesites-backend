"""The eleven-step setup interview.

Two rules, both learned from how Stripe does onboarding:
  1. A step is complete because we just called the vendor and it worked, never
     because someone clicked Next. A key revoked last week turns its step amber
     on its own.
  2. Progress is saved per account, so you can leave halfway and come back.
"""
from datetime import datetime, timedelta, timezone

STEPS = [
    {"n": 1, "key": "intent", "title": "What do you want to do?",
     "icon": "bi-signpost-split", "mins": 1,
     "why": "This only sets sensible defaults for the rest of the setup. "
            "Nothing is locked in — you can turn any lane on later.",
     "skippable": True},
    {"n": 2, "key": "twilio", "title": "Connect your phone account (Twilio)",
     "icon": "bi-telephone-plus", "mins": 3,
     "why": "Twilio is the phone company underneath. It's your account and "
            "your bill, so you keep your numbers and we never mark up a minute. "
            "A connected US call costs about 1.4 cents a minute.",
     "skippable": False},
    {"n": 3, "key": "business", "title": "Verify your business with Twilio",
     "icon": "bi-patch-check", "mins": 10,
     "why": "Until Twilio has approved your business, they cap you at roughly "
            "two calls at once and one call per second, and your number is far "
            "more likely to show up as “Spam Likely”. Approval takes up to 48 "
            "hours, so start it early. You do this on Twilio's own site.",
     "skippable": True},
    {"n": 4, "key": "numbers", "title": "Get your phone numbers",
     "icon": "bi-123", "mins": 3,
     "why": "People answer local numbers. One number per hundred-odd calls a "
            "day keeps any single one from getting flagged. $1.15 a month each.",
     "skippable": False},
    {"n": 5, "key": "llm", "title": "Add an AI key for transcripts & scoring",
     "icon": "bi-stars", "mins": 2,
     "why": "This is what writes the call summary, scores the rep, pulls out "
            "the answers and creates the follow-up task. It costs well under a "
            "cent per call. Calls still work without it — you just get audio "
            "instead of a transcript.",
     "skippable": True},
    {"n": 6, "key": "elevenlabs", "title": "Connect the AI voice (ElevenLabs)",
     "icon": "bi-soundwave", "mins": 3,
     "why": "Only needed if you want the AI to talk to people. Eight cents a "
            "minute on every plan — the plan you buy decides how many calls can "
            "run at once, not the price.",
     "skippable": True},
    {"n": 7, "key": "compliance", "title": "Recording, disclosure & calling hours",
     "icon": "bi-shield-check", "mins": 4,
     "why": "The rules the system will hold you to. Defaults are the cautious "
            "ones; you can change them, and changes are logged.",
     "skippable": False},
    {"n": 8, "key": "voice", "title": "Voice & call behaviour",
     "icon": "bi-sliders", "mins": 2,
     "why": "Pick the AI's voice, cap how long a call can run, and decide where "
            "a hot lead gets transferred.",
     "skippable": True},
    {"n": 9, "key": "playbook", "title": "Your script, questions & objections",
     "icon": "bi-journal-text", "mins": 8,
     "why": "One playbook feeds both sides: it's the rail your reps read on a "
            "live call, and it's what the AI is told to ask.",
     "skippable": False},
    {"n": 10, "key": "voicemail", "title": "Record your voicemail drop",
     "icon": "bi-voicemail", "mins": 3,
     "why": "Record it once. From then on a rep hears the beep, clicks one "
            "button and is already dialling the next number.",
     "skippable": True},
    {"n": 11, "key": "test", "title": "Make a test call",
     "icon": "bi-telephone-outbound", "mins": 2,
     "why": "Proves the whole chain works before you point it at a real list.",
     "skippable": True},
]
BY_KEY = {s["key"]: s for s in STEPS}
BY_N = {s["n"]: s for s in STEPS}

# A step counts as done only if its live probe succeeded this recently.
PROBE_MAX_AGE_DAYS = 30


def _fresh(stamp, days=PROBE_MAX_AGE_DAYS):
    if not stamp:
        return False
    return (datetime.now(timezone.utc).replace(tzinfo=None) - stamp) \
        < timedelta(days=days)


def status(settings, account_id):
    """-> {key: 'done'|'todo'|'skipped'|'stale'} derived from reality, with the
    saved wizard state only used for 'skipped' and for free-text steps."""
    from dialer.models import AiAgent, PhoneNumber, Playbook, VoicemailDrop
    from dialer.providers import registry
    saved = settings.wizard if settings else {}
    sim = registry.simulating(settings)
    out = {}

    def mark(key, done, stale=False):
        if done:
            out[key] = "stale" if stale else "done"
        elif saved.get(key, {}).get("skipped"):
            out[key] = "skipped"
        else:
            out[key] = "todo"

    mark("intent", bool(settings.intent))
    mark("twilio", bool(settings.has_twilio) or sim,
         stale=bool(settings.twilio_verified_at)
         and not _fresh(settings.twilio_verified_at))
    mark("business", settings.twilio_pcp_status == "business" or sim)
    mark("numbers", PhoneNumber.query.filter_by(
        account_id=account_id, state="active").count() > 0 or sim)
    mark("llm", bool(settings.has_llm) or sim)
    mark("elevenlabs", bool(settings.has_elevenlabs) or sim)
    mark("compliance", bool(saved.get("compliance", {}).get("done")))
    mark("voice", bool(saved.get("voice", {}).get("done")))
    mark("playbook", Playbook.query.filter_by(account_id=account_id).count() > 0)
    mark("voicemail", VoicemailDrop.query.filter_by(
        account_id=account_id).count() > 0)
    mark("test", bool(saved.get("test", {}).get("done")))
    return out


REQUIRED = ["twilio", "numbers", "compliance", "playbook"]


def progress(settings, account_id):
    st = status(settings, account_id)
    done = sum(1 for v in st.values() if v == "done")
    required_left = [BY_KEY[k] for k in REQUIRED if st.get(k) != "done"]
    return {"status": st, "done": done, "total": len(STEPS),
            "pct": round(100 * done / len(STEPS)),
            "required_left": required_left,
            "complete": not required_left,
            "next": next((s for s in STEPS if st.get(s["key"]) == "todo"), None)}


def mark(settings, key, **fields):
    """Persist free-text progress (skipped / done / a note)."""
    state = settings.wizard
    entry = state.get(key, {})
    entry.update(fields)
    entry["at"] = datetime.now(timezone.utc).isoformat()
    state[key] = entry
    settings.set_wizard(state)
    return entry
