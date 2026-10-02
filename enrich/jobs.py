"""The job runner.

Work happens in small chunks, driven by whoever is watching: the browser polls
for the next chunk while the page is open, and the worker picks jobs up if one
is running. Either way the state lives in the database, so closing the tab
pauses a job rather than losing it, and reopening it carries on.
"""
import json
from datetime import datetime, timezone

from app import Media, db

from enrich import core
from enrich.models import EnrichJob, EnrichRow, EnrichSettings


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


CHUNK = 5          # rows per tick; small enough that a tick always returns fast


def get_settings(account_id, create=True):
    row = EnrichSettings.query.filter_by(account_id=account_id).first()
    if row is None and create:
        row = EnrichSettings(account_id=account_id)
        db.session.add(row)
        db.session.commit()
    return row


# ------------------------------------------------------------------ create
def create_job(account_id, kind, name, filename, data, user_id=None):
    """Read the upload, store it, and lay out one row per spreadsheet line."""
    headers, rows = core.read_sheet(data, filename)
    media = Media(owner_id=account_id, filename=filename[:200],
                  mimetype="text/csv", data=data)
    db.session.add(media)
    db.session.flush()
    job = EnrichJob(account_id=account_id, kind=kind,
                    name=(name or filename or "Untitled")[:200],
                    source_filename=filename[:300], source_media_id=media.id,
                    columns_json=json.dumps(headers), total=len(rows),
                    created_by=user_id, status="draft")
    db.session.add(job)
    db.session.flush()
    for i, r in enumerate(rows):
        db.session.add(EnrichRow(job_id=job.id, account_id=account_id, idx=i,
                                 input_json=json.dumps(r), state="pending"))
    db.session.commit()
    return job, headers, rows[:5]


def configure(job, mapping=None, config=None, model=None, name=None):
    if mapping is not None:
        job.mapping_json = json.dumps(mapping)
    if config is not None:
        job.config_json = json.dumps(config)
    if model:
        job.model = model[:60]
    if name:
        job.name = name[:200]
    db.session.commit()
    return job


def start(job):
    job.status = "running"
    job.started_at = job.started_at or _now()
    job.error = ""
    db.session.commit()
    return job


def pause(job):
    job.status = "paused"
    db.session.commit()
    return job


def reset_failures(job):
    """Retry just the rows that failed, without redoing the work that worked."""
    n = EnrichRow.query.filter_by(job_id=job.id, state="failed").update(
        {"state": "pending", "error": ""}, synchronize_session=False)
    job.failed = max(0, (job.failed or 0) - n)
    job.status = "running"
    db.session.commit()
    return n


# -------------------------------------------------------------------- run
def tick(job, limit=CHUNK):
    """Process up to `limit` pending rows. Returns a progress dict the UI
    renders directly."""
    settings = get_settings(job.account_id)
    if job.status != "running":
        return progress(job, note=f"Job is {job.status}.")
    if not settings.has_key:
        job.status = "paused"
        job.error = "Add your OpenAI key before running this."
        db.session.commit()
        return progress(job, note=job.error)
    if over_cap(settings):
        job.status = "paused"
        job.error = (f"Monthly spend cap of {core.money(settings.monthly_spend_cap)} "
                     f"reached. Raise it in Settings to carry on.")
        db.session.commit()
        return progress(job, note=job.error)

    handler = _handler(job.kind)
    if handler is None:
        job.status = "failed"
        job.error = f"Unknown job type: {job.kind}"
        db.session.commit()
        return progress(job)

    rows = (EnrichRow.query.filter_by(job_id=job.id, state="pending")
            .order_by(EnrichRow.idx).limit(limit).all())
    if not rows:
        job.status = "done"
        job.finished_at = job.finished_at or _now()
        db.session.commit()
        return progress(job, note="Finished.")

    for row in rows:
        try:
            handler(job, row, settings)
        except Exception as e:                       # never strand a job
            row.state = "failed"
            row.error = f"{type(e).__name__}: {e}"[:400]
        row.done_at = _now()
        if row.state == "done":
            job.done = (job.done or 0) + 1
            if row.reused:
                job.reused = (job.reused or 0) + 1
        elif row.state == "skipped":
            job.done = (job.done or 0) + 1
        else:
            job.failed = (job.failed or 0) + 1
        job.cost = round((job.cost or 0) + (row.cost or 0), 6)
        db.session.commit()

    add_spend(settings, sum(r.cost or 0 for r in rows))
    if job.remaining <= 0:
        job.status = "done"
        job.finished_at = _now()
    db.session.commit()
    return progress(job)


def _handler(kind):
    if kind == "scrape":
        from enrich.scrape import process_row
        return process_row
    if kind == "personalize":
        from enrich.personalize import process_row
        return process_row
    return None


def progress(job, note=""):
    return {"ok": True, "id": job.id, "status": job.status, "pct": job.pct,
            "done": job.done or 0, "failed": job.failed or 0,
            "reused": job.reused or 0, "total": job.total or 0,
            "remaining": job.remaining, "cost": round(job.cost or 0, 4),
            "cost_pretty": core.money(job.cost), "error": job.error or "",
            "note": note}


# ------------------------------------------------------------------ spend
def _month():
    return _now().strftime("%Y-%m")


def add_spend(settings, amount):
    if not amount:
        return
    if settings.spend_month != _month():
        settings.spend_month = _month()
        settings.spend_this_month = 0.0
    settings.spend_this_month = round((settings.spend_this_month or 0)
                                      + float(amount), 6)
    db.session.commit()


def over_cap(settings):
    if not settings.monthly_spend_cap:
        return False
    if settings.spend_month != _month():
        return False
    return (settings.spend_this_month or 0) >= settings.monthly_spend_cap


# ----------------------------------------------------------------- export
def export(job, only_done=False):
    """-> (filename, bytes). Original columns first, then whatever the job
    produced, so the sheet drops straight back into whatever they use."""
    rows = EnrichRow.query.filter_by(job_id=job.id).order_by(EnrichRow.idx).all()
    base = job.columns
    extra = []
    for r in rows:
        for k in r.output.keys():
            if k not in extra and k not in base:
                extra.append(k)
    headers = base + extra + ["enrich_status"]
    out = []
    for r in rows:
        if only_done and r.state != "done":
            continue
        d = dict(r.input)
        d.update(r.output)
        d["enrich_status"] = r.error if r.state == "failed" else r.state
        out.append(d)
    stamp = _now().strftime("%Y-%m-%d")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in job.name)[:50]
    return f"{safe or 'enriched'}-{stamp}.csv", core.write_csv(headers, out)


def delete_job(job):
    EnrichRow.query.filter_by(job_id=job.id).delete(synchronize_session=False)
    if job.source_media_id:
        m = db.session.get(Media, job.source_media_id)
        if m:
            db.session.delete(m)
    db.session.delete(job)
    db.session.commit()
