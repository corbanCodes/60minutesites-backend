"""Everything a call produced so far, in one dict.

The call page and the test page both read it, and both poll it while the
pieces are still landing: the AI's notes arrive during the call, its
transcript seconds after the hand-off, Twilio's completed status when the
person hangs up, the recording a few seconds after that, and the grade of
the human conversation once the recording has been transcribed.
"""
import json
from datetime import timedelta

from app import Note

from dialer.models import CallEvent

TERMINAL = ("completed", "failed", "canceled", "busy", "no-answer")


def results_for(call):
    events = (CallEvent.query.filter_by(call_id=call.id)
              .order_by(CallEvent.at, CallEvent.id).all())
    handoff = next((e for e in events if e.kind == "handoff"), None)
    rep_leg = next((e for e in reversed(events) if e.kind == "trace:rep_leg"), None)

    notes = []
    if call.lead_id and call.started_at:
        since = call.started_at - timedelta(minutes=1)
        until = (call.ended_at or call.started_at) + timedelta(hours=2)
        rows = (Note.query.filter_by(lead_id=call.lead_id, kind="ai_summary")
                .filter(Note.created_at >= since, Note.created_at <= until)
                .order_by(Note.created_at).all())
        notes = [(n.body or "").replace("[AI, during the call] ", "", 1)
                 for n in rows]

    try:
        coaching = json.loads(call.handoff_coaching_json or "{}")
    except ValueError:
        coaching = {}
    try:
        reasons = (json.loads(call.coaching_json or "{}") or {}).get("reasons") or []
    except ValueError:
        reasons = []

    terminal = call.status in TERMINAL
    pending = []
    if not terminal:
        pending.append("the call to end")
    if terminal and not call.transcript:
        pending.append("the AI transcript")
    if terminal and not call.recording_sid and not call.error:
        pending.append("the recording")

    pending_grade = ""
    if handoff is not None and call.handoff_score is None:
        if not call.recording_sid:
            pending_grade = "Graded once the recording arrives."
        else:
            stop = next((e for e in reversed(events)
                         if e.kind in ("handoff_grade_skipped",
                                       "handoff_grade_failed",
                                       "handoff_transcript_failed")), None)
            if stop is not None:
                pending_grade = f"Not graded: {stop.detail}"
            else:
                pending_grade = "Grading the human conversation\u2026"
                pending.append("the grade")

    at_text = ""
    if handoff is not None and call.started_at:
        secs = int((handoff.at - call.started_at).total_seconds())
        at_text = f"handed over {secs}s into the call"

    version = (len(events) + len(notes) + len(call.transcript or "")
               + (call.handoff_score or 0) + (1 if call.recording_sid else 0)
               + (1 if call.summary else 0) + (1 if call.finalized_at else 0))
    return {
        "call_id": call.id, "status": call.status or "",
        "finalized": bool(call.finalized_at),
        "disposition": call.disposition or "",
        "handed_off": handoff is not None,
        "handoff_at_text": at_text,
        "rep_leg": (rep_leg.detail if rep_leg is not None else ""),
        "notes": notes, "summary": call.summary or "",
        "transcript": call.transcript or "",
        "has_recording": bool(call.recording_sid and not call.recording_deleted_at),
        "score": call.score, "reasons": reasons,
        "handoff_score": call.handoff_score,
        "handoff_coaching": coaching,
        "handoff_transcript": call.handoff_transcript or "",
        "pending_grade": pending_grade,
        "pending": pending, "error": call.error or "",
        "version": version,
    }
