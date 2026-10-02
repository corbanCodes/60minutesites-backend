"""Script tracking, objection spotting and call scoring.

Two tiers, deliberately:

v1 (shipping) is free and needs no streaming infrastructure: the rail tracks
the script locally in the browser, objections are matched by phrase, and the
score arrives after the call from the transcript. That is parity with what the
category leader actually does -- Gong scores after the call too.

v1.5 (per-account opt-in) adds Twilio's real-time transcription webhooks, at
$0.027 a minute, which more than doubles the cost of a call. The same functions
below serve both: `suggest()` is called either once per utterance batch or once
at the end.
"""
import json
import re
from datetime import datetime, timezone

from app import db

from dialer.models import CoachTick, Playbook


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())


def match_objection(text, playbook):
    """Phrase match, not an LLM call. It has to land in well under a second
    while someone is mid-sentence, and it costs nothing."""
    if playbook is None:
        return None
    hay = _norm(text)
    best, best_len = None, 0
    for obj in playbook.objections:
        for phrase in obj.get("trigger_phrases", []):
            p = _norm(phrase)
            if p and p in hay and len(p) > best_len:
                best, best_len = obj, len(p)
    return best


STEP_HINTS = {
    "opening": ["hi", "hello", "this is", "calling from", "good morning"],
    "who you are": ["we supply", "we give", "what we do", "we work with"],
    "permission": ["quick question", "two questions", "got a minute",
                   "out of your hair"],
    "qualify": ["who handles", "how many", "what do you", "who supplies"],
    "close": ["put you through", "get you over to", "set it up", "next step"],
}


def detect_step(text, playbook):
    """Which script step the rep sounds like they are on."""
    if playbook is None:
        return None
    hay = _norm(text)
    for i, step in enumerate(playbook.steps):
        title = (step.get("title") or "").lower()
        hints = STEP_HINTS.get(title, [])
        said = _norm(step.get("say") or "")
        words = [w for w in said.split() if len(w) > 5][:6]
        if any(h in hay for h in hints) or sum(1 for w in words if w in hay) >= 3:
            return {"index": i, "title": step.get("title", "")}
    return None


def push(call_id, kind, body, step="", objection=""):
    """Append a suggestion the rep's rail will pick up on its next poll."""
    last = (db.session.query(db.func.max(CoachTick.seq))
            .filter(CoachTick.call_id == call_id).scalar() or 0)
    tick = CoachTick(call_id=call_id, seq=last + 1, kind=kind, body=body,
                     step=step, objection=objection)
    db.session.add(tick)
    db.session.commit()
    return tick


def suggest(call, text, playbook=None):
    """Run the cheap local checks over a chunk of live transcript."""
    if playbook is None and call.campaign_id:
        from dialer.models import Campaign
        camp = db.session.get(Campaign, call.campaign_id)
        if camp and camp.playbook_id:
            playbook = db.session.get(Playbook, camp.playbook_id)
    if playbook is None:
        playbook = Playbook.query.filter_by(account_id=call.account_id,
                                            is_default=True).first()
    out = []
    obj = match_objection(text, playbook)
    if obj:
        out.append(push(call.id, "objection", obj.get("response", ""),
                        objection=", ".join(obj.get("trigger_phrases", []))[:200]))
    step = detect_step(text, playbook)
    if step:
        out.append(push(call.id, "step", f"You're on: {step['title']}",
                        step=step["title"]))
    # Hard guard rails the rep should hear about immediately.
    hay = _norm(text)
    if any(p in hay for p in ("take me off", "stop calling", "do not call",
                              "remove me from")):
        out.append(push(call.id, "alert",
                        "They asked to be removed. Confirm it, set the outcome "
                        "to Do not call, and end the call."))
    return out


SCORE_SYSTEM = (
    "You are a sales manager reviewing one cold call. Score it honestly and "
    "briefly. A call that reached the wrong person and ended politely is not a "
    "bad call. Return strict JSON only.")


def score_call(call, settings, playbook=None):
    """Post-call scoring. Cheap, and the only tier most accounts will want."""
    from dialer.providers import registry
    if not call.transcript:
        return None
    rubric = []
    if playbook:
        rubric = [q.get("question", "") for q in playbook.questions]
    prompt = (
        "Score this call 1-10 and give at most three short reasons. Also list "
        "which of these questions were actually asked.\n"
        f"Questions that should be asked: {json.dumps(rubric)}\n\n"
        'Return {"score": N, "reasons": ["..."], "asked": ["..."], '
        '"missed": ["..."], "coaching": "one sentence of advice"}\n\n'
        f"TRANSCRIPT:\n{call.transcript[:12000]}")
    r = registry.llm(settings).complete(SCORE_SYSTEM, prompt, max_tokens=500,
                                        json_mode=True)
    if not r.get("ok") or not isinstance(r.get("data"), dict):
        return None
    d = r["data"]
    if isinstance(d.get("score"), int):
        call.score = max(1, min(d["score"], 10))
    call.coaching_json = json.dumps({
        "reasons": d.get("reasons") or [],
        "asked": d.get("asked") or [],
        "missed": d.get("missed") or [],
        "coaching": d.get("coaching") or ""})
    db.session.commit()
    return d
