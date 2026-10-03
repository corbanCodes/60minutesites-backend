"""Turning a playbook into an AI agent.

The disclosure is assembled as a LOCKED prefix: the operator can edit their
company name and callback number, but cannot delete the sentence that says a
machine is calling. That is a product decision, not a legal one -- an
undisclosed synthetic voice is the thing that gets a number blocked, a brand
burned, and a customer into an argument they cannot win.
"""
import json
from datetime import datetime, timezone

from app import db

from dialer.models import AiAgent, Playbook
from dialer.providers import registry


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_prompt(agent, settings):
    """The full system prompt, in the order the agent should think in.

    A hand-written override replaces all of this. It is your product and
    there is no good reason the generated version should be the only one you
    are allowed. Two short blocks are still appended after it, and both are
    mechanics rather than content: the disclosure rule, only while the step
    7 switch is on, and how to drive the transfer tool, only when there is
    somewhere to transfer to.

    The second one is appended because of what overrides are made from in
    practice. People copy the generated prompt out, edit the wording, and
    paste it back -- which freezes whatever the tool instructions said on
    the day they copied. One such copy carried "say this, THEN call the
    transfer tool", an instruction that cannot be obeyed, and no later fix
    could reach that agent. What it says is the customer's; how the tool is
    called is not a style choice.
    """
    override = (getattr(agent, "prompt_override", "") or "").strip()
    if override:
        out = [override]
        mech = _transfer_mechanics(agent, settings)
        if mech:
            out.append(mech)
        if settings.disclose_ai:
            out.append(_disclosure_block(settings))
        return _fill(agent, settings, "\n\n".join(out))
    return _fill(agent, settings, _generated_prompt(agent, settings))


def _fill(agent, settings, text):
    """Resolve {ai_name} and {company} in the finished prompt.

    Done here, at the very end, rather than when a script is saved. Baking
    a name into the stored row froze it: renaming the AI left every
    existing script saying the old name. The agent's own name wins over the
    account's, so one account can run "John" on venues and "Sam" on retail.

    ElevenLabs' own {{double brace}} variables are untouched -- these are
    single braces and the names do not overlap.
    """
    from dialer import napkin
    person = (getattr(agent, "person_name", "") or "").strip()
    if person:
        class _Local:
            ai_person_name = person
            ai_disclosure_name = getattr(settings, "ai_disclosure_name", "")
        return napkin.fill(text, _Local)
    return napkin.fill(text, settings)


def _transfer_mechanics(agent, settings):
    """How to drive the transfer tool, for a prompt we did not write."""
    if not transfer_number(settings, agent):
        return ""
    return ("# How the hand-off actually works (mechanics, not wording)\n"
            + transfer_intro(agent))


def _disclosure_block(settings):
    return (
        "# Disclosure (never skip, never reword away)\n"
        f"Your FIRST words on every call must make clear that you are an "
        f"automated assistant and who you are calling for:\n"
        f"  \"{settings.effective_disclosure}\"\n"
        "If anyone asks whether you are a real person, say plainly that "
        "you are an AI assistant. Never claim to be human.")


