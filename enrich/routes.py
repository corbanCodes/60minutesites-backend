"""The enrichment screens.

Three ideas run through every route here:

* The customer's own OpenAI key pays for everything, so the cost of a run is
  shown before the button that spends it, and the key itself is never
  rendered, logged, flashed or returned -- only its last four characters.
* A job lives in the database, not in the page. Closing the tab pauses a run;
  reopening it carries on. That is why /tick exists and why the setup screen
  saves itself as you type.
* Nothing in here raises at the customer. A bad upload, an unreachable
  vendor and a half-configured job each get a sentence they can act on.
"""
import json
from datetime import datetime, timezone

from flask import (Response, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from app import db

from enrich import bp, core, jobs, personalize, scrape
from enrich.models import (DEFAULT_MODEL, JOB_KINDS, MODELS, EnrichJob,
                           EnrichRow, PromptTemplate, ScrapedSite)

# How far down the sheet the setup screen looks for a row worth previewing.
PREVIEW_SCAN = 25
RECENT_JOBS = 8
SITES_PAGE = 200

# Headers that almost always mean "the company's website". Matched as
# substrings so "Company Website URL" and "domain_name" both land.
WEBSITE_HINTS = ("website", "url", "domain", "site", "web")


@bp.context_processor
def _enrich_globals():
    """money() and the price table for every enrichment template.

    Blueprint-scoped on purpose: a global filter called "money" would be a
    name every other template in HQ now has to avoid.
    """
    return {"money": core.money, "MODELS": MODELS}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _month():
    return _now().strftime("%Y-%m")


# ----------------------------------------------------------------- lookups
def _settings():
    return jobs.get_settings(g.account_id)


def _job(job_id):
    """A job, or a 404. Scoped by account on every single read: an id in the
    URL is a guess anyone can make."""
    job = db.session.get(EnrichJob, job_id)
    if job is None or job.account_id != g.account_id:
        abort(404)
    return job


def _spend_this_month(settings):
    """Zero in a new month. The stored figure is only meaningful alongside
    the month it was accumulated in."""
    if not settings or settings.spend_month != _month():
        return 0.0
    return float(settings.spend_this_month or 0)


def _spend_view(settings):
    spent = _spend_this_month(settings)
    cap = float(settings.monthly_spend_cap or 0) if settings else 0
    pct = min(100, round(100 * spent / cap)) if cap else 0
    return {"spent": spent, "spent_pretty": core.money(spent),
            "cap": cap, "cap_pretty": core.money(cap) if cap else "",
            "pct": pct, "over": bool(cap and spent >= cap)}


def _readiness(settings):
    """What will not work right now, and the step that fixes it.

    Same promise the dialer makes: name the missing thing and link to it,
    never a dead button and never a silent failure half way down a run.
    """
    out = []
    if not settings or not settings.openai_key_enc:
        out.append({"feature": "Research and email writing",
                    "needs": "your OpenAI key",
                    "fix": "Nothing here will run until you add an OpenAI "
                           "key. It is yours, you are billed by OpenAI "
                           "directly, and we never mark it up."})
    elif not settings.verified_at:
        out.append({"feature": "Research and email writing",
                    "needs": "a working OpenAI key",
                    "fix": settings.verify_error
                           or "Your OpenAI key has not been tested yet. "
                              "Test it before starting a run."})
    view = _spend_view(settings)
    if view["over"]:
        out.append({"feature": "Every job",
                    "needs": "more room under your spend cap",
                    "fix": f"You have spent {view['spent_pretty']} of your "
                           f"{view['cap_pretty']} cap this month, so jobs "
                           f"will pause instead of running."})
    return out


def _guess_website_column(headers):
    """The column that probably holds the website. A guess the customer can
    see and change beats a mapping step they have to think about."""
    for h in headers or []:
        low = str(h).strip().lower()
        for hint in WEBSITE_HINTS:
            if hint in low:
                return h
    return ""


def _sample_row(job):
    """The first row with something in it.

    A preview built from a blank first row teaches nobody anything, and real
    exports start with a blank row more often than anyone admits.
    """
    rows = (EnrichRow.query.filter_by(job_id=job.id)
            .order_by(EnrichRow.idx).limit(PREVIEW_SCAN).all())
    for r in rows:
        data = r.input
        if any(str(v).strip() for v in data.values()):
            return data
    return rows[0].input if rows else {}


def _recent_rows(job, limit=6):
    """The last few finished rows, with what they actually produced, so the
    run screen shows work rather than a number going up."""
    rows = (EnrichRow.query.filter(EnrichRow.job_id == job.id,
                                   EnrichRow.state != "pending")
            .order_by(EnrichRow.done_at.desc(), EnrichRow.idx.desc())
            .limit(limit).all())
    out = []
    for r in rows:
        data = r.input
        label = ""
        for key in ("Company", "company", "Name", "name", "First Name",
                    "Email", "email"):
            if str(data.get(key, "")).strip():
                label = str(data[key]).strip()
                break
        if not label:
            label = r.domain or f"Row {r.idx + 1}"
        fields = [{"name": k, "value": str(v)[:900]}
                  for k, v in r.output.items() if str(v).strip()]
        out.append({"idx": r.idx + 1, "state": r.state, "label": label[:80],
                    "reused": bool(r.reused), "error": (r.error or "")[:300],
                    "cost": core.money(r.cost), "fields": fields})
    return out


# -------------------------------------------------------------------- home
@bp.route("/")
def home():
    settings = _settings()
    recent = (EnrichJob.query.filter_by(account_id=g.account_id)
              .order_by(EnrichJob.created_at.desc()).limit(RECENT_JOBS).all())
    sites = ScrapedSite.query.filter_by(account_id=g.account_id).count()
    return render_template(
        "enrich/home.html", active="enrich", tab="home", s=settings,
        blockers=_readiness(settings), spend=_spend_view(settings),
        recent=recent, saved_sites=sites,
        templates=personalize.list_templates(g.account_id))


# ---------------------------------------------------------------- settings
@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    settings = _settings()
    if request.method == "POST":
        action = (request.form.get("action") or "save").strip()
        if action == "key":
            _save_key(settings)
        elif action == "test":
            _test_key(settings)
        elif action == "import":
            _import_dialer_key(settings)
        elif action == "forget":
            settings.openai_key_enc = None
            settings.openai_last4 = ""
            settings.verified_at = None
            settings.verify_error = ""
            settings.available_models = ""
            db.session.commit()
            flash("That key has been removed.")
        else:
            _save_prefs(settings)
        return redirect(url_for("enrich.settings_page"))

    return render_template(
        "enrich/settings.html", active="enrich", tab="settings", s=settings,
        models=settings.models, all_models=MODELS,
        spend=_spend_view(settings), dialer_key=_dialer_key_available(),
        blockers=_readiness(settings))


def _save_key(settings):
    """Store and verify in one step. A key that is saved but never tested is
    a run that fails on row one, so there is no way to save without testing."""
    key = (request.form.get("openai_key") or "").strip()
    if not key:
        flash("Paste your OpenAI key first.", "error")
        return
    result = core.verify_key(key)
    settings.set_key(key)
    _apply_verify(settings, result)
    if result.get("ok"):
        flash("That key works. It is stored encrypted and only the last four "
              "characters are ever shown.")
    else:
        # The error comes from OpenAI and is about the key, never the key.
        flash(result.get("error") or "OpenAI rejected that key.", "error")


def _test_key(settings):
    key = None
    try:
        key = settings.key()
    except Exception:
        key = None
    if not key:
        flash("There is no key saved to test.", "error")
        return
    result = core.verify_key(key)
    _apply_verify(settings, result)
    flash("That key works." if result.get("ok")
          else (result.get("error") or "OpenAI rejected that key."),
          "" if result.get("ok") else "error")


def _apply_verify(settings, result):
    """Record the outcome and the usable model list, so the model picker only
    ever offers models this key can actually call."""
    if result.get("ok"):
        settings.verified_at = _now()
        settings.verify_error = ""
        settings.available_models = json.dumps(result.get("models") or [])
        allowed = [m["id"] for m in settings.models]
        if settings.default_model not in allowed and allowed:
            settings.default_model = allowed[0]
    else:
        settings.verified_at = None
        settings.verify_error = (result.get("error") or "")[:300]
    db.session.commit()


def _dialer_key_available():
    """-> the last 4 of the calling module's OpenAI key, or "".

    Offered rather than imported automatically: it is the customer's money
    and the customer's key, so copying it between modules is their call.
    """
    try:
        from dialer.models import DialerSettings
        row = DialerSettings.query.filter_by(account_id=g.account_id).first()
    except Exception:
        return ""
    if row is None or (row.llm_provider or "openai") != "openai":
        return ""
    if not row.llm_key_enc or not row.llm_verified_at:
        return ""
    return row.llm_last4 or "key"


def _import_dialer_key(settings):
    try:
        from dialer.models import DialerSettings
        row = DialerSettings.query.filter_by(account_id=g.account_id).first()
    except Exception:
        row = None
    key = None
    if row is not None and row.llm_key_enc:
        from dialer import crypto
        key = crypto.decrypt(row.llm_key_enc)
    if not key:
        flash("There is no verified OpenAI key on your calling setup to "
              "copy.", "error")
        return
    result = core.verify_key(key)
    settings.set_key(key)
    _apply_verify(settings, result)
    flash("Copied the OpenAI key from your calling setup." if result.get("ok")
          else (result.get("error") or "That key did not work here."),
          "" if result.get("ok") else "error")


def _save_prefs(settings):
    model = (request.form.get("default_model") or "").strip()
    if model in {m["id"] for m in MODELS}:
        settings.default_model = model
    cap = (request.form.get("monthly_spend_cap") or "").strip()
    if cap == "":
        settings.monthly_spend_cap = None
    else:
        try:
            value = float(cap)
            settings.monthly_spend_cap = value if value > 0 else None
        except ValueError:
            flash("The spend cap has to be a number of dollars, like 25.",
                  "error")
    timeout = (request.form.get("scrape_timeout") or "").strip()
    if timeout:
        try:
            settings.scrape_timeout = max(5, min(60, int(float(timeout))))
        except ValueError:
            flash("The page timeout has to be a number of seconds.", "error")
    db.session.commit()
    flash("Settings saved.")


# -------------------------------------------------------------- new upload
@bp.route("/jobs/new", methods=["POST"])
def job_new():
    kind = (request.form.get("kind") or "scrape").strip()
    if kind not in JOB_KINDS:
        kind = "scrape"
    name = (request.form.get("name") or "").strip()
    upload = request.files.get("file")
    if upload is None or not (upload.filename or "").strip():
        flash("Choose a CSV or spreadsheet to upload.", "error")
        return redirect(url_for("enrich.home"))
    data = upload.read()
    if not data:
        flash("That file came through empty. Try saving it again as CSV.",
              "error")
        return redirect(url_for("enrich.home"))
    try:
        job, _headers, _sample = jobs.create_job(
            g.account_id, kind, name, upload.filename, data,
            user_id=getattr(g.member, "id", None))
    except ValueError as e:
        # core.read_sheet raises these deliberately, already in plain English.
        flash(str(e), "error")
        return redirect(url_for("enrich.home"))
    except Exception as e:
        db.session.rollback()
        flash(f"That file could not be read ({type(e).__name__}). Save it as "
              f"CSV and try again.", "error")
        return redirect(url_for("enrich.home"))
    return redirect(url_for("enrich.job_setup", job_id=job.id))


# -------------------------------------------------------------- the setup
@bp.route("/jobs/<int:job_id>/setup", methods=["GET", "POST"])
def job_setup(job_id):
    job = _job(job_id)
    if job.status in ("running", "done"):
        return redirect(url_for("enrich.job_view", job_id=job.id))
    settings = _settings()

    if request.method == "POST":
        _save_setup(job, settings)
        if (request.form.get("action") or "") == "start":
            if not settings.has_key:
                flash("Add your OpenAI key before starting a run.", "error")
                return redirect(url_for("enrich.job_setup", job_id=job.id))
            jobs.start(job)
            return redirect(url_for("enrich.job_view", job_id=job.id))
        flash("Saved.")
        return redirect(url_for("enrich.job_setup", job_id=job.id))

    state = _setup_state(job, settings)
    page = ("enrich/setup_personalize.html" if job.kind == "personalize"
            else "enrich/setup_scrape.html")
    return render_template(page, active="enrich", tab="home", job=job, s=settings,
                           models=settings.models, blockers=_readiness(settings),
                           spend=_spend_view(settings),
                           headers=job.columns, cfg=state["config"],
                           mapping=job.mapping, state=state,
                           templates=personalize.list_templates(g.account_id),
                           steers=personalize.VARIANT_STEERS,
                           max_variants=personalize.MAX_VARIANTS)


def _form_config(job, source):
    """Build the stored config from a form post or a preview payload.

    One function for both so what the live preview quoted and what the Start
    button runs can never be two different configurations.
    """
    def get(name, default=""):
        value = source.get(name, default)
        return "" if value is None else value

    model = str(get("model")).strip()
    if model not in {m["id"] for m in MODELS}:
        model = job.model or DEFAULT_MODEL

    if job.kind == "personalize":
        config = {
            "model": model,
            "subject_prompt": str(get("subject_prompt")),
            "body_prompt": str(get("body_prompt")),
            "separate_subject": _truthy(source.get("separate_subject"), True),
            "variants": get("variants", 1),
            "tone": str(get("tone")).strip(),
            "max_words": get("max_words", 120),
            "sender_name": str(get("sender_name")).strip(),
            "sender_company": str(get("sender_company")).strip(),
            "extra_rules": str(get("extra_rules")).strip(),
        }
        return config, {}, model

    config = {"model": model, "instructions": str(get("instructions")).strip()}
    mapping = {"website": str(get("website_column")).strip()}
    return config, mapping, model


def _truthy(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _save_setup(job, settings):
    config, mapping, model = _form_config(job, request.form)
    name = (request.form.get("name") or "").strip()
    jobs.configure(job, mapping=mapping or None, config=config, model=model,
                   name=name or None)


def _setup_state(job, settings):
    """Everything the setup screen needs to render itself and to quote a
    price: the sample row, the filled preview, the problems and the estimate.

    Wrapped so hard because this runs on every keystroke through /preview. A
    traceback here would take the screen down over a half-typed prompt.
    """
    config = job.config or {}
    mapping = job.mapping or {}
    headers = job.columns
    sample = _sample_row(job)
    state = {"config": config, "mapping": mapping, "sample": sample,
             "problems": [], "warnings": [], "preview": {}, "estimate": {}}

    if job.kind == "personalize":
        if not config:
            config = {"separate_subject": True, "variants": 1,
                      "max_words": 120, "model": job.model or DEFAULT_MODEL}
            state["config"] = config
        try:
            checked = personalize.validate_config(config, headers)
        except Exception as e:
            checked = {"problems": [f"That prompt could not be checked "
                                    f"({type(e).__name__})."], "warnings": []}
        state["problems"] = list(checked.get("problems") or [])
        state["warnings"] = list(checked.get("warnings") or [])
        state["preview"] = _personalize_preview(config, sample)
        try:
            state["estimate"] = personalize.estimate_job(job, settings)
        except Exception:
            state["estimate"] = {}
    else:
        column = mapping.get("website") or _guess_website_column(headers)
        state["mapping"] = {"website": column}
        state["preview"] = _scrape_preview(column, sample)
        try:
            state["estimate"] = scrape.estimate_job(job, settings)
        except Exception:
            state["estimate"] = {}
        state["problems"], state["warnings"] = _scrape_checks(
            column, headers, state["estimate"])

    _cap_warning(state, settings)
    if not settings.has_key:
        state["problems"].append(
            "Add your OpenAI key in Settings -- nothing can run without it.")
    return state


def _cap_warning(state, settings):
    est = state.get("estimate") or {}
    cap = float(getattr(settings, "monthly_spend_cap", 0) or 0)
    if not cap:
        return
    spent = _spend_this_month(settings)
    total = float(est.get("total") or 0)
    if spent >= cap:
        state["problems"].append(
            f"You have already spent {core.money(spent)} of your "
            f"{core.money(cap)} monthly cap. Raise it in Settings or this job "
            f"will pause on the first row.")
    elif spent + total > cap:
        state["warnings"].append(
            f"This run is estimated at {core.money(total)} and you have "
            f"{core.money(cap - spent)} left under your cap, so it will pause "
            f"part-way through.")


def _scrape_checks(column, headers, estimate):
    problems, warnings = [], []
    if not column:
        problems.append("Choose which column holds the website address.")
    elif headers and column not in headers:
        problems.append(f"There is no column called \"{column}\" in this "
                        f"sheet any more. Pick one from the list.")
    unique = estimate.get("unique_domains")
    without = estimate.get("rows_without_website") or 0
    if column and unique == 0:
        problems.append(f"Nothing in \"{column}\" looks like a company "
                        f"website, so there would be nothing to research.")
    elif without:
        verb = "rows have" if without != 1 else "row has"
        warnings.append(f"{without} {verb} no usable website and will be "
                        f"skipped, not charged.")
    return problems, warnings


def _personalize_preview(config, row):
    """The customer's own prompt with this row's values dropped in.

    The whole point of the screen: seeing "Hey Dana" instead of
    "Hey {First Name}" is what catches a wrong column name before four
    hundred rows have been paid for.
    """
    out = {"row": {k: str(v)[:160] for k, v in (row or {}).items()
                   if str(v).strip()}}
    body, missing_b = core.fill(str(config.get("body_prompt") or ""), row or {})
    subject, missing_s = core.fill(str(config.get("subject_prompt") or ""),
                                   row or {})
    out["body"] = body
    out["subject"] = subject
    out["missing"] = list(dict.fromkeys(missing_b + missing_s))
    try:
        kind = "body" if _truthy(config.get("separate_subject"), True) else "both"
        system, user = personalize.build_messages(
            dict(config, variant=1, variant_count=config.get("variants", 1)),
            row or {}, kind)
        out["system"] = system
        out["user"] = user
    except Exception:
        out["system"] = ""
        out["user"] = ""
    return out


def _scrape_preview(column, row):
    raw = str((row or {}).get(column, "")) if column else ""
    domain = scrape.normalize_domain(raw) if raw else ""
    return {"raw": raw[:160], "domain": domain,
            "row": {k: str(v)[:160] for k, v in (row or {}).items()
                    if str(v).strip()}}


@bp.route("/jobs/<int:job_id>/preview", methods=["POST"])
def job_preview(job_id):
    """The live half of the setup screen.

    It saves as it quotes. That is deliberate: the estimate a customer reads
    and the configuration the Start button runs come from the same stored
    row, so there is no window in which the screen says $0.14 and the job
    bills something else. It also means a closed tab loses nothing.
    """
    job = _job(job_id)
    if job.status in ("running", "done"):
        return jsonify({"ok": False,
                        "error": f"This job is {job.status}."}), 409
    payload = request.get_json(silent=True) or {}
    settings = _settings()
    try:
        config, mapping, model = _form_config(job, payload)
        jobs.configure(job, mapping=mapping or None, config=config,
                       model=model)
        state = _setup_state(job, settings)
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False,
                        "error": f"That could not be checked "
                                 f"({type(e).__name__})."}), 200
    est = state.get("estimate") or {}
    return jsonify({"ok": True, "problems": state["problems"],
                    "warnings": state["warnings"],
                    "preview": state["preview"], "estimate": est,
                    "can_start": not state["problems"]})


