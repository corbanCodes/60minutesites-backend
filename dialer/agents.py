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
    """The full system prompt, in the order the agent should think in."""
    pb = db.session.get(Playbook, agent.playbook_id) if agent.playbook_id else None
    out = []

    # 1. who, and the non-negotiable disclosure
    who = settings.ai_disclosure_name or "the company you work for"
    out.append(f"# Who you are\nYou are a voice assistant making calls for "
               f"{who}.")
    if settings.disclose_ai:
        out.append(
            "# Disclosure (never skip, never reword away)\n"
            f"Your FIRST words on every call must make clear that you are an "
            f"automated assistant and who you are calling for:\n"
            f"  \"{settings.effective_disclosure}\"\n"
            "If anyone asks whether you are a real person, say plainly that "
            "you are an AI assistant. Never claim to be human.")
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
                "confirm details you already have. Say one short line such as "
                "\"Perfect — let me put you straight through to a colleague, "
                "one moment\", then call the transfer tool immediately.\n"
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


def transfer_number(settings):
    """The phone a qualified call should land on, or "".

    Two modes exist. "number" is an explicit phone the owner typed. "browser"
    means whoever is on shift, which is a softphone in a browser tab and has
    no phone number of its own -- so for a warm hand-off we fall back to the
    callback number the AI already reads out, which is required to reach a
    human during business hours anyway.
    """
    if (settings.transfer_mode or "") == "number" and settings.transfer_number:
        return settings.transfer_number
    return settings.ai_callback_number or ""


def transfer_config(agent, settings):
    """The transfer_to_number system tool, or None.

    This is the gap that made the whole feature a no-op: the prompt has long
    told the agent to "use the transfer tool", and no transfer tool was ever
    given to it. The agent would say "let me put you through to a colleague"
    and then sit there, which is worse than never offering.
    """
    number = transfer_number(settings)
    if not number:
        return None
    condition = (agent.transfer_rules or "").strip()
    if not condition and agent.playbook_id:
        pb = db.session.get(Playbook, agent.playbook_id)
        condition = (pb.transfer_criteria or "").strip() if pb else ""
    if not condition:
        condition = ("When the person confirms they are the one who decides "
                     "on this, or asks about price, timing or next steps.")
    return {
        "type": "system",
        "name": "transfer_to_number",
        "description": "Hand the live call to a person on the team.",
        "params": {
            "system_tool_type": "transfer_to_number",
            "transfers": [{
                "transfer_destination": {"type": "phone",
                                         "phone_number": number},
                "condition": condition[:900],
                # Conference, so the caller hears a human arrive rather than
                # silence and a click. A blind transfer on a cold call that
                # was just qualified loses people.
                "transfer_type": "conference",
            }],
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
    if not agent.first_message and settings.disclose_ai:
        agent.first_message = settings.effective_disclosure
    if not agent.voicemail_message:
        agent.voicemail_message = voicemail_text(agent, settings)

    r = va.upsert_agent(agent, prompt, tools,
                        webhook_id=settings.elevenlabs_webhook_id or None,
                        transfer=transfer_config(agent, settings))
    if r.get("ok"):
        agent.elevenlabs_agent_id = (r.get("agent_id") or "")[:64]
        agent.synced_at = _now()
        agent.last_sync_error = ""
    else:
        agent.last_sync_error = (r.get("error") or "")[:400]
    db.session.commit()
    return r
