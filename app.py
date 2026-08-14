"""60 Minute Sites — Backend HQ v4
Admin + customer accounts · CRM (pipeline, board, tasks, revenue) · Forms
(Formspree-style, feeds the CRM) · WYSIWYG site builder on real 60MS templates
(+ AI text/design) · GitHub→Netlify publishing · Flipbooks.

Persistence: set DATABASE_URL (Railway Postgres) and everything survives
deploys. Falls back to local SQLite (data.db) for development.
AI: set OPENAI_API_KEY (and optionally OPENAI_MODEL) to enable editor AI.
Publishing: set GITHUB_TOKEN (fine-grained PAT, Contents read/write) once and
every editor Save commits to the linked repo. APP_TZ controls display times.
"""
import base64
import io
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import pymupdf as fitz  # PyMuPDF
import requests as http
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for, Response)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------- app config
app = Flask(__name__, static_folder="site", static_url_path="")

# absolute sqlite path so the dev DB is the same no matter where you launch from
_here = os.path.dirname(os.path.abspath(__file__))
db_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(_here, "instance", "data.db"))
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
os.makedirs(os.path.join(_here, "instance"), exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme60")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
RESEND_KEY = (os.environ.get("RESEND_API_KEY") or os.environ.get("RESEND_API")
              or os.environ.get("resend-api") or os.environ.get("resend_api", ""))
RESEND_FROM = os.environ.get("RESEND_FROM", "60MS HQ <onboarding@resend.dev>")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
try:
    LOCAL_TZ = ZoneInfo(os.environ.get("APP_TZ", "America/Los_Angeles"))
except Exception:
    LOCAL_TZ = timezone.utc

db = SQLAlchemy(app)

LEAD_STATUSES = ["New", "Contacted", "Booked", "Built", "Client", "Dead"]
STATUS_COLORS = {
    "New": "#2E86DE", "Contacted": "#9A6B14", "Booked": "#E85D2A",
    "Built": "#8E44AD", "Client": "#2E7D4F", "Dead": "#888888",
}
# how much of a deal's monthly value counts toward the weighted pipeline
STATUS_WEIGHTS = {"New": 0.10, "Contacted": 0.25, "Booked": 0.50, "Built": 0.75}
LEAD_FIELDS = ["name", "phone", "email", "business", "business_type"]
TASK_KINDS = ["Call", "Text", "Email", "Meeting", "Follow-up", "To-do"]
TASK_ICONS = {"Call": "bi-telephone", "Text": "bi-chat-left-dots",
              "Email": "bi-envelope", "Meeting": "bi-people",
              "Follow-up": "bi-arrow-repeat", "To-do": "bi-check2-square"}


# -------------------------------------------------------------------- models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    phone = db.Column(db.String(40), default="")
    password_hash = db.Column(db.String(300), nullable=False)
    monthly_price = db.Column(db.Float, nullable=True)  # what they pay per month
    setup_fee = db.Column(db.Float, nullable=True)      # one-time
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)  # None = admin's lead
    form_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    business = db.Column(db.String(120), default="")
    business_type = db.Column(db.String(120), default="")
    source = db.Column(db.String(120), default="manual")
    status = db.Column(db.String(20), default="New")
    deal_value = db.Column(db.Float, nullable=True)  # expected $/month if closed
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.relationship("Note", backref="lead", cascade="all, delete-orphan",
                            order_by="Note.created_at.desc()")
    tasks = db.relationship("Task", backref="lead", cascade="all, delete-orphan",
                            order_by="Task.due_at")


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)  # None = admin's task
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=True)
    title = db.Column(db.String(240), nullable=False)
    kind = db.Column(db.String(30), default="To-do")
    due_at = db.Column(db.DateTime, nullable=True)  # stored UTC
    done = db.Column(db.Boolean, default=False)
    done_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Form(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    redirect_url = db.Column(db.String(400), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    business_name = db.Column(db.String(120), nullable=False)
    template = db.Column(db.String(80), default="")
    github_repo = db.Column(db.String(200), default="")  # "owner/repo" -> Netlify auto-deploy
    last_push_at = db.Column(db.DateTime, nullable=True)
    last_push_ok = db.Column(db.Boolean, nullable=True)
    last_push_msg = db.Column(db.String(300), default="")
    html = db.Column(db.Text, default="")
    # legacy v1 fields (older generated sites still render through them)
    tagline = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    services = db.Column(db.Text, default="")
    about = db.Column(db.Text, default="")
    color = db.Column(db.String(9), default="#FF6B35")
    style = db.Column(db.String(20), default="clean")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class SiteRevision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=False)
    html = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    filename = db.Column(db.String(200), default="upload")
    mimetype = db.Column(db.String(100), default="application/octet-stream")
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Flipbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    title = db.Column(db.String(160), nullable=False)
    page_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pages = db.relationship("FlipbookPage", backref="flipbook",
                            cascade="all, delete-orphan",
                            order_by="FlipbookPage.page_num")


class FlipbookPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flipbook_id = db.Column(db.Integer, db.ForeignKey("flipbook.id"), nullable=False)
    page_num = db.Column(db.Integer, nullable=False)
    image = db.Column(db.LargeBinary, nullable=False)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)


def ensure_schema():
    """create_all + additive column migration so existing DBs upgrade in place."""
    db.create_all()
    insp = inspect(db.engine)
    wanted = {
        "lead": {"owner_id": "INTEGER", "form_id": "INTEGER", "deal_value": "FLOAT"},
        "site": {"owner_id": "INTEGER", "template": "VARCHAR(80)", "html": "TEXT",
                 "github_repo": "VARCHAR(200)", "last_push_at": "TIMESTAMP",
                 "last_push_ok": "BOOLEAN", "last_push_msg": "VARCHAR(300)"},
        "user": {"phone": "VARCHAR(40)", "monthly_price": "FLOAT",
                 "setup_fee": "FLOAT"},
    }
    with db.engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}'))


with app.app_context():
    ensure_schema()


# ------------------------------------------------------------------- helpers
def current_user():
    if session.get("admin"):
        return "admin", None
    uid = session.get("uid")
    if uid:
        user = db.session.get(User, uid)
        if user:
            return "user", user
        session.clear()
    return None, None


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        role, _ = current_user()
        if not role:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def owner_filter(query, model):
    """Admin sees everything; customers see their own rows."""
    role, user = current_user()
    if role == "admin":
        return query
    return query.filter(model.owner_id == user.id)


