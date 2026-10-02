"""Draft a playbook from a sentence about the business.

Writing one from a blank page is the step people stall on, and it is also the
step where a bad job is invisible until twenty calls have gone badly. The
model is good at the shape of a cold call; what it cannot know is the offer.
So the brief is the only thing asked for, and everything else is scaffolding.

Two rules this module holds to:

* Whatever comes back is a DRAFT in an editor, never saved and dialled
  straight away. The point is to replace a blank page, not a person's
  judgement about their own business.
* Nothing the model returns is trusted structurally. Every field is coerced
  to the shape the Playbook model and the prompt builder expect, because a
  missing key here surfaces three screens later as an agent that says
  nothing.
"""
import json

from dialer.providers import registry

MAX_STEPS = 8
MAX_QUESTIONS = 5
MAX_OBJECTIONS = 6

SYSTEM = """You write cold-call playbooks for outbound B2B phone teams.

The same playbook is read two ways: a human rep follows it live on a call,
and an AI voice agent is given it as instructions. So every line has to be
speakable out loud by either one. No stage directions, no marketing copy, no
sentence a person would be embarrassed to say to a stranger.

What a good playbook does:
- Says who is calling in the first breath.
- Gets to the offer in one sentence, not three.
- Asks the CHEAPEST DISQUALIFYING QUESTION as early as possible. If the call
  cannot end in a sale, find that out in the first thirty seconds rather than
  the eighth minute.
- Writes objection answers that concede the point before answering it.
- Says plainly when to stop selling and hand over to a person.

Style: short sentences. Contractions. No exclamation marks. No "I hope you're
having a great day". No "touch base", "circle back", "reach out", "solution",
"leverage" or "synergy". Nothing that sounds like it was written down.

Return ONLY JSON matching this shape exactly:

{
  "name": "short name, under 60 characters",
  "description": "one sentence on who this calls and what it offers",
  "steps": [
    {"title": "2-4 words",
     "say": "the actual words, one or two sentences",
     "goal": "what this step is for, under 12 words"}
  ],
  "questions": [
    {"question": "asked out loud, ends in a question mark",
     "collect_as": "snake_case_field_name",
     "disqualify_if": "the answer that means stop, or an empty string"}
  ],
  "objections": [
    {"trigger_phrases": ["what they actually say", "another phrasing"],
     "response": "the answer, two sentences at most"}
  ],
  "transfer_criteria": "one or two sentences saying exactly when to stop and hand the call to a live person",
  "never_do": "the lines that must never be said on this call"
}

Between 4 and %d steps, 2 and %d questions, 3 and %d objections.
The FIRST question must be the one that disqualifies fastest.
""" % (MAX_STEPS, MAX_QUESTIONS, MAX_OBJECTIONS)


def _text(value, limit, default=""):
    if not isinstance(value, str):
        return default
    out = " ".join(value.split()).strip()
    return out[:limit] or default


def _slug(value, fallback):
    """A field name the rest of the system can store an answer against."""
    raw = value if isinstance(value, str) else ""
    keep = [c.lower() if c.isalnum() else "_" for c in raw]
    out = "".join(keep).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return (out[:40] or fallback)


def _steps(raw):
    out = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        say = _text(item.get("say"), 400)
        if not say:
            continue                      # a step with no words is not a step
        out.append({"title": _text(item.get("title"), 60, f"Step {i + 1}"),
                    "say": say,
                    "goal": _text(item.get("goal"), 120)})
        if len(out) >= MAX_STEPS:
            break
    return out


def _questions(raw):
    out = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        q = _text(item.get("question"), 240)
        if not q:
            continue
        out.append({"question": q,
                    "collect_as": _slug(item.get("collect_as"),
                                        f"answer_{i + 1}"),
                    "disqualify_if": _text(item.get("disqualify_if"), 200)})
        if len(out) >= MAX_QUESTIONS:
            break
    return out


def _objections(raw):
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        response = _text(item.get("response"), 500)
        if not response:
            continue
        phrases = [_text(p, 80) for p in (item.get("trigger_phrases") or [])
                   if _text(p, 80)][:5]
        if not phrases:
            # The rail matches on these, so an objection nobody can trigger
            # is dead weight on the screen during a live call.
            continue
        out.append({"trigger_phrases": phrases, "response": response})
        if len(out) >= MAX_OBJECTIONS:
            break
    return out


def draft(settings, brief, company=""):
    """-> {ok, playbook: {...}} or {ok: False, error}.

    `brief` is whatever the customer typed about their business. It is passed
    through nearly untouched, because the one thing the model cannot invent
    is what they actually sell.
    """
    brief = (brief or "").strip()
    if len(brief) < 15:
        return {"ok": False,
                "error": "Tell me a bit more about the offer first. One or "
                         "two sentences on who you call and what you are "
                         "offering them is enough."}

    llm = registry.llm(settings)
    user = f"The business: {company}\n\n" if company else ""
    user += (f"What they sell and who they call:\n{brief[:2000]}\n\n"
             "Write the playbook.")

    r = llm.complete(SYSTEM, user, max_tokens=2000, json_mode=True)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or "The AI did not answer."}

    data = r.get("data")
    if not isinstance(data, dict):
        try:
            data = json.loads(r.get("text") or "")
        except (ValueError, TypeError):
            data = None
    if not isinstance(data, dict):
        return {"ok": False,
                "error": "The AI returned something we could not read. Try "
                         "again, or write the playbook by hand."}

    steps = _steps(data.get("steps"))
    if not steps:
        return {"ok": False,
                "error": "The AI came back without any script steps. Try "
                         "again with a bit more detail about the call."}

    return {"ok": True, "playbook": {
        "name": _text(data.get("name"), 120, "Draft playbook"),
        "description": _text(data.get("description"), 300),
        "steps": steps,
        "questions": _questions(data.get("questions")),
        "objections": _objections(data.get("objections")),
        "transfer_criteria": _text(data.get("transfer_criteria"), 2000),
        "never_do": _text(data.get("never_do"), 2000),
    }}