def _generated_prompt(agent, settings):
    pb = db.session.get(Playbook, agent.playbook_id) if agent.playbook_id else None
    out = []

    # 1. who, and the non-negotiable disclosure
    who = settings.ai_disclosure_name or "the company you work for"
    out.append(f"# Who you are\nYou are a voice assistant making calls for "
               f"{who}.")
    if settings.disclose_ai:
        out.append(_disclosure_block(settings))
    if (getattr(agent, "opening_mode", "") or "wait") == "wait":
        block = (
            "# Who speaks first\n"
            "Say NOTHING when the call connects. Wait for them to speak. "
            "People answer a phone with \"hello\" and talking over that is "
            "the clearest sign of a machine.")
        line = (getattr(agent, "first_message", "") or "").strip()
        if line:
            # Waiting and having an opening line are not in conflict, whatever
            # ElevenLabs' first_message field implies. The line simply belongs
            # AFTER they speak, which is a prompt instruction rather than a
            # field that fires the instant the call connects.
            block += ("\nOnce they have spoken, greet them back briefly and "
                      "then say this, in these words:\n"
                      f"  \"{line}\"")
        else:
            block += (" When they have spoken, greet them back naturally and "
                      "only then begin.")
        out.append(block)
    if settings.records_calls and settings.announce_recording:
        out.append(f"# Recording\nSay this early, before anything substantive: "
                   f"\"{settings.announce_text}\"")

    # 2. the business
    if agent.company_facts:
        out.append(f"# What {who} does\n{agent.company_facts}")
    if agent.persona:
        out.append(f"# How to come across\n{agent.persona}")
    else:
        out.append("# How to come across\nWarm, brief and unbothered. You are "
                   "qualifying, not selling. Short sentences. Let them talk. "
                   "A bad fit should cost three minutes, not thirty.")

    # 3. the call itself
    if pb:
        if pb.steps:
            lines = [f"{i + 1}. {s.get('title', '')} — {s.get('say', '')}"
                     + (f" (goal: {s['goal']})" if s.get("goal") else "")
                     for i, s in enumerate(pb.steps)]
            out.append("# How the call goes\n" + "\n".join(lines))
        if pb.questions:
            lines = []
            for i, q in enumerate(pb.questions):
                line = f"{i + 1}. {q.get('question', '')}"
                if q.get("collect_as"):
                    line += f"  [record this as: {q['collect_as']}]"
                if q.get("disqualify_if"):
                    line += f"  [if {q['disqualify_if']}, politely end the call]"
                lines.append(line)
            out.append("# Questions to get answered, in this order\n"
                       "Ask the cheapest disqualifying question first. Do not "
                       "read them like a form.\n" + "\n".join(lines))
        if pb.objections:
            lines = [f'- If they say something like "{", ".join(o.get("trigger_phrases", []))}": '
                     f'{o.get("response", "")}' for o in pb.objections]
            out.append("# When they push back\n" + "\n".join(lines))
        if pb.transfer_criteria:
            out.append(
                "# Handing the call to a person — your most important job\n"
                f"{pb.transfer_criteria}\n"
                "The moment that is true, STOP SELLING. Do not ask another "
                "qualifying question, do not explain the offer again, do not "
                "confirm details you already have.\n"
                f"{transfer_intro(agent)}\n"
                "Every extra sentence after they qualify is a chance to lose "
                "them. Transferring a second too early costs nothing; a second "
                "too late costs the call.\n"
                "If the transfer does not connect, apologise once, get the "
                "best time to call back, and book it.")
        if pb.never_do:
            out.append(f"# Never\n{pb.never_do}")
    if agent.transfer_rules:
        out.append(f"# Extra transfer rules\n{agent.transfer_rules}")
    if agent.knowledge_text:
        out.append(f"# Background you can draw on\n{agent.knowledge_text}")

    # 4. CRM context the platform injects per call
    out.append(
        "# What you already know about this person\n"
        "name: {{lead_name}} · business: {{business}} ({{business_type}}) · "
        "state: {{state}} · previous calls: {{prior_calls}} · "
        "current stage: {{lead_status}}\n"
        "Last note on file: {{last_note}}\n"
        "If {{is_known}} is false, this is a first contact — do not pretend to "
        "remember them.")

    # 5. ending well
    mins = max(1, int((agent.max_duration_seconds or 420) / 60))
    out.append(
        "# Ending the call\n"
        f"- Keep it under about {mins} minutes. If it is going nowhere, thank "
        "them and end it.\n"
        "- If they ask to be taken off the list, in ANY wording: say \"of "
        "course, I'll take care of that now\", call set_disposition with "
        "dnc, and end the call. Do not argue, do not pitch again.\n"
        "- If you reach a voicemail, "
        + ("leave the short message you were given and hang up."
           if agent.voicemail_behavior == "leave_tts" else "hang up without "
           "leaving a message.") + "\n"
        "- If someone is wasting your time or playing games, end the call "
        "politely rather than staying on it.\n"
        "- Before you finish, use log_note to record anything useful you "
        "learned, and set_disposition to record the outcome.")

    # 6. the callback, which is the second-best outcome and usually the one
    out.append(
        "# When they cannot talk now\n"
        "This is the second-best outcome and it happens more than anything "
        "else, so treat it as a result rather than a failure.\n"
        "- Ask for a better time, out loud and specifically: \"When would be "
        "a better time to catch you — is the morning or the afternoon "
        "easier?\" A day and a rough time is enough. Do not accept a vague "
        "\"later\" without one follow-up attempt at pinning it down.\n"
        "- If they are not the right person at all, get the name of whoever "
        "is and when they are usually around. That is worth more than the "
        "call you were trying to have.\n"
        "- Say the time back to them so it is confirmed: \"Thursday morning, "
        "got it.\"\n"
        "- Then record it with log_note, in plain words including the day and "
        "time they said, set_disposition to callback, and END THE CALL. Do "
        "not keep talking once you have the time; you already have what you "
        "came for.")
    return "\n\n".join(out)