def my_tasks_query():
    """Tasks are personal: the admin's day view shows the admin's own tasks,
    not every customer's (oversight still exists via each lead's page)."""
    role, user = current_user()
    if role == "admin":
        return Task.query.filter(Task.owner_id.is_(None))
    return Task.query.filter(Task.owner_id == user.id)


def my_owner_id():
    role, user = current_user()
    return None if role == "admin" else user.id


def can_touch(obj):
    role, user = current_user()
    return role == "admin" or (user and obj.owner_id == user.id)


def slugify(txt):
    base = re.sub(r"[^a-z0-9]+", "-", (txt or "").lower()).strip("-") or "item"
    return f"{base}-{secrets.token_hex(2)}"


# ------------------------------------------------------------- time & money
def utcnow_naive():
    """Naive UTC now — matches how DateTime columns come back from the DB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def parse_local_dt(s):
    """'2026-08-14T15:30' from a datetime-local input, in APP_TZ -> naive UTC."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_money(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v) or v < 0:  # 'inf'/'nan' would 500 every |money render
        return None
    return round(v, 2)


@app.template_filter("local")
def filter_local(dt, fmt="%b %-d, %-I:%M %p"):
    dt = to_local(dt)
    return dt.strftime(fmt) if dt else "—"


@app.template_filter("localdate")
def filter_localdate(dt, fmt="%b %-d"):
    dt = to_local(dt)
    return dt.strftime(fmt) if dt else "—"


@app.template_filter("money")
def filter_money(v):
    if v is None:
        return "—"
    v = float(v)
    if not math.isfinite(v):  # defensive: never let a bad DB row 500 a page
        return "—"
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


@app.template_filter("duefmt")
def filter_duefmt(dt):
    """Human due label: Today 3:00 PM · Tomorrow · Aug 20."""
    if dt is None:
        return "no due date"
    local = to_local(dt)
    today = datetime.now(LOCAL_TZ).date()
    d = local.date()
    clock = local.strftime("%-I:%M %p")
    if d == today:
        return f"Today {clock}"
    if d == today + timedelta(days=1):
        return f"Tomorrow {clock}"
    if d == today - timedelta(days=1):
        return f"Yesterday {clock}"
    fmt = "%a %b %-d" if abs((d - today).days) < 7 else "%b %-d"
    if d.year != today.year:
        fmt += ", %Y"
    return f"{local.strftime(fmt)} {clock}"


# --------------------------------------------------------- setup notifications
def setup_alerts():
    """Admin to-do list for things that aren't fully configured.
    Each: {level: critical|warn|info, icon, title, body, guide (anchor on /admin/setup)}."""
    alerts = []
    linked_q = Site.query.filter(Site.github_repo.isnot(None), Site.github_repo != "")
    linked_count = linked_q.count()
    if not GITHUB_TOKEN:
        if linked_count:
            alerts.append(dict(
                level="critical", icon="bi-github", guide="github",
                title="GitHub publishing is OFF — client site edits are NOT going live",
                body=f"{linked_count} site(s) are linked to GitHub repos, but no GITHUB_TOKEN "
                     "is set on the server, so Saves only store here — nothing is pushed to "
                     "Netlify. One token fixes every site (set it once, not per site)."))
        else:
            alerts.append(dict(
                level="info", icon="bi-github", guide="github",
                title="Set up GitHub publishing (one-time)",
                body="Add a GITHUB_TOKEN so editor Saves auto-commit to each client's repo "
                     "and Netlify redeploys their real domain."))
    failed = linked_q.filter(Site.last_push_ok.is_(False)).all()
    for s in failed:
        alerts.append(dict(
            level="critical", icon="bi-cloud-slash", guide="github",
            title=f"Last publish FAILED for “{s.business_name}”",
            body=f"{s.last_push_msg or 'GitHub rejected the push'} — repo {s.github_repo}. "
                 f"Fix the token/repo access, then use “Push now” on the Sites page."))
    client_unlinked = Site.query.filter(
        Site.owner_id.isnot(None),
        db.or_(Site.github_repo.is_(None), Site.github_repo == "")).all()
    for s in client_unlinked:
        alerts.append(dict(
            level="warn", icon="bi-link-45deg", guide="linksite",
            title=f"“{s.business_name}” isn't linked to a GitHub repo",
            body="Edits save here but never reach the client's live domain. "
                 "Sites → Link repo, then their Saves publish automatically."))
    if not RESEND_KEY:
        alerts.append(dict(
            level="warn", icon="bi-envelope-x", guide="resend",
            title="Lead email alerts are off",
            body="Set RESEND_API_KEY so new form leads email their owner instantly."))
    elif not ADMIN_EMAIL:
        alerts.append(dict(
            level="warn", icon="bi-envelope-exclamation", guide="resend",
            title="Your own forms can't email you",
            body="Resend is connected, but ADMIN_EMAIL isn't set — client forms email "
                 "clients, yours go nowhere. Set ADMIN_EMAIL in Railway."))
    no_price = User.query.filter(User.monthly_price.is_(None)).count()
    if no_price:
        alerts.append(dict(
            level="info", icon="bi-currency-dollar", guide="billing",
            title=f"{no_price} customer(s) have no monthly price set",
            body="Set what each customer pays (Customers page) and the Revenue "
                 "dashboard computes MRR and projections for real."))
    if not OPENAI_API_KEY:
        alerts.append(dict(
            level="info", icon="bi-stars", guide="openai",
            title="Editor AI is off",
            body="Set OPENAI_API_KEY to enable AI rewrite / AI restyle in the site editor."))
    return alerts


@app.context_processor
def inject_globals():
    role, user = current_user()
    ctx = {"STATUSES": LEAD_STATUSES, "STATUS_COLORS": STATUS_COLORS,
           "STATUS_WEIGHTS": STATUS_WEIGHTS, "TASK_KINDS": TASK_KINDS,
           "TASK_ICONS": TASK_ICONS, "role": role, "me": user,
           "alerts": [], "alert_count": 0}
    # alert badge only for admin pages (skip public pages -> no extra queries)
    if role == "admin" and request.path.startswith("/admin"):
        alerts = setup_alerts()
        ctx["alerts"] = alerts
        ctx["alert_count"] = sum(1 for a in alerts if a["level"] != "info")
    return ctx