# ------------------------------------------------------------------- runs
@bp.route("/jobs/<int:job_id>")
def job_view(job_id):
    job = _job(job_id)
    settings = _settings()
    if job.status == "draft":
        return redirect(url_for("enrich.job_setup", job_id=job.id))
    return render_template("enrich/job.html", active="enrich", tab="home", job=job,
                           s=settings, rows=_recent_rows(job, 6),
                           progress=jobs.progress(job),
                           spend=_spend_view(settings),
                           blockers=_readiness(settings))


@bp.route("/jobs/<int:job_id>/start", methods=["POST"])
def job_start(job_id):
    job = _job(job_id)
    settings = _settings()
    if not settings.has_key:
        flash("Add your OpenAI key in Settings before starting a run.",
              "error")
        return redirect(url_for("enrich.settings_page"))
    jobs.start(job)
    return redirect(url_for("enrich.job_view", job_id=job.id))


@bp.route("/jobs/<int:job_id>/pause", methods=["POST"])
def job_pause(job_id):
    job = _job(job_id)
    jobs.pause(job)
    flash("Paused. Nothing is lost -- press Resume whenever you like.")
    return redirect(url_for("enrich.job_view", job_id=job.id))


@bp.route("/jobs/<int:job_id>/retry-failed", methods=["POST"])
def job_retry_failed(job_id):
    job = _job(job_id)
    n = jobs.reset_failures(job)
    flash(f"{n} row{'s' if n != 1 else ''} queued again."
          if n else "There are no failed rows to retry.")
    return redirect(url_for("enrich.job_view", job_id=job.id))