def resync_for_playbook(playbook_id, settings):
    """Push every agent that reads this playbook back to ElevenLabs.

    The prompt is assembled at sync time and then lives at ElevenLabs. So
    editing a script changed what reps read on screen and left the AI saying
    the old words until somebody happened to re-sync the agent by hand.
    Step 9 promises in so many words that "write it once and both sides stay
    in step"; this is the line that makes that true.

    Returns (synced, failures).
    """
    if not playbook_id:
        return 0, []
    agents = AiAgent.query.filter_by(playbook_id=playbook_id).all()
    ok_count, failed = 0, []
    for agent in agents:
        if not agent.elevenlabs_agent_id:
            continue          # never synced; building it is a separate act
        r = sync_agent(agent, settings)
        if r.get("ok"):
            ok_count += 1
        else:
            failed.append(agent.name)
    return ok_count, failed


def resync_all(account_id, settings):
    """Every synced agent on the account. Used when something global
    changes -- the disclosure, the voice, the transfer number -- because all
    three are baked into the prompt or the agent config at sync time."""
    agents = AiAgent.query.filter_by(account_id=account_id).all()
    ok_count, failed = 0, []
    for agent in agents:
        if not agent.elevenlabs_agent_id:
            continue
        r = sync_agent(agent, settings)
        if r.get("ok"):
            ok_count += 1
        else:
            failed.append(agent.name)
    return ok_count, failed


TRANSFER_STYLES = {
    "brief": {
        "label": "One short line, then go",
        "hint": "Fastest. The prospect barely registers a pause.",
        "line": "Perfect \u2014 one second.",
    },
    "explicit": {
        "label": "Say plainly that a person is coming on",
        "hint": "Slower, but nobody is surprised by the new voice.",
        "line": "That's great \u2014 I'm going to put you through to a "
                "colleague. One moment.",
    },
    "natural": {
        "label": "A natural aside, like a person would",
        "hint": "Sounds least like a machine. Worth a second of delay.",
        "line": "Oh great \u2014 sorry, can you give me one second?",
    },
    "custom": {
        "label": "My own line",
        "hint": "Write exactly what it says before handing over.",
        "line": "",
    },
}


