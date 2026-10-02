"""Segments, the dial queue, and the tick that feeds it.

The queue is a Postgres table claimed with FOR UPDATE SKIP LOCKED, which is
what lets a worker process and several reps' browsers all pull from the same
list without ever handing the same lead to two people. No Redis.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app import Lead, db

from dialer import compliance, tz
from dialer.models import Call, Campaign, CampaignLead, PhoneNumber

LEASE_MINUTES = 3


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_postgres():
    return db.engine.dialect.name == "postgresql"


# ----------------------------------------------------------------- segments
def build_query(account_id, seg):
    """seg is the saved filter dict from the segment builder."""
    q = Lead.query.filter(Lead.owner_id == account_id)
    if seg.get("statuses"):
        q = q.filter(Lead.status.in_(seg["statuses"]))
    if seg.get("sources"):
        q = q.filter(Lead.source.in_(seg["sources"]))
    if seg.get("business_type"):
        q = q.filter(Lead.business_type.ilike(f"%{seg['business_type']}%"))
    if seg.get("states"):
        q = q.filter(Lead.state_code.in_(seg["states"]))
    if seg.get("area_codes"):
        clauses = [Lead.phone_e164.like(f"+1{a}%") for a in seg["area_codes"]]
        q = q.filter(db.or_(*clauses))
    if seg.get("tags"):
        for t in seg["tags"]:
            q = q.filter(Lead.tags.ilike(f"%{t}%"))
    if seg.get("line_types"):
        q = q.filter(Lead.line_type.in_(seg["line_types"]))
    if seg.get("assignee_id"):
        q = q.filter(Lead.assignee_id == seg["assignee_id"])
    if seg.get("has_phone", True):
        q = q.filter(db.or_(Lead.phone_e164 != "", Lead.phone != ""))
    if seg.get("exclude_dnc", True):
        q = q.filter(db.or_(Lead.do_not_call.is_(False),
                            Lead.do_not_call.is_(None)))
    days = seg.get("not_called_in_days")
    if days:
        cutoff = _now() - timedelta(days=int(days))
        q = q.filter(db.or_(Lead.last_called_at.is_(None),
                            Lead.last_called_at < cutoff))
    if seg.get("lead_ids"):
        q = q.filter(Lead.id.in_(seg["lead_ids"]))
    return q


def preview(account_id, seg, settings, mode="power", limit=5):
    """What the segment builder shows live: how many, and how many the gate
    will actually let this mode dial."""
    leads = build_query(account_id, seg).limit(2000).all()
    eligible, blocked, reasons = [], [], {}
    for lead in leads:
        compliance.enrich_lead(lead)
        ev = compliance.can_dial(lead, mode, settings, account_id)
        if ev["ok"]:
            eligible.append(lead)
        else:
            blocked.append(lead)
            reasons[ev["reason"]] = reasons.get(ev["reason"], 0) + 1
    return {"total": len(leads), "eligible": len(eligible),
            "blocked": len(blocked), "reasons": reasons,
            "sample": [{"name": l.name, "business": l.business,
                        "phone": l.phone_e164 or l.phone,
                        "line_type": l.line_type or "unchecked"}
                       for l in eligible[:limit]]}


def materialize(campaign, settings):
    """Freeze the segment into queue rows. Later CRM edits don't shift a
    running campaign."""
    account_id = campaign.account_id
    leads = build_query(account_id, campaign.segment).all()
    existing = {r.lead_id for r in CampaignLead.query.filter_by(
        campaign_id=campaign.id)}
    added = skipped = 0
    for i, lead in enumerate(leads):
        if lead.id in existing:
            continue
        compliance.enrich_lead(lead)
        if not lead.phone_e164:
            skipped += 1
            continue
        db.session.add(CampaignLead(
            campaign_id=campaign.id, lead_id=lead.id, account_id=account_id,
            state="queued", position=i,
            lead_tz=lead.timezone or tz.zone_for(lead.phone_e164),
            next_attempt_at=_now()))
        added += 1
    db.session.commit()
    return {"added": added, "skipped": skipped,
            "total": CampaignLead.query.filter_by(campaign_id=campaign.id).count()}


# -------------------------------------------------------------- the claim
CLAIM_SQL = text("""
UPDATE campaign_lead SET state='claimed', locked_by=:worker, locked_at=:now,
       lease_until=:lease