@bp.route("/jobs/<int:job_id>/tick", methods=["POST"])
def job_tick(job_id):
    """One chunk of work, driven by the open browser.

    There is no worker process behind this on purpose. The page polls here
    about once a second while a job is running, and each call does a handful
    of rows and returns the progress. That is how the work gets done on a
    plain web dyno, and it is why closing the tab pauses a job instead of
    breaking it: the rows that were finished stay finished.
    """
    job = _job(job_id)
    try:
        data = jobs.tick(job)
    except Exception as e:
        db.session.rollback()
        data = {"ok": False, "id": job.id, "status": job.status,
                "error": f"That chunk failed ({type(e).__name__}).",
                "pct": job.pct, "done": job.done or 0,
                "failed": job.failed or 0, "reused": job.reused or 0,
                "total": job.total or 0, "remaining": job.remaining,
                "cost": round(job.cost or 0, 4),
                "cost_pretty": core.money(job.cost), "note": ""}
    data["rows"] = _recent_rows(job, 6)
    data["spend"] = _spend_view(_settings())
    return jsonify(data)


@bp.route("/jobs/<int:job_id>/export.csv")
def job_export(job_id):
    job = _job(job_id)
    try:
        filename, blob = jobs.export(job)
    except Exception as e:
        flash(f"That export could not be built ({type(e).__name__}).", "error")
        return redirect(url_for("enrich.job_view", job_id=job.id))
    safe = filename.replace('"', "")
    return Response(blob, mimetype="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="{safe}"',
                             "Content-Length": str(len(blob))})


@bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
def job_delete(job_id):
    job = _job(job_id)
    name = job.name
    try:
        jobs.delete_job(job)
    except Exception as e:
        db.session.rollback()
        flash(f"That job could not be deleted ({type(e).__name__}).", "error")
        return redirect(url_for("enrich.job_view", job_id=job_id))
    flash(f"Deleted \"{name}\". Your saved research was kept.")
    return redirect(url_for("enrich.home"))


# ------------------------------------------------------------- the library
@bp.route("/sites")
def sites():
    q = (request.args.get("q") or "").strip()
    query = ScrapedSite.query.filter_by(account_id=g.account_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(db.or_(db.func.lower(ScrapedSite.domain).like(like),
                                    db.func.lower(ScrapedSite.title).like(like),
                                    db.func.lower(ScrapedSite.summary).like(like)))
    total = ScrapedSite.query.filter_by(account_id=g.account_id).count()
    rows = query.order_by(ScrapedSite.scraped_at.desc()).limit(SITES_PAGE).all()
    # Counted over the whole library, not the current page: it is a fact about
    # the asset they are building, and a search must not appear to shrink it.
    saved = (ScrapedSite.query
             .filter(ScrapedSite.account_id == g.account_id,
                     ScrapedSite.summary != "", ScrapedSite.summary.isnot(None))
             .count())
    return render_template("enrich/sites.html", active="enrich", tab="sites",
                           sites=rows,
                           total=total, q=q, shown=len(rows), with_summary=saved,
                           s=_settings())


@bp.route("/sites/<int:site_id>/resummarise", methods=["POST"])
def site_resummarise(site_id):
    site = db.session.get(ScrapedSite, site_id)
    if site is None or site.account_id != g.account_id:
        abort(404)
    settings = _settings()
    if not settings.has_key:
        flash("Add your OpenAI key in Settings first.", "error")
        return redirect(url_for("enrich.settings_page"))
    try:
        fresh, _reused = scrape.get_or_scrape(
            g.account_id, settings, site.domain,
            model=settings.default_model, force=True)
    except Exception as e:
        db.session.rollback()
        fresh = None
        flash(f"That site could not be read again ({type(e).__name__}).",
              "error")
    if fresh is not None:
        jobs.add_spend(settings, fresh.cost or 0)
        if fresh.status == "ok" and fresh.summary:
            flash(f"Fetched {fresh.domain} again for "
                  f"{core.money(fresh.cost)}.")
        else:
            flash(fresh.error or f"{site.domain} could not be read.", "error")
    return redirect(url_for("enrich.sites", q=request.form.get("q") or None))


@bp.route("/sites/<int:site_id>/delete", methods=["POST"])
def site_delete(site_id):
    site = db.session.get(ScrapedSite, site_id)
    if site is None or site.account_id != g.account_id:
        abort(404)
    domain = site.domain
    try:
        db.session.delete(site)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"That could not be removed ({type(e).__name__}).", "error")
        return redirect(url_for("enrich.sites"))
    flash(f"Removed {domain}. The next job that needs it will fetch it again.")
    return redirect(url_for("enrich.sites"))