def transfer_say(agent):
    """The literal words spoken as the hand-off fires.

    These used to be descriptions aimed at the model -- "say one short line
    and transfer immediately" -- which left the model free to compose its
    own. It reliably composed corporate filler: "I'm going to connect you
    with one of our team members now." The words are a literal string now
    because they are handed to the tool, not described to a writer.
    """
    style = (getattr(agent, "transfer_style", "") or "brief").lower()
    if style == "custom":
        line = (getattr(agent, "transfer_line", "") or "").strip()
        if line:
            return line
        style = "brief"
    return TRANSFER_STYLES.get(style, TRANSFER_STYLES["brief"])["line"]


def transfer_intro(agent):
    """How to hand over in ONE turn.

    This used to read "say exactly this, then transfer immediately", and
    that instruction cannot be obeyed. Speaking ends the model's turn, so
    the tool call lands in the NEXT turn -- which only arrives when the
    other person says something else. The observed behaviour was an agent
    that announced the transfer and then sat there until the prospect spoke
    again, which reads as the transfer being broken.

    The tool takes the spoken line as its own client_message parameter, so
    the words and the hand-off go together in a single turn. Nothing is
    said first.
    """
    line = transfer_say(agent)
    return ("Do NOT say anything first and do NOT wait for a reply. Call the "
            "transfer_to_number tool straight away, in the same turn, and "
            f"pass exactly this as its client_message: \"{line}\"\n"
            "Speaking before you call the tool ends your turn, and the "
            "hand-off then waits for them to talk again. That delay loses "
            "the call. The tool speaks the line for you.")


def transfer_number(settings, agent=None):
    """The phone a qualified call should land on, or "".

    An agent's own number wins. One account can run a restaurant campaign
    that rings the bar team and a retail one that rings somebody else, and
    forcing both through a single account-wide setting is why "where does
    it transfer" had no satisfying answer.

    Two modes exist. "number" is an explicit phone the owner typed. "browser"
    means whoever is on shift, which is a softphone in a browser tab and has
    no phone number of its own -- so for a warm hand-off we fall back to the
    callback number the AI already reads out, which is required to reach a
    human during business hours anyway.
    """
    own = (getattr(agent, "transfer_to_number", "") or "").strip()
    if own:
        return own
    if (settings.transfer_mode or "") == "number" and settings.transfer_number:
        return settings.transfer_number
    return settings.ai_callback_number or ""


DELIVERIES = {
    "calm": {
        "label": "Calm \u2014 like a routine work call",
        "hint": "Flat and unbothered. Use this for cold calls: the job is "
                "to sound like someone who rings twenty venues a day, not "
                "someone delighted to be on the phone.",
        "tts": {"stability": 0.75, "speed": 1.0, "expressive_mode": False},
    },
    "natural": {
        "label": "Natural",
        "hint": "ElevenLabs' own defaults. Some warmth and variation.",
        "tts": {"stability": 0.5, "speed": 1.0, "expressive_mode": True},
    },
    "lively": {
        "label": "Lively",
        "hint": "Bright and animated. Good for a warm inbound line, far "
                "too much for a cold call.",
        "tts": {"stability": 0.35, "speed": 1.05, "expressive_mode": True},
    },
}


def delivery_tts(agent):
    """Prosody settings for the voice.

    We sent nothing but a voice_id, so every agent ran on ElevenLabs'
    defaults. The lever that definitely works is stability: higher is
    flatter and more consistent. expressive_mode is "automatically disabled
    for non-v3 models" per their spec, so with the TTS model pinned to v4
    turbo its effect is undocumented; it is sent anyway because it is a
    documented boolean and harmless. Do not credit it for the change.
    """
    want = (getattr(agent, "voice_delivery", "") or "calm").strip()
    return DELIVERIES.get(want, DELIVERIES["calm"])["tts"]


HANDOFFS = {
    "blind": {
        "label": "Straight through \u2014 no hold music",
        "hint": "The leg is handed over as it is: a normal ring, your "
                "caller ID preserved, and the AI gone the instant it fires. "
                "Two things ElevenLabs does NOT document for blind: whether "
                "the spoken line plays at all, and the colleague never gets "
                "a hand-off summary. If nobody picks up they reach that "
                "phone's voicemail and the AI cannot come back.",
    },
    "conference": {
        "label": "Park them while it rings you",
        "hint": "The prospect waits in a conference room while your phone is "
                "dialled. Twilio plays its own classical hold music during "
                "the wait and there is no way to change or silence it.",
    },
}


