"""Drives simulated calls through the REAL webhook and processing path.

This is what makes Practice mode worth having: it is not a mock of the UI, it
is the production pipeline with a fake carrier on the end. Every row a real
call would write gets written.
"""
import json
from datetime import datetime, timezone

from app import db

from dialer.models import Call, WebhookInbox
from dialer.providers.fakes import simulator


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def advance(call, settings=None):
    """Push one simulated call to completion."""
    from dialer import processor
    sim = simulator()
    sid = call.twilio_sid
    if sid and sim.state(sid):
        for i, payload in enumerate(sim.sequence(sid)):
            key = f"{sid}:{payload.get('CallStatus')}:{i}"
            if WebhookInbox.query.filter_by(dedupe_key=key).first():
                continue
            db.session.add(WebhookInbox(
                account_id=call.account_id, source="twilio",
                kind=f"status:{payload.get('CallStatus')}", dedupe_key=key,
                signature_ok=True, payload=json.dumps(payload)))
        db.session.commit()

    if call.elevenlabs_conversation_id:
        from dialer.providers import registry
        from dialer.settings_store import get_settings
        settings = settings or get_settings(call.account_id)
        va = registry.voice_agent(settings)
        conv = va.conversation(call.elevenlabs_conversation_id)
        if conv.get("ok"):
            key = f"el:{call.elevenlabs_conversation_id}:sim"
            if not WebhookInbox.query.filter_by(dedupe_key=key).first():
                db.session.add(WebhookInbox(
                    account_id=call.account_id, source="elevenlabs",
                    kind="post_call", dedupe_key=key, signature_ok=True,
                    payload=json.dumps({"data": {
                        "conversation_id": call.elevenlabs_conversation_id,
                        "transcript": conv.get("transcript"),
                        "analysis": {
                            "transcript_summary": "",
                            "data_collection_results":
                                (conv.get("analysis") or {}).get("data") or {}},
                        "metadata": {"call_duration_secs": conv.get("duration"),
                                     "cost": 0}}})))
                db.session.commit()

    processor.process_all(account_id=call.account_id, limit=20)
    db.session.refresh(call)
    return call


def advance_all(account_id, limit=100):
    """Finish every open simulated call on an account."""
    n = 0
    for call in (Call.query.filter_by(account_id=account_id)
                 .filter(Call.finalized_at.is_(None)).limit(limit).all()):
        advance(call)
        n += 1
    return n


def run_campaign(campaign, settings, max_rounds=200):
    """Dial and complete an entire campaign. Used by the demo seeder and the
    end-to-end test."""
    from dialer import campaigns
    rounds = dialed = 0
    while rounds < max_rounds:
        rounds += 1
        res = campaigns.tick(campaign, settings, limit=campaign.max_concurrent or 1)
        advance_all(campaign.account_id)
        dialed += res.get("dialed", 0)
        if res.get("dialed", 0) == 0 and res.get("deferred", 0) == 0:
            break
        db.session.refresh(campaign)
        if campaign.status != "running":
            break
    return {"rounds": rounds, "dialed": dialed}