WHERE id IN (
  SELECT cl.id FROM campaign_lead cl
  JOIN lead l ON l.id = cl.lead_id
  WHERE cl.campaign_id = :campaign_id
    AND cl.state IN ('queued','deferred')
    AND cl.next_attempt_at <= :now
    AND (l.do_not_call IS NULL OR l.do_not_call = false)
    AND NOT EXISTS (SELECT 1 FROM suppression s
                    WHERE s.account_id = cl.account_id
                      AND s.phone_key = l.phone_key)
  ORDER BY cl.next_attempt_at, cl.position
  LIMIT :n
  FOR UPDATE SKIP LOCKED)
RETURNING id
""")


def claim(campaign, n=1, worker="web"):
    """-> [CampaignLead]. On Postgres this is one atomic statement; on SQLite
    (tests, laptop) there is a single writer so a plain update is equivalent."""
    now = _now()
    lease = now + timedelta(minutes=LEASE_MINUTES)
    ids = []
    if _is_postgres():
        rows = db.session.execute(CLAIM_SQL, {
            "worker": worker, "now": now, "lease": lease,
            "campaign_id": campaign.id, "n": n}).fetchall()
        ids = [r[0] for r in rows]
        db.session.commit()
    else:
        q = (db.session.query(CampaignLead.id)
             .join(Lead, Lead.id == CampaignLead.lead_id)
             .filter(CampaignLead.campaign_id == campaign.id,
                     CampaignLead.state.in_(["queued", "deferred"]),
                     CampaignLead.next_attempt_at <= now,
                     db.or_(Lead.do_not_call.is_(False),
                            Lead.do_not_call.is_(None)))
             .order_by(CampaignLead.next_attempt_at, CampaignLead.position)
             .limit(n))
        ids = [r[0] for r in q.all()]
        if ids:
            from dialer.models import Suppression
            keep = []
            for cl_id in ids:
                cl = db.session.get(CampaignLead, cl_id)
                lead = db.session.get(Lead, cl.lead_id)
                if Suppression.query.filter_by(
                        account_id=cl.account_id,
                        phone_key=lead.phone_key).first():
                    cl.state = "skipped"
                    cl.skip_reason = "do-not-call"
                    continue
                cl.state, cl.locked_by = "claimed", worker
                cl.locked_at, cl.lease_until = now, lease
                keep.append(cl_id)
            ids = keep
            db.session.commit()
    return [db.session.get(CampaignLead, i) for i in ids]


def release(cl, reason="", defer_minutes=None):
    cl.locked_by, cl.locked_at, cl.lease_until = "", None, None
    if defer_minutes:
        cl.state = "deferred"
        cl.next_attempt_at = _now() + timedelta(minutes=defer_minutes)
    else:
        cl.state = "queued"
    if reason:
        cl.skip_reason = reason[:120]
    db.session.commit()


def sweep_expired_leases(account_id=None):
    """A rep closed the tab mid-dial; put the lead back."""
    q = CampaignLead.query.filter(CampaignLead.state == "claimed",
                                  CampaignLead.lease_until < _now())
    if account_id:
        q = q.filter(CampaignLead.account_id == account_id)
    n = 0
    for cl in q.limit(200):
        cl.state, cl.locked_by, cl.lease_until = "queued", "", None
        n += 1
    if n:
        db.session.commit()
    return n


# --------------------------------------------------------------- numbers
def pick_number(account_id, pool="rep", lead=None, simulate_ok=False):
    """Lowest-used active number under its cap, preferring the lead's own area
    code so it shows as a local call."""
    today = _now().date()
    rows = PhoneNumber.query.filter_by(account_id=account_id, pool=pool,
                                       state="active").all()
    # A sample number has no Twilio number behind it, so dialling from one
    # fails at the carrier with an error about an unverified source. In
    # practice mode nothing really dials, so there it is fine.
    allow_fake = simulate_ok
    usable = []
    for n in rows:
        if n.is_placeholder and not allow_fake:
            continue
        if n.calls_today_date != today:
            n.calls_today, n.calls_today_date = 0, today
        if (n.calls_today or 0) < (n.daily_cap or 120):
            usable.append(n)
    if not usable:
        return None
    if lead is not None and lead.phone_e164:
        want = tz.area_code(lead.phone_e164)
        local = [n for n in usable if n.area_code == want]
        if local:
            usable = local
    usable.sort(key=lambda n: (n.calls_today or 0))
    return usable[0]


def bump_number(number):
    today = _now().date()
    if number.calls_today_date != today:
        number.calls_today, number.calls_today_date = 0, today
    number.calls_today = (number.calls_today or 0) + 1
    number.last_outbound_at = _now()
    if not number.first_outbound_at:
        number.first_outbound_at = _now()


# ------------------------------------------------------------- the tick
def tick(campaign, settings, limit=None, worker="web"):
    """Dial up to `limit` leads. Called by the worker for AI campaigns and by
    the rep's browser for power campaigns."""
    from dialer import calls as calls_mod
    if campaign.status != "running":
        return {"dialed": 0, "reason": campaign.status}
    account_id = campaign.account_id
    active = Call.query.filter(
        Call.campaign_id == campaign.id,
        Call.status.in_(["queued", "initiated", "ringing", "in-progress"])).count()
    room = max(0, (campaign.max_concurrent or 1) - active)
    limit = min(limit or room, room)
    if limit <= 0:
        return {"dialed": 0, "reason": "at capacity"}

    dialed, skipped, deferred = 0, 0, 0
    for cl in claim(campaign, n=limit, worker=worker):
        lead = db.session.get(Lead, cl.lead_id)
        if lead is None:
            cl.state, cl.skip_reason = "skipped", "lead deleted"
            continue
        mode = {"power": "power", "ai": "ai_outbound",
                "voicemail": "voicemail"}.get(campaign.mode, "power")
        ev = compliance.can_dial(lead, mode, settings, account_id,
                                 campaign=campaign)
        if not ev["ok"]:
            if ev["reason"] in ("outside_window", "state_window"):
                nxt = tz.next_window_open(cl.lead_tz, settings.window_start,
                                          settings.window_weekdays)
                cl.state, cl.next_attempt_at = "deferred", nxt
                cl.skip_reason = ev["reason"]
                deferred += 1
            else:
                cl.state, cl.skip_reason = "skipped", ev["reason"]
                skipped += 1
            continue
        number = pick_number(account_id, campaign.number_pool, lead,
                             simulate_ok=registry_simulating(settings))
        if number is None:
            release(cl, "no number available", defer_minutes=30)
            break
        call = calls_mod.start_call(
            account_id, lead, mode, settings, from_number=number.e164,
            campaign=campaign, campaign_lead=cl, gate=ev)
        placed = _place(call, campaign, settings, number, lead)
        if placed:
            cl.state, cl.last_call_id = "dialing", call.id
            cl.attempts = (cl.attempts or 0) + 1
            bump_number(number)
            dialed += 1
        else:
            release(cl, "dial failed", defer_minutes=10)
    db.session.commit()
    return {"dialed": dialed, "skipped": skipped, "deferred": deferred}