def github_fetch_index(repo):
    """Pull index.html from a GitHub repo (site import)."""
    hdr = {"Accept": "application/vnd.github.raw"}
    if GITHUB_TOKEN:
        hdr["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = http.get(f"https://api.github.com/repos/{repo}/contents/index.html",
                     headers=hdr, timeout=20)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


GITHUB_ERRORS = {
    401: "GitHub rejected the token (expired or revoked) — make a new fine-grained "
         "token and update GITHUB_TOKEN in Railway",
    403: "The token can't write to this repo — edit the token's repository list "
         "and give it Contents: Read & write",
    404: "Repo not found, or the token can't see it — check the owner/repo spelling "
         "and add the repo to the token's repository access",
    409: "Git conflict (the repo changed underneath us) — hit Save / Push now again",
}


def github_push_site(site):
    """Commit site.html to the linked repo's index.html -> Netlify auto-deploys.
    Returns (ok, msg): ok is None when no repo is linked, else True/False.
    Records the attempt on the site row (caller commits)."""
    if not site.github_repo:
        return None, "No repo linked"
    if not GITHUB_TOKEN:
        site.last_push_at = utcnow_naive()
        site.last_push_ok = False
        site.last_push_msg = "GITHUB_TOKEN not set on the server — see Setup"
        return False, site.last_push_msg
    url = f"https://api.github.com/repos/{site.github_repo}/contents/index.html"
    hdr = {"Authorization": f"Bearer {GITHUB_TOKEN}",
           "Accept": "application/vnd.github+json"}
    try:
        r = http.get(url, headers=hdr, timeout=20)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {"message": "Update via 60MS HQ editor",
                   "content": base64.b64encode((site.html or "").encode()).decode()}
        if sha:
            payload["sha"] = sha
        r2 = http.put(url, headers=hdr, json=payload, timeout=30)
        ok = r2.status_code in (200, 201)
        msg = ("Live — committed to GitHub, Netlify is redeploying" if ok
               else GITHUB_ERRORS.get(r2.status_code, f"GitHub error {r2.status_code}"))
    except Exception as e:
        ok, msg = False, f"Couldn't reach GitHub ({type(e).__name__})"
    site.last_push_at = utcnow_naive()
    site.last_push_ok = ok
    site.last_push_msg = msg[:300]
    return ok, msg


def github_check_repo(repo):
    """Can the server token see this repo? Returns (ok, msg)."""
    if not GITHUB_TOKEN:
        return False, "No GITHUB_TOKEN set on the server yet — the link is saved, but pushes will fail until you add one (Setup guide)."
    try:
        r = http.get(f"https://api.github.com/repos/{repo}", timeout=20,
                     headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                              "Accept": "application/vnd.github+json"})
        if r.status_code == 200:
            return True, "Token can see the repo."
        return False, GITHUB_ERRORS.get(r.status_code, f"GitHub error {r.status_code}")
    except Exception as e:
        return False, f"Couldn't reach GitHub ({type(e).__name__})"


def notify_lead(form, lead):
    """Email the form's owner about a new lead via Resend (best-effort)."""
    if not RESEND_KEY:
        return
    owner = db.session.get(User, form.owner_id) if form.owner_id else None
    to = owner.email if owner else ADMIN_EMAIL
    if not to:
        return
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#888'>{k}</td><td><b>{v}</b></td></tr>"
                   for k, v in [("Name", lead.name), ("Cell", lead.phone), ("Email", lead.email),
                                ("Business", lead.business), ("Source", lead.source)] if v)
    try:
        http.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {RESEND_KEY}"},
                  json={"from": RESEND_FROM, "to": [to],
                        "subject": f"New lead: {lead.name} — {form.name}",
                        "html": f"<h2 style='font-family:sans-serif'>New lead from “{form.name}”</h2>"
                                f"<table style='font-family:sans-serif;font-size:15px'>{rows}</table>"
                                f"<p style='font-family:sans-serif;color:#888'>It's already in your CRM.</p>"},
                  timeout=15)
    except Exception:
        pass


TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "site", "landing-pages")


def list_templates():
    out = []
    if os.path.isdir(TEMPLATE_DIR):
        for f in sorted(os.listdir(TEMPLATE_DIR)):
            if f.endswith(".html") and f != "landing-page.html":
                out.append(f[:-5])
    return out


def instantiate_template(name, business_name):
    """Load a landing-page template and strip 60MS-specific wiring so it
    becomes a clean starting point for a customer site."""
    if name == "blank":
        html = render_template("blank_site.html", business_name=business_name)
        return html
    path = os.path.join(TEMPLATE_DIR, f"{name}.html")
    if not os.path.isfile(path):
        abort(404)
    html = open(path, encoding="utf-8", errors="ignore").read()
    # strip Meta pixel / gtag / hls / shared header+footer loaders
    html = re.sub(r"<script[^>]*>[^<]*(?:fbq|googletagmanager|gtag)\b.*?</script>",
                  "", html, flags=re.S)
    html = re.sub(r"<script[^>]*src=\"[^\"]*(?:gtag|googletagmanager|hls\.js)[^\"]*\"[^>]*>\s*</script>",
                  "", html)
    html = re.sub(r"<noscript><img[^>]*facebook[^>]*></noscript>", "", html)
    html = re.sub(r"<script src=\"/js/components.js\"></script>", "", html)
    html = html.replace('<div id="site-header"></div>', "")
    html = html.replace('<div id="site-footer"></div>', "")
    html = re.sub(r"<title>.*?</title>",
                  f"<title>{business_name}</title>", html, count=1, flags=re.S)
    return html


EDITOR_SNIPPET = ('<link rel="stylesheet" href="/static-admin/editor.css" data-wys="1">'
                  '<script src="/static-admin/editor.js" data-wys="1" defer></script>')


