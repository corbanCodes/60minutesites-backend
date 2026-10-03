"""Call lifecycle: start, disposition, and the post-call pipeline.

finalize() is the valuable part. One call in, and out come: a transcript, a
three-line summary, a coaching score, the answers to the qualification
questions, the lead's new stage, a note on the lead and the next follow-up
task. It is idempotent -- a replayed webhook changes nothing.
"""
import json
from datetime import datetime, timedelta, timezone

from app import Lead, Note, Task, db

from dialer import compliance
from dialer.models import (DEFAULT_STAGE_MAP, PROTECTED_STAGES, AiAgent, Call,
                           CallEvent, DISPOSITION_LABELS)
from dialer.providers import registry


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def event(call, kind, detail="", payload=None):
    db.session.add(CallEvent(call_id=call.id, account_id=call.account_id,
                             kind=kind, detail=str(detail)[:300],
                             payload=json.dumps(payload) if payload else ""))


# --------------------------------------------------------------- creating
def start_call(account_id, lead, mode, settings, from_number=None,
               campaign=None, campaign_lead=None, agent_user_id=None,
               ai_agent=None, gate=None):
    """Create the Call row with the compliance decision frozen onto it."""
    gate = gate or compliance.can_dial(lead, mode, settings, account_id,
                                       campaign=campaign)
    call = Call(
        account_id=account_id, lead_id=getattr(lead, "id", None),
        campaign_id=getattr(campaign, "id", None),
        campaign_lead_id=getattr(campaign_lead, "id", None),
        direction="outbound", mode=mode, agent_user_id=agent_user_id,
        ai_agent_id=getattr(ai_agent, "id", None),
        from_number=from_number or "", to_number=lead.phone_e164 or lead.phone,
        line_type_at_dial=(lead.line_type or ""),
        consent_at_dial=(lead.consent_status or "none"),
        gate_decision=json.dumps(gate),
        disclosure_text=(settings.effective_disclosure
                         if mode in ("ai_outbound", "voicemail")
                         and settings.disclose_ai else ""),
        status="queued", started_at=_now())
    db.session.add(call)
    db.session.flush()
    event(call, "created", f"mode={mode} gate={gate.get('reason')}")
    return call


# ------------------------------------------------------------- outcomes
_STATUS_TO_OUTCOME = {
    "completed": "answered_human", "busy": "busy", "no-answer": "no_answer",
    "failed": "failed", "canceled": "canceled",
}