def handoff_type(agent):
    """Which of ElevenLabs' three transfer types to ask for.

    Conference was the old hard-coded choice and it is the reason a hand-off
    sounded like being put on hold: an unconfigured Twilio conference plays
    the default classical playlist while the destination is dialled, and the
    conference belongs to ElevenLabs, so waitUrl is not ours to set.

    sip_refer is deliberately not offered. It needs a SIP trunk that permits
    REFER, and every number here arrives through the native Twilio
    integration, so asking for it would fail on every account we have.
    """
    want = (getattr(agent, "transfer_handoff", "") or "blind").strip()
    return want if want in HANDOFFS else "blind"


def transfer_collides(agent, settings, to_number):
    """True when the hand-off would dial the phone already on the call.

    On a one-person account the hand-off destination falls back to the
    callback number, which is that person's mobile -- the same mobile they
    answer the test call on. The transfer then dials a line that is busy by
    definition, the carrier rolls it to voicemail, and the prospect sits
    listening to hold music until the AI bridges them to the voicemail
    greeting of the man who is already on the phone.

    Nothing in that chain reports an error. It is a working transfer to an
    impossible destination, so it has to be caught before the call is placed.
    """
    from dialer import compliance
    dest = transfer_number(settings, agent)
    if not dest or not to_number:
        return False
    _, a, ok_a = compliance.normalize(dest)
    _, b, ok_b = compliance.normalize(to_number)
    return bool(ok_a and ok_b and a == b)


def transfer_config(agent, settings):
    """The transfer_to_number system tool, or None.

    This is the gap that made the whole feature a no-op: the prompt has long
    told the agent to "use the transfer tool", and no transfer tool was ever
    given to it. The agent would say "let me put you through to a colleague"
    and then sit there, which is worse than never offering.
    """
    number = transfer_number(settings, agent)
    if not number:
        return None
    condition = (agent.transfer_rules or "").strip()
    if not condition and agent.playbook_id:
        pb = db.session.get(Playbook, agent.playbook_id)
        condition = (pb.transfer_criteria or "").strip() if pb else ""
    if not condition:
        condition = ("When the person confirms they are the one who decides "
                     "on this, or asks about price, timing or next steps.")
    # client_message and agent_message are LLM-supplied runtime parameters,
    # not config, so the ONLY place to pin the wording is the description the
    # model reads when it decides to call this. Left vague ("hand the live
    # call to a person on the team") it invents the line itself, and what it
    # invents is "I'm going to connect you with one of our team members now."
    line = transfer_say(agent)
    return {
        "type": "system",
        "name": "transfer_to_number",
        "description": (
            "Hand the live call straight to a person on the team. Call this "
            "the instant you are speaking to a decision maker, in the same "
            "turn, without saying anything first.\n"
            f"For client_message pass exactly: \"{line}\" \u2014 use those "
            "words verbatim. Do NOT write your own. Never say \"let me "
            "connect you\", \"one of our team members\", \"someone who can "
            "help\" or anything else that sounds like a call centre.\n"
            "For agent_message give the colleague one plain sentence naming "
            "the venue and who is on the line."),
        "params": {
            "system_tool_type": "transfer_to_number",
            "transfers": [{
                "transfer_destination": {"type": "phone",
                                         "phone_number": number},
                "condition": condition[:900],
                "transfer_type": handoff_type(agent),
            }],
            # Documented default is true; sent explicitly because the line
            # the tool speaks is the whole of what the prospect hears.
            "enable_client_message": True,
        },
    }


