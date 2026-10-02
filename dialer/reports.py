"""The numbers a manager, a regulator and an enterprise buyer each ask for.

Pure functions, no routes. Every one takes an `account_id` and hands back a
plain dict (or list of dicts) a template can render without running a single
query of its own. That is deliberate: the reports page is the easiest place in
the product to grow an accidental N+1, and the daily digest has to be built by
the worker, outside any request context, from exactly the same code.

Everything here is written to survive an empty account. No division by zero,
no None arithmetic, and the full key set every time -- a dashboard that
KeyErrors on a brand-new account is worse than one showing a row of zeroes.

One definition to know before reading further. `summary()` keeps `meetings`
(disposition `meeting_set`) and `qualified` apart, because a manager reading a
daily recap wants to know which of the two happened. Everywhere else -- the
leaderboard, the campaign table, AI vs human -- `meetings` means "a booked
outcome", `meeting_set` OR `qualified`, which is the definition
campaigns._update_stats and the dialer home tiles already use. `summary()`
also returns that combined figure as `booked`, so a template can show one
number consistently across the page.
"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import LOCAL_TZ, Task, User, db, to_local

from dialer import calls as calls_mod
from dialer.models import (DEFAULT_STAGE_MAP, DISPOSITION_KEYS,
                           DISPOSITION_LABELS, Call, Campaign, CampaignLead,
                           PhoneNumber)

# The FCC's safe-harbour abandonment ceiling. Hard-coded on purpose: it is a
# regulatory number, not a preference, and an account must not be able to
# "configure" its way out of the red light.
ABANDON_CAP_PCT = 3.0

# Below this share of the pool's median answer rate a DID is behaving like a
# number the carriers have started labelling. Paired with a dial floor so a
# brand-new number is never condemned on four calls.
SPAM_FLAG_RATIO = 0.60
SPAM_FLAG_MIN_DIALS = 20

_AI_MODES = ("ai_outbound", "ai_inbound")


# ------------------------------------------------------------------ helpers
def _zone(tz_name=None):
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return LOCAL_TZ
    return LOCAL_TZ


def _naive_utc(dt_local):
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rate(part, whole, places=1):
    """Percentage, zero when there is nothing to divide by."""
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, places)


def _money(part, whole):
    if not whole:
        return 0.0
    return round(float(part) / float(whole), 2)


def _pretty_seconds(total):
    s = int(total or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {sec:02d}s"


def _stage_map(account_id):
    """The account's own disposition -> stage map, without creating a settings
    row just to read a report."""
    from dialer.settings_store import get_settings
    s = get_settings(account_id, create=False)
    return s.stage_map if s is not None else dict(DEFAULT_STAGE_MAP)


def _settings(account_id):
    from dialer.settings_store import get_settings
    return get_settings(account_id, create=False)


def _calls_q(account_id, start=None, end=None, user_id=None, campaign_id=None):
    q = Call.query.filter(Call.account_id == account_id)
    if start is not None:
        q = q.filter(Call.started_at >= start)
    if end is not None:
        q = q.filter(Call.started_at <= end)
    if user_id is not None:
        q = q.filter(Call.agent_user_id == user_id)
    if campaign_id is not None:
        q = q.filter(Call.campaign_id == campaign_id)
    return q


def _is_ai(call):
    return (call.mode or "") in _AI_MODES


def _booked(call):
    """A booked outcome. Matches campaigns._update_stats so the reports page
    and the campaign card never show two different numbers for one campaign."""
    return call.disposition in ("meeting_set", "qualified")


# --------------------------------------------------------------- the window
def day_range(days=1, tz_name=None):
    """-> (start, end) naive-UTC bounds covering the last `days` local days.

    Local, not UTC: "today" on a report has to mean the day the rep actually
    lived through. A UTC day boundary would cut a West-Coast afternoon in half.
    """
    zone = _zone(tz_name)
    now_local = datetime.now(zone)
    try:
        back = max(0, int(days) - 1)
    except (TypeError, ValueError):
        back = 0
    start_local = (now_local - timedelta(days=back)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(hour=23, minute=59, second=59,
                                  microsecond=999999)
    return _naive_utc(start_local), _naive_utc(end_local)


# ------------------------------------------------------------------ summary
def summary(account_id, start=None, end=None, user_id=None, campaign_id=None):
    """The headline block. Every other report hangs off these definitions."""
    rows = _calls_q(account_id, start, end, user_id, campaign_id).all()
    stage_map = _stage_map(account_id)

    dials = len(rows)
    connects = sum(1 for c in rows if c.answered_live)
    dm_reached = sum(1 for c in rows if c.disposition == "dm_reached")
    qualified = sum(1 for c in rows if c.disposition == "qualified")
    meetings = sum(1 for c in rows if c.disposition == "meeting_set")
    # Either a pre-recorded drop or a message left by hand counts: the manager
    # is asking "how many mailboxes did we land in", not which button was used.
    voicemails = sum(1 for c in rows
                     if c.voicemail_dropped or c.disposition == "voicemail_left")
    no_answer = sum(1 for c in rows if c.system_outcome == "no_answer")
    busy = sum(1 for c in rows if c.system_outcome == "busy")
    talk = sum(int(c.duration_s or 0) for c in rows if c.answered_live)
    cost = round(float(sum(float(c.cost_estimate or 0.0) for c in rows)), 2)
    stage_moves = sum(1 for c in rows
                      if c.disposition and stage_map.get(c.disposition))

    return {
        "dials": dials,
        "connects": connects,
        "connect_rate": _rate(connects, dials),
        "dm_reached": dm_reached,
        "qualified": qualified,
        "meetings": meetings,
        "booked": meetings + qualified,
        "voicemails_dropped": voicemails,
        "no_answer": no_answer,
        "busy": busy,
        "talk_seconds": talk,
        "talk_pretty": _pretty_seconds(talk),
        "avg_talk_seconds": int(talk / connects) if connects else 0,
        "cost": cost,
        "cost_per_connect": _money(cost, connects),
        "cost_per_meeting": _money(cost, meetings),
        "stage_moves": stage_moves,
        "follow_ups_created": _follow_ups(rows, start, end),
    }


def _follow_ups(rows, start, end):
    """Tasks born out of these calls. Task has no call_id, so the honest join
    is: a task on a lead we called, created inside the same window."""
    lead_ids = {c.lead_id for c in rows if c.lead_id}
    if not lead_ids:
        return 0
    q = Task.query.filter(Task.lead_id.in_(lead_ids))
    if start is not None:
        q = q.filter(Task.created_at >= start)
    if end is not None:
        q = q.filter(Task.created_at <= end)
    return q.count()


# ------------------------------------------------------------- dispositions
def by_disposition(account_id, start, end, **filters):
    """Every disposition, zero-filled, in the order reps see them.

    Zero-filled because a bar chart that silently drops its empty categories
    rearranges itself between refreshes and nobody can read it.

    `pct` is a share of all dials in the window, so the gap up to 100% is the
    dials nobody dispositioned.
    """
    rows = _calls_q(account_id, start, end,
                    user_id=filters.get("user_id"),
                    campaign_id=filters.get("campaign_id")).all()
    counts = {k: 0 for k in DISPOSITION_KEYS}
    for c in rows:
        if c.disposition in counts:
            counts[c.disposition] += 1
    total = len(rows)
    return [{"key": k, "label": DISPOSITION_LABELS.get(k, k),
             "count": counts[k], "pct": _rate(counts[k], total)}
            for k in DISPOSITION_KEYS]


# ---------------------------------------------------------------- the board
def by_rep(account_id, start, end):
    """The leaderboard. Only people who actually dialed appear -- a list padded
    with zeroes for everyone with a login is demoralising and useless."""
    members = User.query.filter(db.or_(User.id == account_id,
                                       User.account_id == account_id)).all()
    out = []
    for u in members:
        rows = _calls_q(account_id, start, end, user_id=u.id).all()
        if not rows:
            continue
        connects = sum(1 for c in rows if c.answered_live)
        scores = [c.score for c in rows if c.score is not None]
        out.append({
            "user_id": u.id,
            "name": u.name or (u.email or f"User {u.id}"),
            "dials": len(rows),
            "connects": connects,
            "connect_rate": _rate(connects, len(rows)),
            "talk_seconds": sum(int(c.duration_s or 0) for c in rows
                                if c.answered_live),
            "meetings": sum(1 for c in rows if _booked(c)),
            # 0.0 rather than None: a leaderboard cell is arithmetic in a
            # template, and None there is a 500 nobody sees until a demo.
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "cost": round(float(sum(float(c.cost_estimate or 0.0)
                                    for c in rows)), 2),
        })
    out.sort(key=lambda r: r["dials"], reverse=True)
    return out


def by_campaign(account_id, start, end):
    """Campaigns with activity in the window, plus anything still live, so a
    running campaign that has not dialed yet is visible rather than missing."""
    camps = Campaign.query.filter_by(account_id=account_id).all()
    out = []
    for c in camps:
        rows = _calls_q(account_id, start, end, campaign_id=c.id).all()
        live = c.status in ("running", "paused")
        if not rows and not live:
            continue
        remaining = CampaignLead.query.filter(
            CampaignLead.campaign_id == c.id,
            CampaignLead.state.in_(["queued", "deferred", "claimed"])).count()
        connects = sum(1 for x in rows if x.answered_live)
        out.append({
            "campaign_id": c.id, "name": c.name, "mode": c.mode,
            "status": c.status, "dials": len(rows), "connects": connects,
            "meetings": sum(1 for x in rows if _booked(x)),
            "cost": round(float(sum(float(x.cost_estimate or 0.0)
                                    for x in rows)), 2),
            "queued_remaining": remaining,
        })
    out.sort(key=lambda r: r["dials"], reverse=True)
    return out


# ---------------------------------------------------------------- numbers
def by_number(account_id, days=7):
    """Per-DID answer rate -- the spam-label early warning.

    Nobody tells you a number has been flagged. The first and only symptom is
    that it stops getting answered while the numbers beside it do fine, so the
    comparison that matters is against the pool's own median, not an absolute.
    """
    cutoff = _now() - timedelta(days=max(1, int(days or 7)))
    today = _now().date()
    numbers = (PhoneNumber.query.filter_by(account_id=account_id)
               .order_by(PhoneNumber.pool, PhoneNumber.e164).all())

    rows = []
    for n in numbers:
        calls = _calls_q(account_id, cutoff, None).filter(
            Call.from_number == n.e164).all()
        dials = len(calls)
        connects = sum(1 for c in calls if c.answered_live)
        rows.append({
            "e164": n.e164, "pretty": n.pretty, "pool": n.pool or "rep",
            "dials": dials, "connects": connects,
            "answer_rate": _rate(connects, dials),
            "calls_today": int(n.calls_today or 0)
            if n.calls_today_date == today else 0,
            "daily_cap": int(n.daily_cap or 120),
            "flagged": False,
        })

    for pool in {r["pool"] for r in rows}:
        rates = sorted(r["answer_rate"] for r in rows
                       if r["pool"] == pool and r["dials"] > 0)
        if not rates:
            continue
        mid = len(rates) // 2
        median = rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2.0
        if median <= 0:
            continue
        for r in rows:
            if r["pool"] != pool:
                continue
            if (r["dials"] >= SPAM_FLAG_MIN_DIALS
                    and r["answer_rate"] < median * SPAM_FLAG_RATIO):
                r["flagged"] = True
    return rows


# --------------------------------------------------------------- AI vs human
def ai_vs_human(account_id, start, end):
    """The question every buyer asks within five minutes: is the robot cheaper
    per meeting than the person? Same denominators on both sides."""
    rows = _calls_q(account_id, start, end).all()
    out = {}
    for key in ("ai", "human"):
        side = [c for c in rows if _is_ai(c) == (key == "ai")]
        connects = sum(1 for c in side if c.answered_live)
        meetings = sum(1 for c in side if _booked(c))
        cost = round(float(sum(float(c.cost_estimate or 0.0)
                               for c in side)), 2)
        out[key] = {"dials": len(side), "connects": connects,
                    "connect_rate": _rate(connects, len(side)),
                    "meetings": meetings, "cost": cost,
                    "cost_per_meeting": _money(cost, meetings)}
    return out


# ------------------------------------------------------------------- hourly
def hourly(account_id, days=7):
    """Twenty-four buckets on the account's own clock, always all twenty-four.

    This is the only report that changes behaviour tomorrow: reps read it and
    move their block. A missing 11am because nothing happened at 11am would
    read as "11am is fine", which is the opposite of the truth.
    """
    cutoff = _now() - timedelta(days=max(1, int(days or 7)))
    buckets = [{"hour": h, "dials": 0, "connects": 0, "connect_rate": 0.0}
               for h in range(24)]
    for c in _calls_q(account_id, cutoff, None).all():
        if not c.started_at:
            continue
        local = to_local(c.started_at)
        b = buckets[local.hour]
        b["dials"] += 1
        if c.answered_live:
            b["connects"] += 1
    for b in buckets:
        b["connect_rate"] = _rate(b["connects"], b["dials"])
    return buckets


# ------------------------------------------------------------- abandon rate
def abandon_rate(account_id, days=30):
    """The 3% number. A regulator asks for it and so does any buyer whose
    compliance team has ever seen a TCPA letter.

    Only an explicit False on `connected_within_2s` counts as an abandon. NULL
    means we never measured a gap -- an AI lane has its agent on the line from
    the first ring -- and counting unmeasured calls as abandoned would turn a
    compliance gauge into a random-number generator.
    """
    cutoff = _now() - timedelta(days=max(1, int(days or 30)))
    rows = _calls_q(account_id, cutoff, None).all()
    answered = [c for c in rows if c.answered_live]
    within = sum(1 for c in answered if c.connected_within_2s is True)
    abandoned = sum(1 for c in answered if c.connected_within_2s is False)
    rate = _rate(abandoned, len(answered), places=2)
    return {"answered_live": len(answered), "connected_within_2s": within,
            "abandoned": abandoned, "rate_pct": rate,
            "over_cap": rate > ABANDON_CAP_PCT, "cap_pct": ABANDON_CAP_PCT}


# ----------------------------------------------------------------- the money
def cost_breakdown(account_id, start, end):
    """Where the money went, split the way the invoices arrive.

    Mirrors calls.estimate_cost line for line, and rounds per call the way
    estimate_cost does before totalling, so this total is the same number
    summary()["cost"] shows. Two different totals on one page is a support
    ticket. Whole minutes per leg, because that is how Twilio bills and a
    per-second model understates a short dial by 2-3x.
    """
    rates = calls_mod.RATES
    s = _settings(account_id)
    recording_on = bool(s.recording_enabled) if s is not None else False

    buckets = {"telephony": 0.0, "ai_voice": 0.0, "transcription": 0.0,
               "llm": 0.0, "recording": 0.0}
    total = 0.0
    for c in _calls_q(account_id, start, end).all():
        mins = int(c.billable_minutes or 0)
        mode = c.mode or "manual"
        if c.vendor_cost:
            telephony = float(c.vendor_cost)
        else:
            telephony = mins * rates["twilio_outbound_min"]
            if mode == "power":
                telephony += mins * (rates["conference_participant_min"] * 2
                                     + rates["client_leg_min"])
            elif mode == "manual":
                telephony += mins * rates["client_leg_min"]
        one = {"telephony": telephony, "ai_voice": 0.0, "transcription": 0.0,
               "llm": 0.0, "recording": 0.0}
        if mode in _AI_MODES:
            one["ai_voice"] = mins * rates["elevenlabs_min"]
            one["llm"] = mins * rates["elevenlabs_llm_min"]
        if c.recording_sid or recording_on:
            one["recording"] = mins * rates["recording_min"]
        if c.transcript and mode in ("manual", "power"):
            one["transcription"] = mins * rates["transcribe_min"]
        if c.summary:
            one["llm"] += rates["llm_per_call"]
        for k, v in one.items():
            buckets[k] += v
        total += round(sum(one.values()), 4)

    out = {k: round(v, 2) for k, v in buckets.items()}
    out["total"] = round(total, 2)
    return out


# ------------------------------------------------------------- daily digest
def daily_digest(account_id, day=None):
    """One day, assembled for an inbox.

    The worker builds this with no request context, so the HTML is inline-styled
    and table-based: every mail client strips a stylesheet, and half of them
    still lay out with tables.
    """
    zone = _zone()
    target = day or datetime.now(zone).date()
    start_local = datetime(target.year, target.month, target.day,
                           tzinfo=zone)
    start = _naive_utc(start_local)
    end = _naive_utc(start_local + timedelta(days=1) - timedelta(microseconds=1))

    head = summary(account_id, start, end)
    reps = by_rep(account_id, start, end)
    moved = _top_leads_moved(account_id, start, end, limit=5)
    label = target.strftime("%A, %B %-d, %Y")
    digest = {
        "date": target.isoformat(),
        "date_label": label,
        "start": start,
        "end": end,
        "summary": head,
        "by_rep": reps,
        "top_leads": moved,
        "subject": (f"Calling recap for {target.strftime('%b %-d')} — "
                    f"{head['dials']} dials, {head['connects']} connects, "
                    f"{head['meetings']} meetings"),
    }
    digest["html"] = _digest_html(digest)
    return digest


def _top_leads_moved(account_id, start, end, limit=5):
    """Leads whose stage actually changed today, best call first. This is the
    part of the email anyone reads."""
    from app import Lead
    stage_map = _stage_map(account_id)
    rows = [c for c in _calls_q(account_id, start, end).all()
            if c.lead_id and c.disposition and stage_map.get(c.disposition)]
    rank = {"meeting_set": 0, "qualified": 1, "dm_reached": 2, "callback": 3}
    rows.sort(key=lambda c: (rank.get(c.disposition, 9), -(c.score or 0)))
    out, seen = [], set()
    for c in rows:
        if c.lead_id in seen:
            continue
        seen.add(c.lead_id)
        lead = db.session.get(Lead, c.lead_id)
        if lead is None:
            continue
        out.append({
            "lead_id": lead.id, "name": lead.name or "",
            "business": lead.business or "",
            "disposition": c.disposition,
            "label": DISPOSITION_LABELS.get(c.disposition, c.disposition),
            "stage": stage_map.get(c.disposition, ""),
            "score": c.score or 0,
            "summary": (c.summary or "")[:220],
        })
        if len(out) >= limit:
            break
    return out


_TD = ("padding:8px 10px;border-bottom:1px solid #E6E8EC;"
       "font:14px/1.45 -apple-system,Segoe UI,Arial,sans-serif;color:#1B2330")
_TH = ("padding:8px 10px;border-bottom:2px solid #D7DBE2;text-align:left;"
       "font:600 12px/1.4 -apple-system,Segoe UI,Arial,sans-serif;"
       "color:#5A6472;text-transform:uppercase;letter-spacing:.04em")


def _esc(v):
    return (str(v or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _stat_cell(label, value):
    return (f'<td style="{_TD};width:20%;text-align:center">'
            f'<div style="font:700 22px/1.2 -apple-system,Segoe UI,Arial,'
            f'sans-serif;color:#1B2330">{_esc(value)}</div>'
            f'<div style="font:11px/1.4 -apple-system,Segoe UI,Arial,'
            f'sans-serif;color:#6B7483;text-transform:uppercase;'
            f'letter-spacing:.05em">{_esc(label)}</div></td>')


def _digest_html(d):
    s = d["summary"]
    parts = [
        '<div style="background:#F6F7F9;padding:22px">',
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        ' style="max-width:640px;margin:0 auto;background:#FFFFFF;'
        'border:1px solid #E6E8EC;border-radius:10px"><tr><td style="padding:20px">',
        '<div style="font:700 17px/1.3 -apple-system,Segoe UI,Arial,sans-serif;'
        'color:#1B2330">Calling recap</div>',
        f'<div style="font:13px/1.5 -apple-system,Segoe UI,Arial,sans-serif;'
        f'color:#6B7483;margin-top:2px">{_esc(d["date_label"])}</div>',
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        ' style="margin-top:16px"><tr>',
        _stat_cell("Dials", s["dials"]),
        _stat_cell("Connects", s["connects"]),
        _stat_cell("Connect rate", f'{s["connect_rate"]}%'),
        _stat_cell("Meetings", s["meetings"]),
        _stat_cell("Cost", f'${s["cost"]:.2f}'),
        '</tr></table>',
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        ' style="margin-top:14px"><tr>',
        _stat_cell("Talk time", s["talk_pretty"]),
        _stat_cell("DM reached", s["dm_reached"]),
        _stat_cell("Qualified", s["qualified"]),
        _stat_cell("Voicemails", s["voicemails_dropped"]),
        _stat_cell("Follow-ups", s["follow_ups_created"]),
        '</tr></table>',
    ]

    if d["by_rep"]:
        parts.append('<div style="font:600 13px/1.4 -apple-system,Segoe UI,'
                     'Arial,sans-serif;color:#1B2330;margin:22px 0 6px">'
                     'By rep</div>')
        parts.append('<table role="presentation" cellpadding="0" cellspacing="0"'
                     ' width="100%"><tr>'
                     f'<th style="{_TH}">Rep</th>'
                     f'<th style="{_TH};text-align:right">Dials</th>'
                     f'<th style="{_TH};text-align:right">Connects</th>'
                     f'<th style="{_TH};text-align:right">Talk</th>'
                     f'<th style="{_TH};text-align:right">Meetings</th></tr>')
        for r in d["by_rep"]:
            parts.append(
                f'<tr><td style="{_TD}">{_esc(r["name"])}</td>'
                f'<td style="{_TD};text-align:right">{r["dials"]}</td>'
                f'<td style="{_TD};text-align:right">{r["connects"]} '
                f'({r["connect_rate"]}%)</td>'
                f'<td style="{_TD};text-align:right">'
                f'{_pretty_seconds(r["talk_seconds"])}</td>'
                f'<td style="{_TD};text-align:right">{r["meetings"]}</td></tr>')
        parts.append('</table>')

    if d["top_leads"]:
        parts.append('<div style="font:600 13px/1.4 -apple-system,Segoe UI,'
                     'Arial,sans-serif;color:#1B2330;margin:22px 0 6px">'
                     'Leads that moved</div>')
        parts.append('<table role="presentation" cellpadding="0" cellspacing="0"'
                     ' width="100%"><tr>'
                     f'<th style="{_TH}">Lead</th>'
                     f'<th style="{_TH}">Outcome</th>'
                     f'<th style="{_TH}">Now</th></tr>')
        for l in d["top_leads"]:
            who = _esc(l["name"])
            if l["business"]:
                who += (f' <span style="color:#6B7483">— '
                        f'{_esc(l["business"])}</span>')
            parts.append(
                f'<tr><td style="{_TD}">{who}</td>'
                f'<td style="{_TD}">{_esc(l["label"])}</td>'
                f'<td style="{_TD}">{_esc(l["stage"])}</td></tr>')
        parts.append('</table>')
    else:
        parts.append('<div style="font:13px/1.5 -apple-system,Segoe UI,Arial,'
                     'sans-serif;color:#6B7483;margin-top:18px">'
                     'No lead changed stage today.</div>')

    parts.append('<div style="font:12px/1.5 -apple-system,Segoe UI,Arial,'
                 'sans-serif;color:#8A929E;margin-top:20px;border-top:'
                 '1px solid #E6E8EC;padding-top:12px">'
                 'Sent by 60 Minute Sites HQ. Costs are estimates from the '
                 'rate table, not a vendor invoice.</div>')
    parts.append('</td></tr></table></div>')
    return "".join(parts)


# Kept importable for a template that wants the raw rate table beside the
# breakdown; reading it from one place stops the UI drifting from the math.
RATES = calls_mod.RATES


def rates_table():
    """The rate card as rows, so the UI can show its working."""
    return [{"key": k, "rate": v} for k, v in sorted(RATES.items())]


def as_json(obj):
    """Small convenience for embedding a report in a <script> tag."""
    return json.dumps(obj, default=str)