def strip_editor_artifacts(html):
    html = re.sub(r"<[^>]+data-wys=\"1\"[^>]*>\s*(</script>)?", "", html)
    html = re.sub(r"<div id=\"wys-toolbar\".*?</div>\s*(?=</body>)", "", html, flags=re.S)
    html = html.replace(' contenteditable="true"', "").replace(" contenteditable=\"\"", "")
    html = re.sub(r"<style id=\"wys-hover-style\">.*?</style>", "", html, flags=re.S)
    return html


# ---------------------------------------------------------------- auth + home
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/static-admin/<path:filename>")
def static_admin(filename):
    return send_from_directory(os.path.join(app.root_path, "static"), filename)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.static_folder, "favicon_io (4)"),
                               "favicon.ico")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email and password == ADMIN_PASSWORD:
            session.clear()
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        user = User.query.filter_by(email=email).first() if email else None
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["uid"] = user.id
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("No match — check email + password (owner: leave email blank).", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not (name and email and len(password) >= 6):
            flash("Name, email, and a 6+ character password required.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email already has an account — log in instead.", "error")
        else:
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["uid"] = user.id
            return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboard
@app.route("/admin")
@login_required
def dashboard():
    stats = {
        "leads": owner_filter(Lead.query, Lead).count(),
        "booked": owner_filter(Lead.query, Lead)
                  .filter(Lead.status.in_(["Booked", "Built", "Client"])).count(),
        "sites": owner_filter(Site.query, Site).count(),
        "forms": owner_filter(Form.query, Form).count(),
    }
    if session.get("admin"):
        stats["mrr"] = sum(u.monthly_price or 0 for u in
                           User.query.filter(User.monthly_price.isnot(None)))
    now = utcnow_naive()
    eod = datetime.now(LOCAL_TZ).replace(hour=23, minute=59, second=59)\
        .astimezone(timezone.utc).replace(tzinfo=None)
    open_q = my_tasks_query().filter(Task.done.is_(False))
    overdue = (open_q.filter(Task.due_at.isnot(None), Task.due_at < now)
               .order_by(Task.due_at).limit(8).all())
    today = (open_q.filter(Task.due_at >= now, Task.due_at <= eod)
             .order_by(Task.due_at).limit(8).all())
    task_leads = {t.lead_id: t.lead.name for t in overdue + today if t.lead_id}
    recent = owner_filter(Lead.query, Lead).order_by(Lead.created_at.desc()).limit(6).all()
    return render_template("dashboard.html", stats=stats, recent=recent,
                           overdue=overdue, today=today, task_leads=task_leads)


# ------------------------------------------------------------------------ crm
def _next_steps(rows):
    """{lead_id: earliest open task} for the given leads."""
    ids = [l.id for l in rows]
    if not ids:
        return {}
    nxt = {}
    open_tasks = (Task.query.filter(Task.lead_id.in_(ids), Task.done.is_(False))
                  .order_by(Task.due_at.is_(None), Task.due_at).all())
    for t in open_tasks:
        nxt.setdefault(t.lead_id, t)
    return nxt


@app.route("/admin/crm")
@login_required
def crm():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    query = owner_filter(Lead.query, Lead)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like),
                                    Lead.email.ilike(like), Lead.business.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(Lead.created_at.desc()).all()
    return render_template("crm.html", rows=rows, q=q, status=status,
                           next_steps=_next_steps(rows), now=utcnow_naive())


@app.route("/admin/crm/board")
@login_required
def crm_board():
    rows = owner_filter(Lead.query, Lead).order_by(Lead.created_at.desc()).all()
    cols = {s: [] for s in LEAD_STATUSES}
    for lead in rows:
        cols.setdefault(lead.status, []).append(lead)
    totals = {s: sum(l.deal_value or 0 for l in leads_) for s, leads_ in cols.items()}
    return render_template("crm_board.html", cols=cols, totals=totals,
                           next_steps=_next_steps(rows), now=utcnow_naive())


@app.route("/admin/crm/new", methods=["GET", "POST"])
@login_required
def lead_new():
    if request.method == "POST":
        lead = Lead(owner_id=my_owner_id(),
                    source=request.form.get("source", "manual").strip() or "manual",
                    status=request.form.get("status", "New"),
                    deal_value=parse_money(request.form.get("deal_value")),
                    **{f: request.form.get(f, "").strip() for f in LEAD_FIELDS})
        lead.name = lead.name or "Unknown"
        db.session.add(lead)
        db.session.commit()
        flash(f"Lead “{lead.name}” added.")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_form.html", lead=None)


@app.route("/admin/crm/<int:lead_id>", methods=["GET", "POST"])
@login_required
def lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if not can_touch(lead):
        abort(403)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "status" and request.form.get("status") in LEAD_STATUSES:
            old = lead.status
            lead.status = request.form.get("status")
            if old != lead.status:
                db.session.add(Note(lead_id=lead.id,
                                    body=f"Status changed: {old} → {lead.status}"))
        elif action == "note":
            body = request.form.get("body", "").strip()
            if body:
                db.session.add(Note(lead_id=lead.id, body=body))
        elif action == "update":
            for f in LEAD_FIELDS + ["source"]:
                setattr(lead, f, request.form.get(f, "").strip())
            lead.deal_value = parse_money(request.form.get("deal_value"))
        elif action == "delete":
            db.session.delete(lead)
            db.session.commit()
            flash("Lead deleted.")
            return redirect(url_for("crm"))
        db.session.commit()
        return redirect(url_for("lead_detail", lead_id=lead.id))
    open_tasks = [t for t in lead.tasks if not t.done]
    done_tasks = [t for t in lead.tasks if t.done]
    return render_template("lead_detail.html", lead=lead, open_tasks=open_tasks,
                           done_tasks=done_tasks, now=utcnow_naive())


@app.route("/admin/crm/<int:lead_id>/status", methods=["POST"])
@login_required
def lead_status(lead_id):
    """JSON endpoint for the board's drag-and-drop."""
    lead = Lead.query.get_or_404(lead_id)
    if not can_touch(lead):
        abort(403)
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in LEAD_STATUSES:
        return jsonify(ok=False, error="bad status"), 400
    if status != lead.status:
        db.session.add(Note(lead_id=lead.id,
                            body=f"Status changed: {lead.status} → {status}"))
        lead.status = status
        db.session.commit()
    return jsonify(ok=True, status=lead.status)