def voicemail_text(agent, settings):
    """47 CFR 64.1200(b) wants the caller identified at the START of a
    recorded message and a callback number given -- so the template enforces
    both rather than trusting a free-text box."""
    if agent.voicemail_message:
        return agent.voicemail_message
    who = settings.ai_disclosure_name or "our team"
    num = settings.ai_callback_number
    msg = f"Hi, this is an automated message from {who}. "
    msg += ("We supply bars and restaurants with free napkins and wanted to "
            "see if you'd like some. ")
    if num:
        msg += f"Give us a call back on {num} and a person will pick up. "
    msg += "Thanks for your time."
    return msg


# Stored LLM ids that are no longer members of ElevenLabs' enum, mapped to
# what they meant. "claude-3-5-haiku" was in our own dropdown and is not a
# valid id, so an agent that picked it 422'd on every sync from then on.
LLM_RENAMES = {"claude-3-5-haiku": "claude-haiku-4-5",
               "claude-sonnet-4": "claude-sonnet-4-5"}


def normalise_llm(value):
    """The id to send, or "" to let the vendor default (gemini-2.5-flash)."""
    v = (value or "").strip()
    return LLM_RENAMES.get(v, v)


def sync_agent(agent, settings):
    """Create or update the agent at the vendor. Idempotent."""
    va = registry.voice_agent(settings)
    prompt = build_prompt(agent, settings)
    from dialer.tools import TOOL_SPECS, account_token
    from dialer import urls

    tools = []
    for spec in TOOL_SPECS:
        tools.append({
            "type": "webhook", "name": spec["name"],
            "description": spec["description"],
            "api_schema": {
                "url": urls.elevenlabs_tool(spec["name"]), "method": "POST",
                "request_headers": {
                    "X-HQ-Token": account_token(agent.account_id)},
                "request_body_schema": spec["parameters"]},
        })
    # ElevenLabs SPEAKS first_message verbatim the instant the call
    # connects, instructions and all. Leaving it empty is the documented way
    # to make an agent wait for the other person, so "wait" must not be
    # helpfully filled in.
    # ElevenLabs fires first_message the instant the line opens, so it has
    # to be empty THERE for the agent to wait. What the owner typed is NOT
    # discarded: it stays on the record and build_prompt carries it in as
    # the line to say once the other person has spoken. Waiting and having
    # an opening line were never actually in conflict.
    waiting = (agent.opening_mode or "wait") == "wait"
    if not waiting and not agent.first_message and settings.disclose_ai:
        agent.first_message = settings.effective_disclosure
    opening_for_vendor = "" if waiting else (agent.first_message or "")
    if not agent.voicemail_message:
        agent.voicemail_message = voicemail_text(agent, settings)

    created = not (agent.elevenlabs_agent_id or "").strip()
    kwargs = dict(webhook_id=settings.elevenlabs_webhook_id or None,
                  transfer=transfer_config(agent, settings),
                  first_message=opening_for_vendor)
    r = va.upsert_agent(agent, prompt, tools, **kwargs)
    if r.get("ok"):
        agent.elevenlabs_agent_id = (r.get("agent_id") or "")[:64]
        if created and agent.elevenlabs_agent_id:
            # A create has to carry the webhook tools, and the only place
            # they can go on a create is the deprecated `tools` array --
            # which ElevenLabs rebuilds the WHOLE tool set from, so a
            # brand-new agent can come back with built_in_tools empty and
            # no way to hand over until somebody happens to save it again.
            # One follow-up update, which sends no `tools`, lands the
            # transfer tool. It costs one request and only ever runs once.
            r2 = va.upsert_agent(agent, prompt, tools, **kwargs)
            if not r2.get("ok"):
                r = r2
    if r.get("ok"):
        agent.synced_at = _now()
        agent.last_sync_error = ""
    else:
        agent.last_sync_error = (r.get("error") or "")[:400]
    db.session.commit()
    return r