def _place(call, campaign, settings, number, lead):
    """Hand the call to the right vendor for this campaign mode."""
    from dialer import urls
    from dialer.models import AiAgent, VoicemailDrop
    tel = registry_telephony(settings)
    status_cb = urls.twilio_status(call.account_id)
    if campaign.mode == "ai":
        agent = db.session.get(AiAgent, campaign.ai_agent_id)
        if agent is None or not agent.elevenlabs_agent_id:
            call.error = "No AI agent is set up for this campaign."
            return False
        va = registry_voice(settings)
        r = va.outbound_call(agent.elevenlabs_agent_id,
                             number.elevenlabs_phone_id or number.twilio_sid,
                             call.to_number, variables=_variables(lead, call))
        if not r.get("ok"):
            call.error = r.get("error", "")[:400]
            return False
        call.elevenlabs_conversation_id = (r.get("conversation_id") or "")[:64]
        call.twilio_sid = (r.get("call_sid") or "")[:64]
        call.status = "initiated"
        return True

    if campaign.mode == "voicemail":
        drop = db.session.get(VoicemailDrop, campaign.voicemail_drop_id)
        if drop is None:
            call.error = "No voicemail recording is set for this campaign."
            return False
        r = tel.create_call(
            to=call.to_number, from_=number.e164,
            url=urls.twilio_voicemail(call.id),
            status_callback=status_cb, machine_detection="DetectMessageEnd",
            async_amd=True, machine_detection_timeout=50,
            amd_status_callback=urls.twilio_amd(call.id))
    else:
        r = tel.create_call(
            to=call.to_number, from_=number.e164,
            url=urls.twilio_outgoing(call.account_id, call.id),
            status_callback=status_cb,
            record=bool(settings.recording_enabled),
            recording_status_callback=urls.twilio_recording(call.account_id),
            time_limit=settings.max_call_seconds or 600)
    if not r.get("ok"):
        call.error = r.get("error", "")[:400]
        return False
    call.twilio_sid = (r.get("sid") or "")[:64]
    call.status = "initiated"
    return True