# legacy URLs (old bookmarks / muscle memory) -> CRM
@app.route("/admin/leads")
def legacy_leads():
    return redirect(url_for("crm"), code=301)


@app.route("/admin/leads/new")
def legacy_lead_new():
    return redirect(url_for("lead_new"), code=301)


@app.route("/admin/leads/<int:lead_id>")
def legacy_lead_detail(lead_id):
    return redirect(url_for("lead_detail", lead_id=lead_id), code=301)


# -------------------------------------------------------- tasks & activities
@app.route("/admin/tasks", methods=["GET", "POST"])
@login_required
def tasks():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Give the task a title.", "error")
            return redirect(request.form.get("next") or url_for("tasks"))
        lead_id = request.form.get("lead_id", type=int)
        if lead_id:
            lead = Lead.query.get_or_404(lead_id)
            if not can_touch(lead):
                abort(403)
        kind = request.form.get("kind", "To-do")
        task = Task(owner_id=my_owner_id(), lead_id=lead_id or None, title=title,
                    kind=kind if kind in TASK_KINDS else "To-do",
                    due_at=parse_local_dt(request.form.get("due_at", "")))
        db.session.add(task)
        db.session.commit()
        flash(f"Task “{title}” scheduled." if task.due_at else f"Task “{title}” added.")
        return redirect(request.form.get("next") or url_for("tasks"))

    rows = my_tasks_query().order_by(Task.due_at.is_(None), Task.due_at).all()
    now = utcnow_naive()
    local_now = datetime.now(LOCAL_TZ)

    def utc_eod(days_ahead):
        return (local_now + timedelta(days=days_ahead)).replace(
            hour=23, minute=59, second=59).astimezone(timezone.utc).replace(tzinfo=None)

    eod, tomorrow_end, week_end = utc_eod(0), utc_eod(1), utc_eod(7)
    buckets = {"Overdue": [], "Today": [], "Tomorrow": [], "This week": [],
               "Later": [], "No due date": []}
    done_recent = []
    for t in rows:
        if t.done:
            done_recent.append(t)
        elif t.due_at is None:
            buckets["No due date"].append(t)
        elif t.due_at < now:
            buckets["Overdue"].append(t)
        elif t.due_at <= eod:
            buckets["Today"].append(t)
        elif t.due_at <= tomorrow_end:
            buckets["Tomorrow"].append(t)
        elif t.due_at <= week_end:
            buckets["This week"].append(t)
        else:
            buckets["Later"].append(t)
    done_recent.sort(key=lambda t: t.done_at or t.created_at, reverse=True)
    open_count = sum(len(v) for v in buckets.values())
    lead_names = {t.lead_id: t.lead.name for t in rows if t.lead_id}
    my_leads = (owner_filter(Lead.query, Lead)
                .filter(Lead.status.notin_(["Dead"]))
                .order_by(Lead.created_at.desc()).limit(200).all())
    return render_template("tasks.html", buckets=buckets, done_recent=done_recent[:15],
                           open_count=open_count, lead_names=lead_names,
                           my_leads=my_leads)


@app.route("/admin/tasks/<int:task_id>/<action>", methods=["POST"])
@login_required
def task_action(task_id, action):
    task = Task.query.get_or_404(task_id)
    if not can_touch(task):
        abort(403)
    if action == "toggle":
        task.done = not task.done
        task.done_at = utcnow_naive() if task.done else None
    elif action == "delete":
        db.session.delete(task)
    elif action == "snooze":  # quick reschedule: +1d / +3d / +1w / today 9am
        opt = request.form.get("to", "+1d")
        now_local = datetime.now(LOCAL_TZ)
        if opt == "today":
            nxt = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
            if nxt <= now_local:  # 9am already gone -> top of the next hour
                nxt = (now_local + timedelta(hours=1)).replace(minute=0, second=0,
                                                               microsecond=0)
        else:
            days = {"+1d": 1, "+3d": 3, "+1w": 7}.get(opt, 1)
            base = to_local(task.due_at) or now_local
            if base < now_local:  # snoozing an overdue task counts from NOW
                base = now_local
            nxt = base + timedelta(days=days)
        task.due_at = nxt.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        abort(404)
    db.session.commit()
    return redirect(request.form.get("next") or url_for("tasks"))


# ---------------------------------------------------------- revenue (admin)
@app.route("/admin/revenue")
@admin_required
def revenue():
    users = User.query.order_by(User.created_at).all()
    paying = [u for u in users if (u.monthly_price or 0) > 0]
    paying.sort(key=lambda u: u.monthly_price, reverse=True)
    mrr = sum(u.monthly_price for u in paying)
    setup_total = sum(u.setup_fee or 0 for u in users)
    open_statuses = [s for s in LEAD_STATUSES if s not in ("Client", "Dead")]
    # admin-owned leads only: customers' deals are THEIR revenue, not 60MS's
    open_leads = (Lead.query.filter(Lead.owner_id.is_(None),
                                    Lead.status.in_(open_statuses),
                                    Lead.deal_value.isnot(None),
                                    Lead.deal_value > 0)
                  .order_by(Lead.deal_value.desc()).all())
    pipeline_raw = sum(l.deal_value for l in open_leads)
    pipeline_weighted = sum(l.deal_value * STATUS_WEIGHTS.get(l.status, 0)
                            for l in open_leads)
    # 12-month cumulative collections: committed MRR + weighted pipeline upside
    local_now = datetime.now(LOCAL_TZ)
    months, base_cum, upside_cum = [], [], []
    y, m = local_now.year, local_now.month
    for i in range(1, 13):
        m += 1
        if m > 12:
            m, y = 1, y + 1
        months.append(datetime(y, m, 1).strftime("%b %y" if i in (1, 12) or m == 1 else "%b"))
        base_cum.append(mrr * i)
        upside_cum.append(pipeline_weighted * i)
    chart_max = max((base_cum[-1] + upside_cum[-1]), 1)
    return render_template("revenue.html", paying=paying, mrr=mrr,
                           setup_total=setup_total, open_leads=open_leads,
                           pipeline_raw=pipeline_raw,
                           pipeline_weighted=pipeline_weighted,
                           months=months, base_cum=base_cum, upside_cum=upside_cum,
                           chart_max=chart_max, users=users)


