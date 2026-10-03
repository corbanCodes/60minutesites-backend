"""What the AI is told about the person before it says hello.

One dict, whole, every time. ElevenLabs treats a missing dynamic variable
as a failure, and three places used to build this by hand with three
different sets of keys. The prompt references every key here.
"""
from app import Note

BASE = {"lead_name": "there", "first_name": "there", "business": "",
        "business_type": "", "city": "", "state": "", "prior_calls": "0",
        "last_note": "", "lead_status": "New", "is_known": "false",
        "decision_maker": "", "callback_said": ""}


def lead_vars(lead):
    if lead is None:
        return dict(BASE)
    notes = (Note.query.filter_by(lead_id=lead.id)
             .order_by(Note.created_at.desc()).limit(1).all())
    return {
        "lead_name": lead.name or "there",
        "first_name": (lead.name or "there").split(" ")[0],
        "business": lead.business or "",
        "business_type": lead.business_type or "",
        "city": "", "state": lead.state_code or "",
        "prior_calls": str(lead.call_count or 0),
        "last_note": (notes[0].body[:300] if notes else ""),
        "lead_status": lead.status or "New",
        "is_known": "true",
        "decision_maker": getattr(lead, "decision_maker", "") or "",
        "callback_said": getattr(lead, "callback_said", "") or "",
    }