def _variables(lead, call):
    """CRM context the AI gets before it says hello."""
    from app import Note
    notes = (Note.query.filter_by(lead_id=lead.id)
             .order_by(Note.created_at.desc()).limit(3).all())
    return {
        "lead_name": lead.name or "there",
        "first_name": (lead.name or "").split(" ")[0],
        "business": lead.business or "",
        "business_type": lead.business_type or "",
        "city": "", "state": lead.state_code or "",
        "prior_calls": str(lead.call_count or 0),
        "last_note": (notes[0].body[:300] if notes else ""),
        "lead_status": lead.status or "New",
    }


def registry_simulating(settings):
    """Imported inside the function like its neighbours here, which exist to
    keep dialer.providers out of this module's import cycle."""
    from dialer.providers import registry
    return registry.simulating(settings)


def registry_telephony(settings):
    from dialer.providers import registry
    return registry.telephony(settings)


def registry_voice(settings):
    from dialer.providers import registry
    return registry.voice_agent(settings)


# ------------------------------------------------------------ queue close
def close_queue_row(call):
    """Called from finalize(): mark the queue row done, or schedule a retry."""
    from dialer.settings_store import get_settings
    cl = db.session.get(CampaignLead, call.campaign_lead_id)
    if cl is None:
        return
    settings = get_settings(call.account_id)
    outcome = call.system_outcome or "unknown"
    cl.outcome = call.disposition or outcome
    policy = settings.retry_policy.get(outcome)
    terminal = call.disposition in ("dnc", "not_interested", "meeting_set",
                                    "qualified", "wrong_number")
    if terminal or not policy or (cl.attempts or 0) >= policy["attempts"]:
        cl.state = "done"
    else:
        cl.state = "deferred"
        cl.next_attempt_at = _now() + timedelta(minutes=policy["minutes"])
    cl.locked_by, cl.lease_until = "", None
    _update_stats(call.campaign_id)


def _update_stats(campaign_id):
    c = db.session.get(Campaign, campaign_id)
    if c is None:
        return
    rows = CampaignLead.query.filter_by(campaign_id=campaign_id).all()
    calls = Call.query.filter_by(campaign_id=campaign_id).all()
    stats = {
        "queued": sum(1 for r in rows if r.state in ("queued", "deferred")),
        "done": sum(1 for r in rows if r.state == "done"),
        "skipped": sum(1 for r in rows if r.state == "skipped"),
        "total": len(rows), "dials": len(calls),
        "connects": sum(1 for x in calls if x.answered_live),
        "meetings": sum(1 for x in calls
                        if x.disposition in ("meeting_set", "qualified")),
    }
    c.stats_json = json.dumps(stats)
    if stats["queued"] == 0 and c.status == "running":
        c.status, c.finished_at = "done", _now()