# ------------------------------------------------------- forms (formspree-ish)
@app.route("/admin/forms", methods=["GET", "POST"])
@login_required
def forms():
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Contact form"
        owner_id = my_owner_id()
        if session.get("admin") and request.form.get("owner_id"):
            owner_id = int(request.form["owner_id"])
        form = Form(owner_id=owner_id, name=name, slug=slugify(name),
                    redirect_url=request.form.get("redirect_url", "").strip())
        db.session.add(form)
        db.session.commit()
        flash(f"Form “{name}” created — grab the embed code below.")
        return redirect(url_for("forms"))
    rows = owner_filter(Form.query, Form).order_by(Form.created_at.desc()).all()
    counts = {f.id: Lead.query.filter_by(form_id=f.id).count() for f in rows}
    users = User.query.order_by(User.name).all() if session.get("admin") else []
    owners = {u.id: u.name for u in users}
    return render_template("forms.html", rows=rows, counts=counts, users=users,
                           owners=owners, host=request.host_url.rstrip("/"))


@app.route("/admin/forms/<int:form_id>/delete", methods=["POST"])
@login_required
def form_delete(form_id):
    form = Form.query.get_or_404(form_id)
    if not can_touch(form):
        abort(403)
    db.session.delete(form)
    db.session.commit()
    flash("Form deleted (its leads are kept).")
    return redirect(url_for("forms"))


@app.route("/form/<slug>", methods=["POST", "OPTIONS"])
def form_submit(slug):
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    form = Form.query.filter_by(slug=slug).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    if data.get("_gotcha"):  # honeypot
        return _cors(jsonify(ok=True))
    lead = Lead(owner_id=form.owner_id, form_id=form.id,
                source=data.get("source") or data.get("utm_content") or form.name,
                **{f: str(data.get(f, ""))[:200] for f in LEAD_FIELDS})
    lead.name = lead.name or "Unknown"
    db.session.add(lead)
    db.session.flush()
    extras = {k: v for k, v in data.items()
              if k not in LEAD_FIELDS + ["source", "_gotcha", "_next"] and v}
    if extras:
        db.session.add(Note(lead_id=lead.id, body="Form extras: " +
                            json.dumps(extras, ensure_ascii=False)[:2000]))
    db.session.commit()
    notify_lead(form, lead)
    if request.is_json:
        return _cors(jsonify(ok=True, lead_id=lead.id))
    return redirect(data.get("_next") or form.redirect_url
                    or url_for("form_thanks", slug=slug))


@app.route("/form/<slug>/thanks")
def form_thanks(slug):
    form = Form.query.filter_by(slug=slug).first_or_404()
    return render_template("form_thanks.html", form=form)


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


# ---------------------------------------------------------- customers (admin)
@app.route("/admin/customers", methods=["GET", "POST"])
@admin_required
def customers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "") or secrets.token_urlsafe(8)
        if not (name and email):
            flash("Name and email required.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email already exists.", "error")
        else:
            db.session.add(User(name=name, email=email, phone=phone,
                                monthly_price=parse_money(request.form.get("monthly_price")),
                                setup_fee=parse_money(request.form.get("setup_fee")),
                                password_hash=generate_password_hash(password)))
            db.session.commit()
            flash(f"Customer “{name}” created — password: {password}", "sticky")
        return redirect(url_for("customers"))
    rows = User.query.order_by(User.created_at.desc()).all()
    stats = {u.id: {"sites": Site.query.filter_by(owner_id=u.id).count(),
                    "leads": Lead.query.filter_by(owner_id=u.id).count()}
             for u in rows}
    mrr = sum(u.monthly_price or 0 for u in rows)
    return render_template("customers.html", rows=rows, stats=stats, mrr=mrr)


@app.route("/admin/customers/<int:user_id>/<action>", methods=["POST"])
@admin_required
def customer_action(user_id, action):
    user = User.query.get_or_404(user_id)
    if action == "delete":
        db.session.delete(user)
        flash(f"Customer “{user.name}” deleted (their sites/leads are kept, unowned).")
    elif action == "reset":
        new_pw = secrets.token_urlsafe(8)
        user.password_hash = generate_password_hash(new_pw)
        flash(f"New password for {user.name}: {new_pw}", "sticky")
    elif action == "billing":
        user.monthly_price = parse_money(request.form.get("monthly_price"))
        user.setup_fee = parse_money(request.form.get("setup_fee"))
        price = filter_money(user.monthly_price)
        flash(f"Billing saved for {user.name}: {price}/mo"
              + (f" + {filter_money(user.setup_fee)} setup" if user.setup_fee else ""))
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("customers"))


# ------------------------------------------------------ site builder (wysiwyg)
@app.route("/admin/sites")
@login_required
def sites():
    rows = owner_filter(Site.query, Site).order_by(Site.updated_at.desc()).all()
    owners = {u.id: u.name for u in User.query.all()} if session.get("admin") else {}
    revisions = {s.id: SiteRevision.query.filter_by(site_id=s.id).count() for s in rows}
    return render_template("sites.html", rows=rows, owners=owners, revisions=revisions)


@app.route("/admin/sites/new", methods=["GET", "POST"])
@login_required
def site_new():
    if request.method == "POST":
        business = request.form.get("business_name", "").strip() or "My Business"
        template = request.form.get("template", "blank")
        owner_id = my_owner_id()
        if session.get("admin") and request.form.get("owner_id"):
            owner_id = int(request.form["owner_id"])
        repo = request.form.get("github_repo", "").strip().removeprefix("https://github.com/").strip("/")
        html = None
        if repo and session.get("admin"):
            html = github_fetch_index(repo)
            if html is None:
                flash(f"Couldn't read index.html from {repo} — check the repo name"
                      + ("" if GITHUB_TOKEN else " (no GITHUB_TOKEN set; private repos need one)"))
                return redirect(url_for("site_new"))
            template = "github-import"
        site = Site(owner_id=owner_id, slug=slugify(business),
                    business_name=business, template=template,
                    github_repo=repo if html else "",
                    html=html or instantiate_template(template, business))
        db.session.add(site)
        db.session.commit()
        return redirect(url_for("editor", site_id=site.id))
    users = User.query.order_by(User.name).all() if session.get("admin") else []
    return render_template("site_picker.html", templates=list_templates(), users=users)