# ------------------------------------------------------------- the prompts
@bp.route("/templates")
def templates_page():
    rows = (PromptTemplate.query
            .filter_by(account_id=g.account_id, kind="personalize")
            .order_by(PromptTemplate.name).all())
    return render_template("enrich/templates.html", active="enrich",
                           tab="prompts", templates=rows,
                           unsaved=personalize.UNSAVED_FIELDS,
                           s=_settings())


@bp.route("/templates/save", methods=["POST"])
def template_save():
    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or "").strip()
    config = payload.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            config = {}
    if not isinstance(config, dict):
        config = {k: payload.get(k) for k in
                  ("subject_prompt", "body_prompt", "separate_subject",
                   "variants", "tone", "max_words")}
    config["separate_subject"] = _truthy(config.get("separate_subject"), True)
    result = personalize.save_template(g.account_id, name, config,
                                       model=payload.get("model"))
    if request.is_json:
        return jsonify(result)
    flash(result.get("error") or f"Saved \"{result.get('name')}\".",
          "error" if not result.get("ok") else "")
    return redirect(request.referrer or url_for("enrich.templates_page"))


@bp.route("/templates/<int:template_id>/load")
def template_load(template_id):
    return jsonify(personalize.load_template(g.account_id, template_id))


@bp.route("/templates/<int:template_id>/delete", methods=["POST"])
def template_delete(template_id):
    row = PromptTemplate.query.filter_by(id=template_id,
                                         account_id=g.account_id).first()
    if row is None:
        abort(404)
    name = row.name
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"That could not be deleted ({type(e).__name__}).", "error")
        return redirect(url_for("enrich.templates_page"))
    flash(f"Deleted \"{name}\".")
    return redirect(url_for("enrich.templates_page"))
