"""What works right now, and what is blocking the rest.

Every dialer page runs this. The rule the product promises: when something will
not work, say exactly which thing is missing and link to the step that fixes
it -- never fail silently, never show a dead button.
"""
from dialer.models import AiAgent, PhoneNumber, Playbook, VoicemailDrop
from dialer.providers import registry


def _blocker(feature, needs, step, fix, severity="blocker"):
    return {"feature": feature, "needs": needs, "step": step, "fix": fix,
            "severity": severity}


def check(settings, account_id):
    """-> {ok, blockers, warnings, lanes:{lane: bool}, simulating}"""
    sim = registry.simulating(settings)
    blockers, warnings = [], []

    numbers = PhoneNumber.query.filter_by(account_id=account_id,
                                          state="active").all()
    rep_numbers = [n for n in numbers if n.pool == "rep"]
    ai_numbers = [n for n in numbers if n.pool == "ai"]
    playbooks = Playbook.query.filter_by(account_id=account_id).count()
    agents = AiAgent.query.filter_by(account_id=account_id, active=True).all()
    drops = VoicemailDrop.query.filter_by(account_id=account_id).count()

    # ---- Twilio: everything depends on it
    if not settings.has_twilio and not sim:
        blockers.append(_blocker(
            "Calling", "your Twilio account",
            2, "Nothing can dial until Twilio is connected — Setup step 2 "
               "(about 3 minutes)."))
    elif settings.twilio_is_trial:
        warnings.append(_blocker(
            "Calling", "a paid Twilio account", 2,
            "Your Twilio account is still a trial, so it can only call numbers "
            "you've verified by hand. Add $20 of credit to lift that.",
            "warning"))

    # ---- Business Profile: the throughput gate
    if settings.twilio_pcp_status == "business":
        pass
    elif settings.twilio_pcp_status in ("none", "", None) and not sim:
        warnings.append(_blocker(
            "Calling", "Twilio business verification", 3,
            "Without an approved Business Profile, Twilio caps you at about "
            "2 calls at once and 1 call per second, and your calls are more "
            "likely to show as “Spam Likely”. It takes about 48 hours, so "
            "start it now — Setup step 3.", "warning"))
    elif settings.twilio_pcp_status == "individual":
        warnings.append(_blocker(
            "Calling", "a BUSINESS Twilio profile", 3,
            "You have an Individual profile approved. That's a dead end for a "
            "dialer: 3 calls at once, 1 per second, and no way to raise it. "
            "Re-register as a business.", "warning"))
    elif settings.twilio_pcp_status == "pending":
        warnings.append(_blocker(
            "Calling", "Twilio business verification", 3,
            "Twilio is still reviewing your Business Profile. Until it's "
            "approved you're capped at about 2 simultaneous calls.", "warning"))

    # ---- numbers
    if not numbers and not sim:
        blockers.append(_blocker(
            "Calling", "a phone number", 4,
            "You need at least one phone number to call from — Setup step 4."))
    elif not rep_numbers and not sim:
        warnings.append(_blocker(
            "Human dialing", "a number in the rep pool", 4,
            "All your numbers are assigned to the AI. Add one for your reps so "
            "callbacks reach a person.", "warning"))

    # ---- the AI stack
    ai_ready = True
    if not settings.has_elevenlabs and not sim:
        ai_ready = False
        blockers.append(_blocker(
            "AI calling", "your ElevenLabs API key", 6,
            "AI calling will not work until your ElevenLabs API key is added — "
            "Setup step 6 (2 minutes). Human dialing works without it."))
    if settings.ai_disclosure_enabled and not (settings.ai_disclosure_name
                                               or settings.ai_disclosure_text):
        ai_ready = False
        blockers.append(_blocker(
            "AI calling", "your company name for the AI to say", 7,
            "The AI has to say who's calling and give a callback number. Fill "
            "those in — Setup step 7."))
    if not agents and settings.has_elevenlabs:
        warnings.append(_blocker(
            "AI calling", "an AI agent", 9,
            "You've connected ElevenLabs but haven't built an agent yet.",
            "warning"))
    if agents and not ai_numbers and not sim:
        warnings.append(_blocker(
            "AI calling", "a number in the AI pool", 4,
            "Your AI agent has no number to call from.", "warning"))

    # ---- transcripts and scoring
    if not settings.has_llm and not sim:
        warnings.append(_blocker(
            "Call transcripts & scoring", "an OpenAI key", 5,
            "Calls will still connect and record, but you won't get "
            "transcripts, summaries, coaching scores or automatic follow-up "
            "tasks until you add an OpenAI key — Setup step 5.", "warning"))
    elif settings.llm_provider == "anthropic":
        warnings.append(_blocker(
            "Call transcripts", "an OpenAI key", 5,
            "Anthropic can score and summarise but can't transcribe audio. Add "
            "an OpenAI key if you want written transcripts.", "warning"))

    # ---- content
    if not playbooks:
        warnings.append(_blocker(
            "Scripts & objections", "a playbook", 9,
            "Reps get no script rail and the AI has no questions to ask until "
            "you build a playbook — Setup step 9.", "warning"))
    if not drops:
        warnings.append(_blocker(
            "Voicemail drop", "a recorded voicemail", 10,
            "Record one and your reps can leave it with one click instead of "
            "talking through it every time — Setup step 10.", "warning"))

    # ---- compliance sanity
    if settings.recording_enabled and not settings.recording_announce:
        warnings.append(_blocker(
            "Recording", "a recording announcement", 7,
            "You're recording without announcing it. Several states require "
            "everyone on the call to consent — switch the announcement on.",
            "warning"))
    if not settings.gate_ai_line_type:
        warnings.append(_blocker(
            "AI calling", "", 7,
            "The mobile-number gate is switched OFF, so the AI will call cell "
            "phones. You accepted responsibility for consent on this list.",
            "warning"))
    if settings.elevenlabs_bursting:
        warnings.append(_blocker(
            "AI calling", "", 6,
            "Burst pricing is on. Going over your ElevenLabs concurrency limit "
            "will silently bill at double the per-minute rate.", "warning"))

    lanes = {
        "manual": bool(sim or (settings.has_twilio and numbers)),
        "power": bool(sim or (settings.has_twilio and rep_numbers)),
        "ai_outbound": bool(sim or (settings.has_twilio and ai_ready
                                    and ai_numbers and agents)),
        "ai_inbound": bool(sim or (settings.has_twilio and ai_ready and agents)),
        "voicemail": bool(sim or (settings.has_twilio and numbers and drops)),
    }
    return {"ok": not blockers, "blockers": blockers, "warnings": warnings,
            "lanes": lanes, "simulating": sim,
            "counts": {"numbers": len(numbers), "rep": len(rep_numbers),
                       "ai": len(ai_numbers), "agents": len(agents),
                       "playbooks": playbooks, "drops": drops}}