def apply_status(call, status, answered_by=None, duration=None, price=None):
    """Fold a carrier status event into the call row."""
    call.status = status
    if status == "in-progress" and not call.answered_at:
        call.answered_at = _now()
        call.answered_live = (answered_by or "human") == "human"
    if answered_by:
        if answered_by.startswith("machine"):
            call.system_outcome = "answered_machine"
            call.answered_live = False
        elif answered_by == "human":
            call.system_outcome = "answered_human"
            call.answered_live = True
    if status in _STATUS_TO_OUTCOME and status != "completed":
        call.system_outcome = _STATUS_TO_OUTCOME[status]
    if status in ("completed", "busy", "no-answer", "failed", "canceled"):
        call.ended_at = call.ended_at or _now()
        if duration is not None:
            call.duration_s = int(duration or 0)
        if status == "completed" and not call.system_outcome:
            call.system_outcome = ("answered_human" if call.duration_s
                                   else "no_answer")
        # Twilio bills whole minutes, per leg. Model it the same way or the
        # cost meter understates short calls by 2-3x.
        call.billable_minutes = max(1, (int(call.duration_s or 0) + 59) // 60) \
            if call.duration_s else 0
    if price is not None:
        try:
            call.vendor_cost = abs(float(price))
        except (TypeError, ValueError):
            pass
    event(call, f"status:{status}", answered_by or "")
    return call


def set_disposition(call, disposition, user_id=None, settings=None, note=""):
    """What the human (or the AI) decided. This is what moves the lead."""
    if disposition not in DEFAULT_STAGE_MAP and disposition != "transferred":
        return call
    call.disposition = disposition
    call.disposition_by = user_id
    event(call, "disposition", disposition)
    lead = db.session.get(Lead, call.lead_id) if call.lead_id else None
    if lead is None:
        return call

    lead.last_outcome = disposition
    lead.last_called_at = call.started_at or _now()
    lead.call_count = (lead.call_count or 0) + 0  # incremented once, in finalize

    if disposition == "dnc":
        compliance.suppress(call.account_id, lead.phone_key,
                            reason="Asked not to be called again",
                            source="rep" if user_id else "ai",
                            lead=lead, call_id=call.id, user_id=user_id)
        db.session.add(Note(lead_id=lead.id, kind="system", author_id=user_id,
                            body="Marked do-not-call on a call. Removed from "
                                 "every queue on this account."))

    stage_map = settings.stage_map if settings else DEFAULT_STAGE_MAP
    target = stage_map.get(disposition, "")
    if target and lead.status != target:
        # never demote a won account because of one bad call
        if not (lead.status in PROTECTED_STAGES and target != "Dead"):
            if lead.status in PROTECTED_STAGES and target == "Dead":
                pass  # also leave Clients alone on a "not interested"
            else:
                old, lead.status = lead.status, target
                db.session.add(Note(
                    lead_id=lead.id, kind="system", author_id=user_id,
                    body=f"Status changed: {old} → {target}"))
    if note:
        db.session.add(Note(lead_id=lead.id, kind="call", author_id=user_id,
                            body=note))
    return call


# -------------------------------------------------------------- finalize
SUMMARY_SYSTEM = (
    "You review recorded sales calls for a small B2B team and return strict "
    "JSON. Be concrete and brief. Never invent facts that are not in the "
    "transcript. If the contact asked not to be called again in any wording, "
    "set revocation_detected true.")

SUMMARY_SHAPE = """Return ONLY a JSON object:
{"summary": "<=3 sentences, what happened and what was agreed",
 "disposition": one of %s,
 "score": 1-10 or null if no human conversation,
 "score_reasons": ["<=3 short reasons"],
 "objections": ["objections the prospect raised"],
 "qualification": {"<question key>": "<answer>"},
 "revocation_detected": true/false,
 "follow_up": {"title": "...", "kind": "Call|Follow-up|Email", "in_days": N,
   "at": "YYYY-MM-DD HH:MM" if they named a day or time, else null,
   "said": "what they actually said about when to call, in their words"} or null}

If the person asked to be called back, "at" is the important field. Read it
off what they said: "Thursday morning" with today's date given below becomes
that Thursday at 09:00, "after 3" today becomes today at 15:00, "next week"
with no day becomes the next Tuesday at 10:00. Only fill it in if they
actually indicated a time; a guess that is wrong is worse than in_days."""


def finalize(call, settings=None, force=False):
    """Idempotent. Safe to call from a webhook replay or a sweeper."""
    from dialer.settings_store import get_settings
    if call.finalized_at and not force:
        return call
    settings = settings or get_settings(call.account_id)
    lead = db.session.get(Lead, call.lead_id) if call.lead_id else None
    providers_needed = call.mode in ("manual", "power")

    # 1. transcript -------------------------------------------------------
    if not call.transcript:
        if call.elevenlabs_conversation_id:
            r = registry.voice_agent(settings).conversation(
                call.elevenlabs_conversation_id)
            if r.get("ok"):
                call.transcript = r.get("transcript", "")
                call.duration_s = call.duration_s or int(r.get("duration") or 0)
                if r.get("cost"):
                    call.vendor_cost = float(r["cost"])
                analysis = r.get("analysis") or {}
                if analysis.get("disposition") and not call.disposition:
                    set_disposition(call, analysis["disposition"],
                                    settings=settings)
                if analysis.get("data"):
                    call.qualification_json = json.dumps(analysis["data"])
            else:
                event(call, "transcript_failed", r.get("error", ""))
        elif providers_needed and call.recording_sid and _can_transcribe(settings):
            rec = registry.telephony(settings).fetch_recording(call.recording_sid)
            if rec.get("ok"):
                tr = registry.transcriber(settings).transcribe(
                    rec["content"], rec.get("mimetype", "audio/mpeg"))
                if tr.get("ok"):
                    call.transcript = tr.get("text", "")
                else:
                    event(call, "transcript_failed", tr.get("error", ""))

    # 2. the AI pass ------------------------------------------------------
    if call.transcript and call.score is None and not call.summary:
        ctx_bits = []
        if lead is not None:
            ctx_bits.append(f"Lead: {lead.name} at {lead.business or 'unknown'}")
            if lead.business_type:
                ctx_bits.append(f"Type: {lead.business_type}")
        transcript = call.transcript[:12000]
        if call.system_outcome == "answered_machine":
            transcript = ("[This call reached an answering machine.]\n"
                          + transcript)
        # "Thursday morning" is only resolvable against a date, and the
        # model has no idea when the call happened unless it is told.
        when = call.started_at or _now()
        today = (f"Today is {when.strftime('%A %d %B %Y')} "
                 f"and the call was at {when.strftime('%H:%M')}.")
        prompt = (f"{SUMMARY_SHAPE % json.dumps(list(DEFAULT_STAGE_MAP))}\n\n"
                  f"{today}\n{chr(10).join(ctx_bits)}\n\n"
                  f"TRANSCRIPT:\n{transcript}")
        r = registry.llm(settings).complete(SUMMARY_SYSTEM, prompt,
                                            max_tokens=700, json_mode=True)
        if r.get("ok") and isinstance(r.get("data"), dict):
            d = r["data"]
            call.summary = (d.get("summary") or "")[:4000]
            call.score = d.get("score") if isinstance(d.get("score"), int) else None
            call.coaching_json = json.dumps({"reasons": d.get("score_reasons") or []})
            call.objections_json = json.dumps(d.get("objections") or [])
            if d.get("qualification"):
                call.qualification_json = json.dumps(d["qualification"])
            call.revocation_detected = bool(d.get("revocation_detected"))
            if not call.disposition and d.get("disposition"):
                set_disposition(call, d["disposition"], settings=settings)
            _follow_up(call, lead, d.get("follow_up"))
        else:
            event(call, "ai_failed", r.get("error", ""))

    # 2b. richer coaching when the account has a playbook: which questions
    #     actually got asked, which were missed, one line of advice.
    if call.transcript and call.mode in ("manual", "power"):
        try:
            from dialer import coaching
            from dialer.models import Campaign, Playbook
            pb = None
            if call.campaign_id:
                camp = db.session.get(Campaign, call.campaign_id)
                if camp and camp.playbook_id:
                    pb = db.session.get(Playbook, camp.playbook_id)
            pb = pb or Playbook.query.filter_by(account_id=call.account_id,
                                                is_default=True).first()
            if pb is not None:
                coaching.score_call(call, settings, pb)
        except Exception as e:
            event(call, "coaching_failed", str(e)[:200])

    # 3. an opt-out heard on the call beats everything else ---------------
    if call.revocation_detected and lead is not None:
        compliance.suppress(call.account_id, lead.phone_key,
                            reason="Asked to be removed, heard on the call",
                            source="transcript", lead=lead, call_id=call.id)
        if call.disposition != "dnc":
            set_disposition(call, "dnc", settings=settings)

    # 4. write the record onto the lead -----------------------------------
    if lead is not None and not call.finalized_at:
        lead.call_count = (lead.call_count or 0) + 1
        lead.last_called_at = call.started_at or _now()
        db.session.add(Note(
            lead_id=lead.id, kind="call", author_id=call.agent_user_id,
            body=_call_note(call)))

    # 5. campaign bookkeeping ---------------------------------------------
    if call.campaign_lead_id:
        from dialer.campaigns import close_queue_row
        close_queue_row(call)

    call.cost_estimate = estimate_cost(call, settings)
    call.finalized_at = _now()
    event(call, "finalized", call.disposition or call.system_outcome or "")
    db.session.commit()
    return call


def _can_transcribe(settings):
    """Practice mode has no keys and should still produce the full record."""
    return bool(registry.simulating(settings) or settings.has_llm)


def _call_note(call):
    bits = []
    who = {"manual": "Call", "power": "Call", "ai_outbound": "AI call",
           "ai_inbound": "Inbound AI call",
           "voicemail": "Voicemail drop"}.get(call.mode, "Call")
    head = f"{who} — {DISPOSITION_LABELS.get(call.disposition, call.system_outcome or 'completed')}"
    if call.duration_s:
        head += f" ({call.duration_pretty})"
    bits.append(head)
    if call.summary:
        bits.append(call.summary)
    q = call.qualification
    if q:
        bits.append(" · ".join(f"{k.replace('_', ' ').title()}: {v}"
                               for k, v in list(q.items())[:8]))
    if call.score:
        bits.append(f"Call score: {call.score}/10")
    bits.append(f"[call:{call.id}]")
    return "\n".join(bits)


def _callback_time(raw):
    """A time the prospect named, or None.

    Anything unparseable, in the past, or absurdly far out is treated as no
    answer rather than forced into a date: a follow-up on the wrong day is
    worse than one the rep schedules themselves.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()[:40]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d"):
        try:
            when = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            when = when.replace(hour=10)
        now = _now()
        if when < now - timedelta(hours=1) or when > now + timedelta(days=120):
            return None
        return when
    return None


def _follow_up(call, lead, fu):
    if not fu or not isinstance(fu, dict) or lead is None:
        return
    title = (fu.get("title") or "").strip()[:240]
    if not title:
        return
    kind = fu.get("kind") if fu.get("kind") in ("Call", "Follow-up", "Email") \
        else "Follow-up"
    # A time the person actually named beats a round number of days. "Call
    # Thursday morning" landing on Thursday at 09:00 is the difference
    # between a task that gets honoured and one that gets reshuffled.
    due = _callback_time(fu.get("at"))
    if due is None:
        try:
            days = max(0, min(int(fu.get("in_days") or 1), 90))
        except (TypeError, ValueError):
            days = 1
        due = (_now() + timedelta(days=days)).replace(
            hour=16, minute=0, second=0, microsecond=0)
    said = (fu.get("said") or "").strip()[:200]
    if said and said.lower() not in title.lower():
        title = f"{title} — they said: {said}"[:240]
    db.session.add(Task(owner_id=call.account_id or None, lead_id=lead.id,
                        title=title, kind=kind, due_at=due,
                        assignee_id=call.agent_user_id))
    event(call, "follow_up", title)


# ------------------------------------------------------- the hand-off grade
HANDOFF_SYSTEM = (
    "You review recorded sales calls for a small B2B team and return strict "
    "JSON. An AI assistant opened the call and reached the decision maker; a "
    "human salesperson then took over. Judge ONLY the human, and how the "
    "hand-off itself felt to the prospect. Be concrete and brief. Never "
    "invent anything that is not in the transcript.")

HANDOFF_SHAPE = """Return ONLY a JSON object:
{"score": 1-10 for the human salesperson, or null if no human spoke,
 "reasons": ["<=3 short reasons for the score"],
 "advice": "one sentence the salesperson should do differently next time",
 "handoff_moment": "one sentence: how the switch from the AI to the person
   came across to the prospect -- seamless, awkward, noticed, not noticed",
 "prospect_said": "<=2 sentences: what the prospect wanted or decided"}"""


def _transcript_text(tr):
    if tr.get("text"):
        return str(tr["text"])
    segs = tr.get("segments") or []
    return "\n".join(f"{s.get('speaker', '')}: {s.get('text', '')}".strip(": ")
                     for s in segs if isinstance(s, dict))


def grade_handoff(call, settings=None, force=False):
    """The human conversation after the AI handed over: transcript + grade.

    An owned-mode recording covers the whole call -- the AI, the hand-off
    line and the salesperson -- so this is where the hand-off itself is
    judged, which is the one thing the test page could not show. Each
    step says why it stopped, on the call's timeline, so "no grade" is
    never a mystery.
    """
    from dialer.settings_store import get_settings
    settings = settings or get_settings(call.account_id)
    if not call.conference_name or not call.recording_sid:
        return None
    if call.handoff_score is not None and not force:
        return None
    if not call.handoff_transcript:
        if not _can_transcribe(settings):
            event(call, "handoff_grade_skipped",
                  "no transcription key: add an OpenAI key on step 5")
            db.session.commit()
            return None
        rec = registry.telephony(settings).fetch_recording(call.recording_sid)
        if not rec.get("ok"):
            event(call, "handoff_transcript_failed",
                  f"recording: {rec.get('error', '')}")
            db.session.commit()
            return None
        tr = registry.transcriber(settings).transcribe(
            rec["content"], rec.get("mimetype", "audio/mpeg"))
        if not tr.get("ok"):
            event(call, "handoff_transcript_failed", tr.get("error", ""))
            db.session.commit()
            return None
        call.handoff_transcript = _transcript_text(tr)[:20000]
        db.session.commit()
    if not (settings.has_llm or registry.simulating(settings)):
        event(call, "handoff_grade_skipped", "no LLM key: add one on step 5")
        db.session.commit()
        return None
    agent = db.session.get(AiAgent, call.ai_agent_id) if call.ai_agent_id else None
    line = (getattr(agent, "transfer_line", "") or "").strip() or "Oh, okay. Thanks."
    prompt = (f"{HANDOFF_SHAPE}\n\nThe AI handed over by saying: {line!r}. "
              f"Everything before that line is the AI assistant; grade only "
              f"the human salesperson after it.\n\nFULL CALL TRANSCRIPT:\n"
              f"{call.handoff_transcript[:12000]}")
    r = registry.llm(settings).complete(HANDOFF_SYSTEM, prompt,
                                        max_tokens=500, json_mode=True)
    if r.get("ok") and isinstance(r.get("data"), dict):
        d = r["data"]
        call.handoff_score = d.get("score") if isinstance(d.get("score"), int) else None
        call.handoff_coaching_json = json.dumps({
            "reasons": d.get("reasons") or [],
            "advice": d.get("advice") or "",
            "handoff_moment": d.get("handoff_moment") or "",
            "prospect_said": d.get("prospect_said") or ""})
        event(call, "handoff_graded", f"score={call.handoff_score}")
    else:
        event(call, "handoff_grade_failed", r.get("error", ""))
    db.session.commit()
    return call


# ------------------------------------------------------------------ cost
RATES = {
    "twilio_outbound_min": 0.0140, "twilio_inbound_min": 0.0085,
    "conference_participant_min": 0.0018, "client_leg_min": 0.0040,
    "recording_min": 0.0025, "amd_per_call": 0.0075,
    "elevenlabs_min": 0.080, "elevenlabs_llm_min": 0.015,
    "transcribe_min": 0.003, "llm_per_call": 0.001,
}


def estimate_cost(call, settings=None):
    """Whole minutes, per leg -- the way Twilio actually bills."""
    if call.vendor_cost:
        base = float(call.vendor_cost)
    else:
        mins = call.billable_minutes or 0
        base = mins * RATES["twilio_outbound_min"]
        if call.mode == "power":
            base += mins * (RATES["conference_participant_min"] * 2
                            + RATES["client_leg_min"])
        elif call.mode == "manual":
            base += mins * RATES["client_leg_min"]
    mins = call.billable_minutes or 0
    if call.mode in ("ai_outbound", "ai_inbound"):
        base += mins * (RATES["elevenlabs_min"] + RATES["elevenlabs_llm_min"])
    if call.recording_sid or (settings and settings.recording_enabled):
        base += mins * RATES["recording_min"]
    if call.transcript and call.mode in ("manual", "power"):
        base += mins * RATES["transcribe_min"]
    if call.summary:
        base += RATES["llm_per_call"]
    return round(base, 4)