@app.route("/edit/<int:site_id>")
@login_required
def editor(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    if not site.html:  # legacy v1 site — wrap its rendered page for editing
        services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
        site.html = render_template("public_site.html", site=site, services=services)
        db.session.commit()
    html = site.html
    my_forms = owner_filter(Form.query, Form).all()
    boot = ("<script data-wys=\"1\">window.WYS = " + json.dumps({
        "siteId": site.id, "slug": site.slug, "ai": bool(OPENAI_API_KEY),
        "forms": [{"name": f.name, "slug": f.slug} for f in my_forms],
    }) + ";</script>")
    inject = boot + EDITOR_SNIPPET
    if "</body>" in html:
        html = html.replace("</body>", inject + "</body>", 1)
    else:
        html += inject
    return Response(html, mimetype="text/html")


@app.route("/edit/<int:site_id>/save", methods=["POST"])
@login_required
def editor_save(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    payload = request.get_json(silent=True) or {}
    html = payload.get("html", "")
    if not html:
        return jsonify(ok=False, error="empty"), 400
    if site.html:  # keep a rollback trail, capped at 20
        db.session.add(SiteRevision(site_id=site.id, html=site.html))
        extra = (SiteRevision.query.filter_by(site_id=site.id)
                 .order_by(SiteRevision.created_at.desc()).offset(20).all())
        for r in extra:
            db.session.delete(r)
    site.html = strip_editor_artifacts(html)
    db.session.commit()
    pushed, msg = github_push_site(site)
    db.session.commit()  # record the push attempt on the site row
    return jsonify(ok=True, msg=msg,
                   github=("synced" if pushed else
                           "failed" if pushed is False else "not linked"))


@app.route("/admin/sites/<int:site_id>/revert", methods=["POST"])
@login_required
def site_revert(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    rev = (SiteRevision.query.filter_by(site_id=site.id)
           .order_by(SiteRevision.created_at.desc()).first())
    if not rev:
        flash("No earlier version to restore.", "error")
        return redirect(url_for("sites"))
    site.html, rev.html = rev.html, site.html  # swap so revert is itself revertible
    pushed, msg = github_push_site(site)
    db.session.commit()
    note = "" if pushed is None else (" Re-pushed to GitHub." if pushed
                                      else f" GitHub push failed: {msg}")
    flash(f"Restored the previous version of “{site.business_name}”.{note}")
    return redirect(url_for("sites"))


@app.route("/admin/sites/<int:site_id>/github", methods=["POST"])
@admin_required
def site_github(site_id):
    """Link/unlink a GitHub repo on an EXISTING site (the Todd case)."""
    site = Site.query.get_or_404(site_id)
    if request.form.get("action") == "unlink":
        site.github_repo = ""
        site.last_push_ok = None
        site.last_push_msg = ""
        db.session.commit()
        flash(f"“{site.business_name}” unlinked from GitHub — edits stay local now.")
        return redirect(url_for("sites"))
    repo = (request.form.get("github_repo", "").strip()
            .removeprefix("https://github.com/").removesuffix(".git").strip("/"))
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        flash("That doesn't look like owner/repo — e.g. corbanCodes/toddtrope", "error")
        return redirect(url_for("sites"))
    site.github_repo = repo
    ok, msg = github_check_repo(repo)
    if ok and request.form.get("push_now"):
        pushed, pmsg = github_push_site(site)
        flash(f"“{site.business_name}” linked to {repo}. "
              + ("Pushed the current version live — Netlify is redeploying."
                 if pushed else f"Linked, but the first push failed: {pmsg}"))
    else:
        flash(f"“{site.business_name}” linked to {repo}. {msg}")
    db.session.commit()
    return redirect(url_for("sites"))


@app.route("/admin/sites/<int:site_id>/push", methods=["POST"])
@login_required
def site_push(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    ok, msg = github_push_site(site)
    db.session.commit()
    if ok is None:
        flash("This site isn't linked to a GitHub repo yet — use Link repo first.", "error")
    elif ok:
        flash(f"“{site.business_name}” pushed to {site.github_repo} — {msg}.")
    else:
        flash(f"Push failed for “{site.business_name}”: {msg}", "error")
    return redirect(url_for("sites"))


@app.route("/admin/sites/<int:site_id>/delete", methods=["POST"])
@login_required
def site_delete(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    db.session.delete(site)
    db.session.commit()
    flash("Site deleted.")
    return redirect(url_for("sites"))


@app.route("/s/<slug>")
def public_site(slug):
    site = Site.query.filter_by(slug=slug).first_or_404()
    if site.html:
        return Response(site.html, mimetype="text/html")
    services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
    return render_template("public_site.html", site=site, services=services)


# ---------------------------------------------------- funnels (links + export)
@app.route("/admin/funnels")
@login_required
def funnels():
    rows = owner_filter(Site.query, Site).order_by(Site.updated_at.desc()).all()
    my_forms = owner_filter(Form.query, Form).all()
    return render_template("funnels.html", rows=rows, my_forms=my_forms,
                           host=request.host_url.rstrip("/"))


@app.route("/admin/sites/<int:site_id>/download")
@login_required
def site_download(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    html = site.html or ""
    if not html:
        services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
        html = render_template("public_site.html", site=site, services=services)
    # absolutize root-relative assets so the file renders anywhere it's hosted
    base = request.host_url.rstrip("/")
    html = re.sub(r'(src|href|action)="/(?!/)', rf'\1="{base}/', html)
    return Response(html, mimetype="text/html", headers={
        "Content-Disposition": f'attachment; filename="{site.slug}.html"'})


# --------------------------------------------------------------------- media
@app.route("/media", methods=["POST"])
@login_required
def media_upload():
    file = request.files.get("file")
    if not file or not (file.mimetype.startswith("image/") or file.mimetype.startswith("video/")):
        return jsonify(ok=False, error="image or video files only"), 400
    m = Media(owner_id=my_owner_id(), filename=file.filename,
              mimetype=file.mimetype, data=file.read())
    db.session.add(m)
    db.session.commit()
    return jsonify(ok=True, url=f"/media/{m.id}")


@app.route("/media/<int:media_id>")
def media_get(media_id):
    m = Media.query.get_or_404(media_id)
    return Response(m.data, mimetype=m.mimetype,
                    headers={"Cache-Control": "public, max-age=604800"})


@app.route("/admin/setup")
@admin_required
def setup_page():
    status = {
        "resend": bool(RESEND_KEY), "github": bool(GITHUB_TOKEN),
        "openai": bool(OPENAI_API_KEY), "admin_email": ADMIN_EMAIL,
        "host": request.host_url.rstrip("/"),
    }
    linked = Site.query.filter(Site.github_repo.isnot(None),
                               Site.github_repo != "").all()
    return render_template("setup.html", s=status, linked_sites=linked)


@app.route("/admin/help")
@admin_required
def help_page():
    return redirect(url_for("setup_page"), code=301)


@app.route("/admin/setup/test-github", methods=["POST"])
@admin_required
def test_github():
    if not GITHUB_TOKEN:
        flash("No GITHUB_TOKEN set yet — follow the GitHub guide below, then retest.", "error")
        return redirect(url_for("setup_page"))
    try:
        r = http.get("https://api.github.com/user", timeout=20,
                     headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                              "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            flash(f"Token check FAILED: {GITHUB_ERRORS.get(r.status_code, f'GitHub error {r.status_code}')}", "error")
            return redirect(url_for("setup_page"))
        login = r.json().get("login", "?")
        results = [f"Token is valid (acts as “{login}”)."]
        for site in Site.query.filter(Site.github_repo.isnot(None),
                                      Site.github_repo != ""):
            ok, msg = github_check_repo(site.github_repo)
            results.append(f"{site.business_name} ({site.github_repo}): "
                           + ("reachable ✓" if ok else f"FAILED — {msg}"))
        flash(" · ".join(results), "sticky")
    except Exception as e:
        flash(f"Couldn't reach GitHub ({type(e).__name__}) — try again.", "error")
    return redirect(url_for("setup_page"))


# ------------------------------------------------------------------ editor AI
def _openai(messages, max_tokens=2000):
    r = http.post("https://api.openai.com/v1/chat/completions",
                  headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                  json={"model": OPENAI_MODEL, "messages": messages,
                        "max_tokens": max_tokens, "temperature": 0.7},
                  timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


@app.route("/ai/text", methods=["POST"])
@login_required
def ai_text():
    if not OPENAI_API_KEY:
        return jsonify(ok=False, error="Set OPENAI_API_KEY on the server."), 400
    p = request.get_json(silent=True) or {}
    try:
        out = _openai([
            {"role": "system", "content":
             "You write tight, persuasive copy for small-business websites. "
             "Return ONLY the replacement text — no quotes, no commentary, no markdown."},
            {"role": "user", "content":
             f"Instruction: {p.get('instruction', 'improve this')}\n\n"
             f"Current text:\n{p.get('text', '')[:4000]}"},
        ], max_tokens=800)
        return jsonify(ok=True, text=out)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 502


@app.route("/ai/design", methods=["POST"])
@login_required
def ai_design():
    if not OPENAI_API_KEY:
        return jsonify(ok=False, error="Set OPENAI_API_KEY on the server."), 400
    p = request.get_json(silent=True) or {}
    try:
        out = _openai([
            {"role": "system", "content":
             "You are a web designer. Given a page's structural outline and a design "
             "instruction, return ONLY a CSS stylesheet (no markdown fences, no <style> tag) "
             "that restyles the page. Use specific selectors from the outline, use "
             "!important where needed to override existing styles, and keep it tasteful."},
            {"role": "user", "content":
             f"Design instruction: {p.get('instruction', '')}\n\n"
             f"Page outline (tag.class/#id list):\n{p.get('outline', '')[:6000]}\n\n"
             f"Current AI override CSS (replace it):\n{p.get('current_css', '')[:3000]}"},
        ], max_tokens=2500)
        out = re.sub(r"^```(?:css)?|```$", "", out, flags=re.M).strip()
        return jsonify(ok=True, css=out)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 502


# ---------------------------------------------------------- flipbook animator
@app.route("/admin/flipbooks", methods=["GET", "POST"])
@admin_required
def flipbooks():
    if request.method == "POST":
        file = request.files.get("pdf")
        title = request.form.get("title", "").strip() or "Untitled"
        if not file or not file.filename.lower().endswith(".pdf"):
            flash("Upload a PDF file.", "error")
            return redirect(url_for("flipbooks"))
        try:
            doc = fitz.open(stream=file.read(), filetype="pdf")
        except Exception:
            flash("Couldn't read that PDF.", "error")
            return redirect(url_for("flipbooks"))
        if doc.page_count > 80:
            flash("PDF too long (80-page max).", "error")
            return redirect(url_for("flipbooks"))
        book = Flipbook(slug=slugify(title), title=title, page_count=doc.page_count)
        db.session.add(book)
        db.session.flush()
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            db.session.add(FlipbookPage(flipbook_id=book.id, page_num=i,
                                        image=pix.tobytes("png"),
                                        width=pix.width, height=pix.height))
        db.session.commit()
        flash(f"Flipbook “{title}” ready at /f/{book.slug}")
        return redirect(url_for("flipbooks"))
    rows = Flipbook.query.order_by(Flipbook.created_at.desc()).all()
    return render_template("flipbooks.html", rows=rows)


@app.route("/admin/flipbooks/<int:book_id>/delete", methods=["POST"])
@admin_required
def flipbook_delete(book_id):
    book = Flipbook.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash("Flipbook deleted.")
    return redirect(url_for("flipbooks"))


@app.route("/f/<slug>")
def flipbook_view(slug):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    first = book.pages[0] if book.pages else None
    return render_template("flipbook_view.html", book=book, first=first)


@app.route("/f/<slug>/page/<int:num>.png")
def flipbook_page(slug, num):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    page = FlipbookPage.query.filter_by(flipbook_id=book.id, page_num=num).first()
    if not page:
        abort(404)
    return Response(page.image, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    # NOTE: not 5060/5061 — Chrome refuses to load that port (ERR_UNSAFE_PORT — both are SIP ports)
    app.run(debug=True, port=5062)
