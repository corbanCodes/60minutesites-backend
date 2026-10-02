"""60 Minute Sites — Backend HQ v4
Admin + customer accounts · CRM (pipeline, board, tasks, revenue) · Forms
(Formspree-style, feeds the CRM) · WYSIWYG site builder on real 60MS templates
(+ AI text/design) · GitHub→Netlify publishing · Flipbooks.

Persistence: set DATABASE_URL (Railway Postgres) and everything survives
deploys. Falls back to local SQLite (data.db) for development.
AI: set OPENAI_API_KEY (and optionally OPENAI_MODEL) to enable editor AI and
AI replies in client chat widgets (/admin/chat — capped per month per widget).
Publishing: set GITHUB_TOKEN (fine-grained PAT, Contents read/write) once and
every editor Save commits to the linked repo. APP_TZ controls display times.
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import pymupdf as fitz  # PyMuPDF
import requests as http
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
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
# Name the driver explicitly. SQLAlchemy 2.1 changed what a bare
# "postgresql://" means -- it now defaults to psycopg v3 rather than psycopg2 --
# so a plain URL silently picks a different driver depending on which
# SQLAlchemy a build happens to resolve. This app ships psycopg2-binary.
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
os.makedirs(os.path.join(_here, "instance"), exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

# SQLite on a hosted container = data erased on every deploy. Detect and scream.
USING_SQLITE = db_url.startswith("sqlite")
IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT")
                  or os.environ.get("RAILWAY_PROJECT_ID"))

app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme60")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
def _env_any(*names, default=""):
    """Find an env var regardless of case or -/_ separators, so RESEND_API_KEY,
    resend-api, Resend_Api etc. all resolve to the same value."""
    wanted = {"".join(ch for ch in n.lower() if ch.isalnum()) for n in names}
    for k, v in os.environ.items():
        if "".join(ch for ch in k.lower() if ch.isalnum()) in wanted and v:
            return v
    return default


RESEND_KEY = _env_any("RESEND_API_KEY", "RESEND_API", "RESEND_KEY", "RESEND")
RESEND_FROM = os.environ.get("RESEND_FROM", "60MS HQ <onboarding@resend.dev>")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Meta lead-ads webhook (Instant Forms) — all optional; feature is off until set
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "")
# domain aliases: hosts in REDIRECT_HOSTS 301 to CANONICAL_HOST (SEO: one URL)
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().lower()
REDIRECT_HOSTS = {h.strip().lower() for h in
                  os.environ.get("REDIRECT_HOSTS", "").split(",") if h.strip()}
try:
    LOCAL_TZ = ZoneInfo(os.environ.get("APP_TZ", "America/Los_Angeles"))
except Exception:
    LOCAL_TZ = timezone.utc

db = SQLAlchemy(app)

LEAD_STATUSES = ["New", "Contacted", "Qualified", "Booked", "Built", "Client", "Dead"]
STATUS_COLORS = {
    "New": "#2E86DE", "Contacted": "#9A6B14", "Qualified": "#0F8A72", "Booked": "#E85D2A",
    "Built": "#8E44AD", "Client": "#2E7D4F", "Dead": "#888888",
}
# how much of a deal's monthly value counts toward the weighted pipeline
STATUS_WEIGHTS = {"New": 0.10, "Contacted": 0.25, "Qualified": 0.35, "Booked": 0.50, "Built": 0.75}
LEAD_FIELDS = ["name", "phone", "email", "business", "business_type"]
# CSV import: mappable targets (key, label shown in the mapping dropdowns)
CSV_FIELDS = [("name", "Name"), ("first_name", "First name"), ("last_name", "Last name"),
              ("phone", "Phone"), ("phone_2", "Phone 2"), ("email", "Email"),
              ("business", "Business"), ("business_type", "Business type"),
              ("title", "Job title"), ("website", "Website"),
              ("address", "Address"), ("city", "City"), ("state", "State"),
              ("zip", "ZIP"), ("source", "Source"), ("status", "Status"),
              ("deal_value", "Deal value ($/mo)"), ("note", "Note"),
              ("created_at", "Date added"), ("skip", "— ignore column —")]
# mapped types with no Lead column — they land in an "Imported details" note
CSV_EXTRA_FIELDS = {"phone_2": "Phone 2", "title": "Title", "website": "Website",
                    "address": "Address", "city": "City", "state": "State",
                    "zip": "ZIP"}
# Everything a customer can be given or denied, in nav order. One list drives
# the sidebar AND the per-client control panel, so they can never disagree.
# `flag` names a feature that must also be switched on; None means the tool is
# on by default and can only be taken away.
TOOLS = [
    # key          label             section     url                icon                        flag
    ("dashboard",  "Dashboard",      "Work",     "/admin",          "bi-grid-1x2",              None),
    ("crm",        "CRM",            "Work",     "/admin/crm",      "bi-kanban",                None),
    ("tasks",      "Tasks",          "Work",     "/admin/tasks",    "bi-check2-square",         None),
    ("dialer",     "Calling",        "Work",     "/dialer",         "bi-telephone-outbound",    "dialer"),
    ("agents",     "AI agents",      "Work",     "/dialer/agents",  "bi-robot",                 "dialer"),
    ("enrich",     "Enrichment",     "Work",     "/enrich",         "bi-binoculars",            "enrichment"),
    ("sites",      "Sites",          "Build",    "/admin/sites",    "bi-window-sidebar",        None),
    ("forms",      "Forms",          "Build",    "/admin/forms",    "bi-envelope-paper",        None),
    ("chat",       "Chat",           "Build",    "/admin/chat",     "bi-chat-dots",             None),
    ("funnels",    "Funnels",        "Build",    "/admin/funnels",  "bi-lightning-charge",      None),
    ("invoices",   "Invoices",       "Build",    "/admin/invoices", "bi-receipt",               None),
    ("ai_studio",  "AI Studio",      "Build",    "/admin/ai-studio", "bi-stars",                None),
    ("email",      "Email",          "Build",    "/admin/email",    "bi-envelope-at",           None),
    ("team",       "Team",           "Account",  "/admin/team",     "bi-people-fill",           "multi_user"),
]
TOOL_LABELS = {k: lbl for k, lbl, _, _, _, _ in TOOLS}
# Tools a customer always keeps -- taking these away leaves them with nothing.
TOOLS_ALWAYS_ON = {"dashboard"}
TOOL_BLURBS = {
    "dashboard": "Their landing page. Cannot be switched off.",
    "crm": "Leads, pipeline, notes and the kanban board.",
    "tasks": "Their own follow-up list.",
    "dialer": "The phone system. Needs the AI calling add-on.",
    "enrich": "Website research and email writing. Needs the enrichment add-on.",
    "sites": "The website editor and publishing.",
    "forms": "Lead capture forms they can embed.",
    "chat": "The AI chat widget for their site.",
    "funnels": "Ad landing pages.",
    "invoices": "The invoice builder.",
    "ai_studio": "Blog and marketing copy.",
    "email": "Their mailbox details.",
    "team": "Seats and roles. Needs the multi-user add-on.",
}

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
    # --- teams: NULL account_id means "this user IS an account owner", which is
    # every row that existed before the teams feature shipped.
    account_id = db.Column(db.Integer, nullable=True, index=True)
    role = db.Column(db.String(20), default="owner")
    active = db.Column(db.Boolean, default=True)
    seat_limit = db.Column(db.Integer, nullable=True)   # owners only; NULL = 1
    feature_multi_user = db.Column(db.Boolean, default=False)
    feature_dialer = db.Column(db.Boolean, default=False)
    feature_enrichment = db.Column(db.Boolean, default=False)
    # Comma-separated tool keys this account should NOT see. Empty means show
    # everything, which is what every account did before this existed -- so
    # adding the column changed nothing for anyone.
    hidden_tools = db.Column(db.String(600), default="")
    last_login_at = db.Column(db.DateTime, nullable=True)
    job_title = db.Column(db.String(80), default="")

    @property
    def is_owner(self):
        return self.account_id is None

    @property
    def owner_account_id(self):
        return self.account_id or self.id

    @property
    def seats(self):
        return self.seat_limit or 1

    @property
    def hidden(self):
        return {t.strip() for t in (self.hidden_tools or "").split(",") if t.strip()}

    def can_see(self, tool_key):
        return tool_key not in self.hidden


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
    # --- dialer: all nullable, all default to today's behaviour
    assignee_id = db.Column(db.Integer, nullable=True, index=True)
    phone_e164 = db.Column(db.String(20), default="")
    phone_key = db.Column(db.String(20), default="", index=True)
    line_type = db.Column(db.String(16), default="")
    line_type_checked_at = db.Column(db.DateTime, nullable=True)
    line_type_raw = db.Column(db.Text, default="")
    carrier = db.Column(db.String(120), default="")
    timezone = db.Column(db.String(40), default="")
    state_code = db.Column(db.String(2), default="")
    consent_status = db.Column(db.String(20), default="none")
    consent_source = db.Column(db.String(120), default="")
    consent_at = db.Column(db.DateTime, nullable=True)
    do_not_call = db.Column(db.Boolean, default=False)
    opt_out_at = db.Column(db.DateTime, nullable=True)
    opt_out_source = db.Column(db.String(60), default="")
    last_called_at = db.Column(db.DateTime, nullable=True)
    call_count = db.Column(db.Integer, default=0)
    last_outcome = db.Column(db.String(30), default="")
    tags = db.Column(db.String(500), default="")

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

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
    # NULL assignee = the account owner's own task (every pre-teams row)
    assignee_id = db.Column(db.Integer, nullable=True, index=True)


class EmailAccount(db.Model):
    """A client mailbox we provisioned (Purelymail). Password is stored so the
    CLIENT can read it from their dashboard — shared-knowledge credential by design."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    address = db.Column(db.String(200), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    author_id = db.Column(db.Integer, nullable=True)        # NULL = system/legacy
    kind = db.Column(db.String(20), default="note")         # note|system|call|ai_summary


class Form(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    redirect_url = db.Column(db.String(400), default="")
    notify_emails = db.Column(db.String(500), default="")  # comma-separated extra recipients
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    business_name = db.Column(db.String(120), nullable=False)
    template = db.Column(db.String(80), default="")
    github_repo = db.Column(db.String(200), default="")  # "owner/repo" -> Netlify auto-deploy
    live_url = db.Column(db.String(300), default="")  # client's real domain (ads point here)
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
    toc = db.Column(db.Text, default="")  # JSON [{"title": ..., "page": 1-based}]
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pages = db.relationship("FlipbookPage", backref="flipbook",
                            cascade="all, delete-orphan",
                            order_by="FlipbookPage.page_num")


class FlipbookPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flipbook_id = db.Column(db.Integer, db.ForeignKey("flipbook.id"), nullable=False)
    page_num = db.Column(db.Integer, nullable=False)
    image = db.Column(db.LargeBinary, nullable=False)
    text = db.Column(db.Text, default="")  # extracted at upload -> powers search
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)


class ChatWidget(db.Model):
    """Embeddable AI chat bubble for a client site. One per business; the
    embed script works on any host and the whole thing can be switched off
    here without touching the client's site."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    business_name = db.Column(db.String(120), nullable=False)
    enabled = db.Column(db.Boolean, default=True)          # master on/off
    ai_enabled = db.Column(db.Boolean, default=True)       # AI replies on/off
    monthly_limit = db.Column(db.Integer, default=50)      # AI replies / month
    used_month = db.Column(db.String(7), default="")       # "2026-08"
    used_count = db.Column(db.Integer, default=0)
    system_prompt = db.Column(db.Text, default="")
    greeting = db.Column(db.String(300), default="")
    accent = db.Column(db.String(9), default="#2E86DE")
    contact_phone = db.Column(db.String(40), default="")   # powers Call + Text chips
    contact_email = db.Column(db.String(120), default="")
    booking_url = db.Column(db.String(300), default="")
    notify_email = db.Column(db.String(120), default="")   # blank = owner/admin email
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ChatConversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    widget_id = db.Column(db.Integer, db.ForeignKey("chat_widget.id"), nullable=False)
    visitor_name = db.Column(db.String(120), default="")
    visitor_phone = db.Column(db.String(40), default="")
    visitor_email = db.Column(db.String(120), default="")
    page_url = db.Column(db.String(400), default="")
    notified = db.Column(db.Boolean, default=False)        # first-message email sent
    lead_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    messages = db.relationship("ChatMessage", backref="conversation",
                               cascade="all, delete-orphan",
                               order_by="ChatMessage.id")


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversation.id"),
                                nullable=False)
    role = db.Column(db.String(12), nullable=False)        # user | assistant
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


def ensure_schema():
    """create_all + additive column migration so existing DBs upgrade in place.

    Gunicorn boots several workers at once and every one of them runs this.
    Two workers can both see a column as missing and both try to add it, and
    the loser crashes -- which on Railway is a boot loop, not a warning. A
    Postgres advisory lock makes one worker do the work while the others wait,
    and each statement is still wrapped individually so an unexpected race
    degrades to a skipped statement rather than a dead deploy.
    """
    if db.engine.dialect.name != "postgresql":
        _ensure_schema_inner()
        return
    # A Postgres advisory lock belongs to a CONNECTION, not a transaction, so
    # lock, work and unlock all have to happen on the SAME connection -- and
    # it has to be one we hold open ourselves, because engine.begin() returns
    # its connection to the pool on commit. pg_try_advisory_lock rather than
    # the blocking form: if another worker is already migrating, this one
    # waits a moment and carries on reading rather than hanging at boot.
    import time
    conn = db.engine.connect()
    try:
        got = False
        for _ in range(30):
            got = bool(conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(60604060)").scalar())
            if got:
                break
            time.sleep(1)
        if not got:
            print("[schema] another worker is migrating; continuing")
            return
        try:
            _ensure_schema_inner()
        finally:
            conn.exec_driver_sql("SELECT pg_advisory_unlock(60604060)")
    finally:
        conn.close()


def _ensure_schema_inner():
    try:
        db.create_all()
    except Exception as e:          # another worker won the race to CREATE
        print(f"[schema] create_all: {type(e).__name__}: {e}")
    insp = inspect(db.engine)
    wanted = {
        "site": {"owner_id": "INTEGER", "template": "VARCHAR(80)", "html": "TEXT",
                 "github_repo": "VARCHAR(200)", "live_url": "VARCHAR(300)",
                 "last_push_at": "TIMESTAMP",
                 "last_push_ok": "BOOLEAN", "last_push_msg": "VARCHAR(300)"},
        "form": {"notify_emails": "VARCHAR(500)"},
        "user": {"phone": "VARCHAR(40)", "monthly_price": "FLOAT",
                 "setup_fee": "FLOAT",
                 # --- teams + dialer (additive; NULL/constant defaults only) ---
                 "account_id": "INTEGER", "role": "VARCHAR(20)",
                 "active": "BOOLEAN", "seat_limit": "INTEGER",
                 "feature_multi_user": "BOOLEAN", "feature_dialer": "BOOLEAN",
                 "feature_enrichment": "BOOLEAN", "hidden_tools": "VARCHAR(600)",
                 "last_login_at": "TIMESTAMP", "job_title": "VARCHAR(80)"},
        "flipbook": {"toc": "TEXT"},
        # --- dialer's own tables. create_all() makes a NEW table but never
        # alters one that already exists, so a column added to a dialer model
        # after its table shipped needs a line here exactly like any other.
        "dialer_settings": {"elevenlabs_webhook_error": "VARCHAR(400)"},
        "ai_agent": {"transfer_style": "VARCHAR(20)",
                     "transfer_line": "VARCHAR(300)",
                     "opening_mode": "VARCHAR(10)",
                     "prompt_override": "TEXT"},
        "flipbook_page": {"text": "TEXT"},
        # --- dialer: columns on existing CRM tables ---
        "task": {"assignee_id": "INTEGER"},
        "note": {"author_id": "INTEGER", "kind": "VARCHAR(20)"},
        # NOTE: one entry per table. A duplicate key here is silently
        # discarded by Python, which is how owner_id/form_id/deal_value went
        # missing from this list for months.
        "lead": {"owner_id": "INTEGER", "form_id": "INTEGER",
                 "deal_value": "FLOAT",
                 "assignee_id": "INTEGER", "phone_e164": "VARCHAR(20)",
                 "phone_key": "VARCHAR(20)", "line_type": "VARCHAR(16)",
                 "line_type_checked_at": "TIMESTAMP", "line_type_raw": "TEXT",
                 "carrier": "VARCHAR(120)", "timezone": "VARCHAR(40)",
                 "state_code": "VARCHAR(2)", "consent_status": "VARCHAR(20)",
                 "consent_source": "VARCHAR(120)", "consent_at": "TIMESTAMP",
                 "do_not_call": "BOOLEAN", "opt_out_at": "TIMESTAMP",
                 "opt_out_source": "VARCHAR(60)", "last_called_at": "TIMESTAMP",
                 "call_count": "INTEGER", "last_outcome": "VARCHAR(30)",
                 "tags": "VARCHAR(500)"},
    }
    added = {}
    tables_now = set(insp.get_table_names())
    for table, cols in wanted.items():
        if table not in tables_now:
            continue
        with db.engine.begin() as conn:
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col in have:
                    continue
                try:
                    conn.execute(text(
                        f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}'))
                    added.setdefault(table, []).append(col)
                except Exception as e:
                    # already there (a racing worker), or the DDL is wrong --
                    # either way, never take the app down over one column
                    print(f"[schema] {table}.{col}: {type(e).__name__}: {e}")
    # Added columns arrive NULL. Give the ones with meaning a value so every
    # EXISTING row keeps behaving exactly as it did before this deploy:
    # every current user is an active owner with both new features OFF.
    backfill = {
        ("user", "role"): "'owner'", ("user", "active"): "TRUE",
        ("user", "feature_multi_user"): "FALSE",
        ("user", "feature_dialer"): "FALSE",
        ("user", "feature_enrichment"): "FALSE",
        # empty means "hide nothing", which is exactly how every existing
        # account already behaves
        ("user", "hidden_tools"): "''",
        ("note", "kind"): "'note'",
        ("lead", "do_not_call"): "FALSE", ("lead", "call_count"): "0",
        ("lead", "consent_status"): "'none'", ("lead", "tags"): "''",
        # Waiting for the other person to speak is the default everywhere,
        # so an agent that predates the column gets it too rather than
        # inheriting the old talk-over-the-hello behaviour by accident.
        ("ai_agent", "opening_mode"): "'wait'",
        ("ai_agent", "transfer_style"): "'brief'",
    }
    for (table, col), value in backfill.items():
        if col not in added.get(table, []):
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'UPDATE "{table}" SET {col} = {value} WHERE {col} IS NULL'))
        except Exception as e:
            print(f"[schema] backfill {table}.{col}: {type(e).__name__}: {e}")
    if added:
        print(f"[schema] added columns: {added}")


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


def demo_uid():
    """The demo account's user id (cached per request), or None."""
    if not hasattr(g, "_demo_uid"):
        u = User.query.filter_by(email=DEMO_EMAIL).first()
        g._demo_uid = u.id if u else None
    return g._demo_uid


def account_owner_id(user):
    """The id that owns the DATA for this user. A team member reads and writes
    the account owner's rows; an owner (every pre-teams user) is their own.
    This single function is why adding seats changed no existing behaviour."""
    if user is None:
        return None
    return getattr(user, "account_id", None) or user.id


def owner_filter(query, model):
    """Admin sees everything EXCEPT the demo account's rows (those only exist
    when you log in as the demo user); customers see their own account's rows."""
    role, user = current_user()
    if role == "admin":
        duid = demo_uid()
        if duid is not None:
            return query.filter(db.or_(model.owner_id.is_(None),
                                       model.owner_id != duid))
        return query
    return query.filter(model.owner_id == account_owner_id(user))


def my_tasks_query():
    """Tasks are personal: the admin's day view shows the admin's own tasks,
    not every customer's (oversight still exists via each lead's page).

    On a team account the rows still belong to the OWNER (owner_id), and
    assignee_id says whose day it lands on. A solo account has no members and
    no assignees, so this returns exactly what it always did."""
    role, user = current_user()
    if role == "admin":
        return Task.query.filter(Task.owner_id.is_(None))
    q = Task.query.filter(Task.owner_id == account_owner_id(user))
    if user.account_id:                      # a member: only what's theirs
        return q.filter(Task.assignee_id == user.id)
    return q.filter(db.or_(Task.assignee_id.is_(None),
                           Task.assignee_id == user.id))


def my_owner_id():
    role, user = current_user()
    return None if role == "admin" else account_owner_id(user)


def can_touch(obj):
    role, user = current_user()
    return role == "admin" or (user and obj.owner_id == account_owner_id(user))


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


def digits_only(s):
    return re.sub(r"\D", "", s or "")


def phone_key(s):
    """Canonical phone for duplicate matching: digits, minus a US country code
    ('+1 415 555 0100' and '(415) 555-0100' must collide)."""
    d = digits_only(s)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


def csv_safe(v):
    """Excel/Sheets execute cells starting with = + - @ as formulas — a lead
    named '=HYPERLINK(...)' from a public form must not run on YOUR machine."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def parse_flex_date(s):
    """Best-effort date parsing for CSV imports ('old' leads keep their real
    date). Naive inputs are read in APP_TZ; stored naive UTC. None if hopeless."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        for f in ("%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%m/%d/%y",
                  "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(s, f)
                break
            except ValueError:
                continue
    if dt is None:
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


_EXTRA_LABELS = {
    "has_website": "Has website", "website_url": "Current site",
    "timeline": "Timeline", "goals": "Goals", "ads_experience": "Ran ads before",
    "wants_ads": "Wants ads", "ad_budget": "Ad budget", "can_pay": "Can pay $100/mo",
    "fill_seconds": "Time to fill", "landing_page": "Landing page",
    "submission_type": "Submission", "traffic_source": "Traffic source",
    "utm_source": "UTM source", "utm_medium": "UTM medium",
    "utm_campaign": "UTM campaign", "utm_content": "UTM content / ad",
    "phone_2": "Phone 2", "title": "Title", "current_website": "Current website",
}


@app.template_filter("extras_kv")
def filter_extras_kv(body):
    """Turn a 'Form extras: {json}' or 'Imported details: k: v · ...' note into an
    ordered list of (label, value) pairs for tidy boxes. Returns None otherwise."""
    if body.startswith("Form extras: "):
        try:
            d = json.loads(body[len("Form extras: "):])
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None
        out = []
        for k, v in d.items():
            if v in ("", None):
                continue
            label = _EXTRA_LABELS.get(k, k.replace("_", " ").capitalize())
            if k == "fill_seconds":
                v = f"{v}s"
            out.append((label, str(v)))
        return out or None
    if body.startswith("Imported details: "):
        out = []
        for part in body[len("Imported details: "):].split(" · "):
            if ": " in part:
                k, v = part.split(": ", 1)
                out.append((k, v))
        return out or None
    return None


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
    if USING_SQLITE and IS_RAILWAY:
        alerts.append(dict(
            level="critical", icon="bi-database-x", guide="postgres",
            title="DATABASE IS TEMPORARY — every deploy erases ALL CRM data",
            body="No DATABASE_URL is set, so the app is writing to a throwaway file inside "
                 "the container. Leads, notes, customers, tasks — all of it vanishes on the "
                 "next deploy. Add the Postgres service NOW (guide below), and export a "
                 "backup (Setup → Backups) after every work session until this alert is gone."))
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


# url prefix -> tool key, for enforcing visibility at the route, not just in
# the sidebar. Hiding a menu item is decoration; this is the actual gate.
TOOL_PREFIXES = [
    ("/admin/crm", "crm"), ("/admin/leads", "crm"),
    ("/admin/tasks", "tasks"),
    ("/admin/sites", "sites"), ("/edit/", "sites"), ("/edit-page/", "sites"),
    ("/admin/forms", "forms"),
    ("/admin/chat", "chat"),
    ("/admin/funnels", "funnels"),
    ("/admin/invoices", "invoices"),
    ("/admin/ai-studio", "ai_studio"),
    ("/dialer/agents", "agents"),
    ("/admin/email", "email"),
]


@app.before_request
def _enforce_tool_visibility():
    """A tool the account owner switched off is gone, not merely hidden.

    Admin is never gated. Accounts that have hidden nothing -- which is every
    account that existed before this feature -- take the fast path out.
    """
    path = request.path
    if not path.startswith(("/admin", "/edit/", "/edit-page/")):
        return None
    role, user = current_user()
    if role != "user" or user is None:
        return None
    owner = db.session.get(User, user.account_id or user.id)
    if owner is None or not owner.hidden_tools:
        return None
    hidden = owner.hidden
    for prefix, key in TOOL_PREFIXES:
        if path.startswith(prefix) and key in hidden and key not in TOOLS_ALWAYS_ON:
            abort(404)
    return None


# A tool whose code is not deployed yet must not appear in the menu. Matching
# against url_map is no good here: static_url_path is "" so the marketing-site
# static route matches every path. Ask the blueprint registry instead.
TOOL_BLUEPRINT = {"dialer": "dialer", "agents": "dialer", "enrich": "enrich",
                  "team": "teams"}


def _mounted(key):
    """True when the blueprint that serves this tool is registered."""
    bp = TOOL_BLUEPRINT.get(key)
    return True if bp is None else bp in app.blueprints


def visible_tools(role, user):
    """The sidebar, resolved for whoever is looking.

    Admin sees everything. A customer sees a tool when its add-on flag is on
    (if it needs one) AND the account owner has not hidden it. An account that
    has never been touched hides nothing, so this returns exactly what the
    sidebar showed before any of this existed.
    """
    from dialer import disabled as dialer_off
    owner = None
    if user is not None:
        owner = db.session.get(User, user.account_id or user.id)
    hidden = owner.hidden if owner is not None else set()
    flags = {
        "dialer": (role == "admin") or bool(owner and owner.feature_dialer),
        "multi_user": (role == "admin") or bool(owner and owner.feature_multi_user),
        "enrichment": (role == "admin") or bool(owner and owner.feature_enrichment),
    }
    out = []
    for key, label, section, url, icon, flag in TOOLS:
        if flag and not flags.get(flag):
            continue
        if key == "dialer" and dialer_off():
            continue
        # Never advertise a tool whose blueprint is not actually mounted. A
        # menu item that 404s is worse than a missing one, and this makes the
        # nav self-healing: the item appears the moment the routes exist.
        if not _mounted(key):
            continue
        if role != "admin" and key in hidden and key not in TOOLS_ALWAYS_ON:
            continue
        if key == "team" and role != "admin":
            from teams import perms as _p
            if not _p.can(user, "team.manage"):
                continue
        out.append({"key": key, "label": label, "section": section,
                    "url": url, "icon": icon})
    return out


@app.context_processor
def inject_globals():
    role, user = current_user()
    ctx = {"STATUSES": LEAD_STATUSES, "STATUS_COLORS": STATUS_COLORS,
           "STATUS_WEIGHTS": STATUS_WEIGHTS, "TASK_KINDS": TASK_KINDS,
           "TASK_ICONS": TASK_ICONS, "CSV_FIELDS": CSV_FIELDS,
           "role": role, "me": user, "alerts": [], "alert_count": 0,
           "show_dialer": False, "show_team": False, "can": lambda p: False}
    # Nav items for the two flagged features. An account without the flag never
    # sees them, and the blueprints 404 anyway.
    if role:
        try:
            from dialer import disabled as _dialer_off
            from dialer.settings_store import dialer_enabled, teams_enabled
            from teams import perms as _perms
            ctx["show_dialer"] = bool(dialer_enabled()) and not _dialer_off()
            ctx["show_team"] = bool(teams_enabled()) and _perms.can(user, "team.manage")
            ctx["can"] = lambda p, _u=user: _perms.can(_u, p)
            from dialer.models import DISPOSITION_LABELS
            ctx["DISPOSITION_LABELS"] = DISPOSITION_LABELS
            ctx["nav_tools"] = visible_tools(role, user)
        except Exception:
            ctx["nav_tools"] = []
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


PAGE_RE = re.compile(r"^[A-Za-z0-9._-]+\.html$")


def github_list_pages(repo):
    """Root-level .html files in the repo, or None on any failure."""
    if not (repo and GITHUB_TOKEN):
        return None
    try:
        r = http.get(f"https://api.github.com/repos/{repo}/contents/", timeout=20,
                     headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                              "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return None
        return sorted(f["name"] for f in r.json()
                      if f.get("type") == "file" and f["name"].endswith(".html"))
    except Exception:
        return None


def github_fetch_file(repo, path):
    hdr = {"Accept": "application/vnd.github.raw"}
    if GITHUB_TOKEN:
        hdr["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = http.get(f"https://api.github.com/repos/{repo}/contents/{path}",
                     headers=hdr, timeout=20)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def github_push_file(repo, path, content):
    """Commit one file to the repo. Returns (ok, msg)."""
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN not set on the server — see Setup"
    # media uploaded through the editor lives on HQ — absolutize for client domains
    content = content.replace('src="/media/', 'src="https://60minutesites.com/media/')
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    hdr = {"Authorization": f"Bearer {GITHUB_TOKEN}",
           "Accept": "application/vnd.github+json"}
    try:
        r = http.get(url, headers=hdr, timeout=20)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {"message": f"Edit {path} via 60MS HQ editor",
                   "content": base64.b64encode(content.encode()).decode()}
        if sha:
            payload["sha"] = sha
        r2 = http.put(url, headers=hdr, json=payload, timeout=30)
        if r2.status_code in (200, 201):
            return True, "Live — committed to GitHub, Netlify is redeploying"
        return False, GITHUB_ERRORS.get(r2.status_code, f"GitHub error {r2.status_code}")
    except Exception as e:
        return False, f"Couldn't reach GitHub ({type(e).__name__})"


def form_tag(form):
    """Stable subject token for inbox rules: C<client id>-F<form id>.
    'subject contains [60MS C3' = one forwarding rule per client;
    'subject contains C3-F12]' = one rule per form."""
    return f"[60MS C{form.owner_id or 0}-F{form.id}]"


def notify_lead(form, lead):
    """Email the form's owner about a new lead via Resend (best-effort)."""
    if not RESEND_KEY:
        return
    owner = db.session.get(User, form.owner_id) if form.owner_id else None
    to = [e.strip() for e in (form.notify_emails or "").split(",") if e.strip()]
    if not to:
        to = [owner.email] if owner and owner.email else ([ADMIN_EMAIL] if ADMIN_EMAIL else [])
    if not to:
        return
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#888'>{k}</td><td><b>{v}</b></td></tr>"
                   for k, v in [("Name", lead.name), ("Cell", lead.phone), ("Email", lead.email),
                                ("Business", lead.business), ("Source", lead.source)] if v)
    payload = {"from": RESEND_FROM, "to": to[:10],
               "subject": f"New lead: {lead.name} — {form.name} {form_tag(form)}",
               "html": f"<h2 style='font-family:sans-serif'>New lead from “{form.name}”</h2>"
                       f"<table style='font-family:sans-serif;font-size:15px'>{rows}</table>"
                       f"<p style='font-family:sans-serif;color:#888'>It's already in your CRM.</p>"}
    if lead.email:
        payload["reply_to"] = lead.email  # hitting Reply answers the LEAD
    try:
        http.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {RESEND_KEY}"},
                  json=payload, timeout=15)
    except Exception:
        pass


def send_email(to, subject, html, reply_to=None):
    """Best-effort transactional email via Resend; never raises."""
    if not (RESEND_KEY and to):
        return
    payload = {"from": RESEND_FROM, "to": [to] if isinstance(to, str) else to,
               "subject": subject, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        http.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {RESEND_KEY}"},
                  json=payload, timeout=15)
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
    html = re.sub(r"<script data-crm-mirror.*?</script>", "", html, flags=re.S)
    html = html.replace('<div id="site-header"></div>', "")
    html = html.replace('<div id="site-footer"></div>', "")
    html = re.sub(r"<title>.*?</title>",
                  f"<title>{business_name}</title>", html, count=1, flags=re.S)
    return html


EDITOR_SNIPPET = ('<link rel="stylesheet" href="/static-admin/editor.css" data-wys="1">'
                  '<script src="/static-admin/editor.js" data-wys="1" defer></script>')


_EDITOR_V = str(int(os.path.getmtime(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "editor.js"))))


def hq_origin():
    """Public origin, HTTPS-correct behind a TLS-terminating proxy (Railway
    forwards plain HTTP internally, so request.host_url says http://).
    Honors X-Forwarded-Proto; forces https for any non-local host."""
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    host = request.host
    if not proto:
        proto = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    return f"{proto}://{host}"


def editor_snippet():
    """Editor css/js with ABSOLUTE urls — an injected <base> tag must never
    redirect them to the client's domain. ?v busts stale browser caches on
    every deploy."""
    hq = hq_origin()
    return (f'<link rel="stylesheet" href="{hq}/static-admin/editor.css?v={_EDITOR_V}" data-wys="1">'
            f'<script src="{hq}/static-admin/editor.js?v={_EDITOR_V}" data-wys="1" defer></script>')


def strip_editor_artifacts(html):
    html = re.sub(r"<[^>]+data-wys=\"1\"[^>]*>\s*(</script>)?", "", html)
    html = re.sub(r"<div id=\"wys-toolbar\".*?</div>\s*(?=</body>)", "", html, flags=re.S)
    html = html.replace(' contenteditable="true"', "").replace(" contenteditable=\"\"", "")
    html = re.sub(r"<style id=\"wys-hover-style\">.*?</style>", "", html, flags=re.S)
    return html


# ---------------------------------------------------------------- auth + home
@app.before_request
def canonical_redirect():
    """60minute-sites.com (and any listed alias) -> the canonical domain.
    GET/HEAD only: form POSTs from embeds must never bounce through a 301."""
    if (CANONICAL_HOST and request.method in ("GET", "HEAD")
            and request.host.split(":")[0].lower() in REDIRECT_HOSTS):
        return redirect(f"https://{CANONICAL_HOST}{request.full_path.rstrip('?')}",
                        code=301)


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(404)
def extensionless_pages(e):
    """Netlify served pretty URLs (/pricing -> pricing.html); the indexed web
    knows those URLs, so resolve them here too instead of 404ing."""
    p = request.path.strip("/")
    if (p and request.method in ("GET", "HEAD")
            and "." not in os.path.basename(p) and ".." not in p):
        for cand in (p + ".html", p + "/index.html"):
            if os.path.isfile(os.path.join(app.static_folder, cand)):
                return send_from_directory(app.static_folder, cand)
    return e


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
            if user.active is False:
                flash("That account has been deactivated — ask your account "
                      "admin to turn it back on.", "error")
                return render_template("login.html")
            session.clear()
            session["uid"] = user.id
            user.last_login_at = utcnow_naive()
            db.session.commit()
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("No match — check your email and password.", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if request.form.get("_gotcha"):  # honeypot — bots fill every field
            return redirect(url_for("login"))
        # invite-only: accounts are created by 60MS, not by the public. Kills bot
        # signups outright, which is why we don't need 2FA on this surface.
        if request.form.get("access_code", "") != ADMIN_PASSWORD:
            flash("That access code isn't right — accounts are created by 60 Minute "
                  "Sites. Call 1-800-60-4-LIFE and we'll set you up.", "error")
            return render_template("signup.html")
        if not (name and email and len(password) >= 6):
            flash("Name, email, and a 6+ character password required.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email already has an account — log in instead.", "error")
        else:
            # Both features are off unless explicitly ticked. The access code
            # has already been checked above, so only 60MS can set these.
            want_team = bool(request.form.get("feature_multi_user"))
            want_dialer = bool(request.form.get("feature_dialer"))
            want_enrich = bool(request.form.get("feature_enrichment"))
            seats = request.form.get("seat_limit", type=int) or 5
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password),
                        role="owner", active=True,
                        feature_multi_user=want_team,
                        feature_dialer=want_dialer,
                        feature_enrichment=want_enrich,
                        seat_limit=(max(1, min(seats, 200)) if want_team else 1))
            db.session.add(user)
            db.session.commit()
            send_email(email, "Welcome to 60 Minute Sites",
                       f"<div style='font-family:sans-serif;font-size:15px'>"
                       f"<h2>Welcome aboard, {name}!</h2>"
                       f"<p>Your 60 Minute Sites account is ready. Log in any time at "
                       f"<a href='https://60minutesites.com/login'>60minutesites.com/login</a>.</p>"
                       f"<p>Questions? Just reply to this email or call "
                       f"<b>1-800-60-4-LIFE</b> — a real person answers.</p>"
                       f"<p>— Corban, 60 Minute Sites</p></div>",
                       reply_to="hello@60minute-sites.com")
            if ADMIN_EMAIL:
                send_email(ADMIN_EMAIL, f"New HQ signup: {name}",
                           f"<p style='font-family:sans-serif'>{name} ({email}) just "
                           f"created an account. They're in your CRM as a Self-signup lead.</p>")
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
    # admin's dashboard tracks HIS pipeline; customer accounts see their own
    lead_q = (Lead.query.filter(Lead.owner_id.is_(None)) if session.get("admin")
              else owner_filter(Lead.query, Lead))
    stats = {
        "leads": lead_q.count(),
        "booked": lead_q.filter(Lead.status.in_(["Booked", "Built", "Client"])).count(),
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
    recent = lead_q.order_by(Lead.created_at.desc()).limit(6).all()
    return render_template("dashboard.html", stats=stats, recent=recent,
                           overdue=overdue, today=today, task_leads=task_leads)


# ------------------------------------------------------------------------ crm
def scoped_leads(query):
    """Lead scoping for CRM views. Customers: always their own. Admin: ?scope=
    'mine' (default — owner_id NULL), 'all' (everyone except demo), or a
    customer id to peek at one account without logging in as them."""
    role, user = current_user()
    if role != "admin":
        return query.filter(Lead.owner_id == account_owner_id(user))
    s = request.args.get("scope", "mine")
    if s == "all":
        duid = demo_uid()
        if duid is not None:
            return query.filter(db.or_(Lead.owner_id.is_(None),
                                       Lead.owner_id != duid))
        return query
    try:
        return query.filter(Lead.owner_id == int(s))
    except (TypeError, ValueError):
        return query.filter(Lead.owner_id.is_(None))  # 'mine' and anything odd


def crm_scope_ctx():
    """Template context for the scope dropdown (admin only)."""
    if not session.get("admin"):
        return {"scope": "", "scope_users": []}
    duid = demo_uid()
    users = User.query.order_by(User.name).all()
    return {"scope": request.args.get("scope", "mine"),
            "scope_users": [u for u in users if u.id != duid]}


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
    query = scoped_leads(Lead.query)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like),
                                    Lead.email.ilike(like), Lead.business.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(Lead.created_at.desc()).all()
    return render_template("crm.html", rows=rows, q=q, status=status,
                           next_steps=_next_steps(rows), now=utcnow_naive(),
                           **crm_scope_ctx())


@app.route("/admin/crm/board")
@login_required
def crm_board():
    rows = scoped_leads(Lead.query).order_by(Lead.created_at.desc()).all()
    cols = {s: [] for s in LEAD_STATUSES}
    for lead in rows:
        cols.setdefault(lead.status, []).append(lead)
    totals = {s: sum(l.deal_value or 0 for l in leads_) for s, leads_ in cols.items()}
    return render_template("crm_board.html", cols=cols, totals=totals,
                           next_steps=_next_steps(rows), now=utcnow_naive(),
                           **crm_scope_ctx())


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
    lead_calls = []
    try:
        from dialer.models import Call
        lead_calls = (Call.query.filter_by(lead_id=lead.id)
                      .order_by(Call.started_at.desc()).limit(20).all())
    except Exception:
        pass
    return render_template("lead_detail.html", lead=lead, open_tasks=open_tasks,
                           done_tasks=done_tasks, now=utcnow_naive(),
                           lead_calls=lead_calls)


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


# ------------------------------------------------------- csv import/export
@app.route("/admin/crm/export.csv")
@login_required
def crm_export():
    """Export the CRM as CSV — honors the same q/status/scope as the list."""
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    query = scoped_leads(Lead.query)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like),
                                    Lead.email.ilike(like), Lead.business.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(Lead.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Business", "Business type", "Phone", "Email",
                "Source", "Status", "Deal value ($/mo)", "Date added",
                "Open tasks", "Notes"])
    nxt = _next_steps(rows)
    for l in rows:
        notes = " | ".join(n.body for n in l.notes
                           if not n.body.startswith("Status changed:"))
        w.writerow([csv_safe(l.name), csv_safe(l.business),
                    csv_safe(l.business_type), csv_safe(l.phone),
                    csv_safe(l.email), csv_safe(l.source), l.status,
                    "" if l.deal_value is None else l.deal_value,
                    to_local(l.created_at).strftime("%Y-%m-%d %H:%M"),
                    csv_safe(nxt[l.id].title if l.id in nxt else ""),
                    csv_safe(notes[:1000])])
    stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="60ms-crm-{stamp}.csv"'})


@app.route("/admin/crm/import", methods=["GET", "POST"])
@login_required
def crm_import():
    if request.method == "GET":
        users = User.query.order_by(User.name).all() if session.get("admin") else []
        return render_template("crm_import.html", users=users)

    file = request.files.get("csv")
    try:
        text_data = file.read().decode("utf-8-sig", errors="replace") if file else ""
    except Exception:
        text_data = ""
    try:
        mapping = json.loads(request.form.get("mapping", "[]"))
    except ValueError:
        mapping = []
    valid = {k for k, _ in CSV_FIELDS}

    def _norm_target(m):
        if isinstance(m, str) and m.startswith("custom:"):
            label = m[7:].strip()[:40]
            return ("custom:" + label) if label else "skip"
        return m if m in valid else "skip"
    mapping = [_norm_target(m) for m in mapping] if isinstance(mapping, list) else []
    if not text_data.strip() or not mapping:
        flash("Upload a CSV and map its columns first.", "error")
        return redirect(url_for("crm_import"))
    if not any(m in ("name", "first_name", "last_name", "phone", "email") for m in mapping):
        flash("Map at least one of Name, Phone, or Email so each lead is identifiable.", "error")
        return redirect(url_for("crm_import"))

    owner_id = my_owner_id()
    if session.get("admin") and request.form.get("owner_id"):
        owner_id = int(request.form["owner_id"])
    dedupe = request.form.get("dedupe", "skip")  # skip | update | none
    default_status = request.form.get("default_status")
    if default_status not in LEAD_STATUSES:
        default_status = "New"
    default_source = (request.form.get("default_source") or "csv-import").strip()[:120]

    if len(text_data) > 10 * 1024 * 1024:
        flash("That file is over 10 MB — export a smaller CSV and try again.", "error")
        return redirect(url_for("crm_import"))
    # normalize \r\n and bare \r (Excel "CSV Macintosh") so csv can't choke
    text_data = text_data.replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    try:
        for r in csv.reader(io.StringIO(text_data)):
            if not any(c.strip() for c in r):
                continue  # blank/comma-only rows — the preview drops these too
            rows.append(r)
            if len(rows) > 5001:  # 5000 data rows + a possible header
                flash("That CSV has over 5,000 rows — split it into smaller files.", "error")
                return redirect(url_for("crm_import"))
    except csv.Error:
        flash("Couldn't parse that file as CSV — re-export it as standard "
              "CSV (UTF-8) and try again.", "error")
        return redirect(url_for("crm_import"))
    if request.form.get("has_header") == "1" and rows:
        rows = rows[1:]
    if len(rows) > 5000:
        flash("That CSV has over 5,000 rows — split it into smaller files.", "error")
        return redirect(url_for("crm_import"))

    # duplicate index (email / phone) within the SAME owner's leads only
    by_email, by_phone = {}, {}
    if dedupe != "none":
        scope = (Lead.query.filter(Lead.owner_id == owner_id) if owner_id
                 else Lead.query.filter(Lead.owner_id.is_(None)))
        for l in scope.all():
            if l.email:
                by_email.setdefault(l.email.strip().lower(), l)
            p = phone_key(l.phone)
            if p:
                by_phone.setdefault(p, l)

    added = updated = skipped = unusable = 0
    for row in rows:
        vals, note_parts, extras, name_parts = {}, [], [], {}
        for i, target in enumerate(mapping):
            v = row[i].strip() if i < len(row) else ""
            if not v or target == "skip":
                continue
            if target == "note":
                note_parts.append(v)
            elif target in ("first_name", "last_name"):
                name_parts[target] = v
            elif target in CSV_EXTRA_FIELDS:
                extras.append((CSV_EXTRA_FIELDS[target], v))
            elif target.startswith("custom:"):
                extras.append((target[7:], v))
            else:
                vals[target] = v
        if not vals.get("name") and name_parts:
            vals["name"] = " ".join(p for p in (name_parts.get("first_name"),
                                                name_parts.get("last_name")) if p)
        if extras:
            note_parts.insert(0, "Imported details: " + " · ".join(
                f"{k}: {v}" for k, v in extras))
        email = vals.get("email", "").strip().lower()
        phone = phone_key(vals.get("phone", ""))
        if not (vals.get("name") or email or phone):
            unusable += 1
            continue
        existing = ((by_email.get(email) if email else None)
                    or (by_phone.get(phone) if phone else None))
        if existing is not None and dedupe == "skip":
            skipped += 1
            continue
        if existing is not None and dedupe == "update":
            for f in LEAD_FIELDS + ["source"]:  # fill blanks, never overwrite
                if vals.get(f) and not getattr(existing, f):
                    # phone column is VARCHAR(40); the rest are 120
                    setattr(existing, f, vals[f][:40 if f == "phone" else 120])
            if existing.deal_value is None and vals.get("deal_value"):
                existing.deal_value = parse_money(vals["deal_value"])
            for np in note_parts:
                db.session.add(Note(lead_id=existing.id, body=np[:2000]))
            updated += 1
            continue
        status = next((s for s in LEAD_STATUSES
                       if s.lower() == vals.get("status", "").strip().lower()),
                      default_status)
        lead = Lead(owner_id=owner_id,
                    name=(vals.get("name") or vals.get("business")
                          or email or vals.get("phone", "Unknown"))[:120],
                    phone=vals.get("phone", "")[:40],
                    email=vals.get("email", "")[:120],
                    business=vals.get("business", "")[:120],
                    business_type=vals.get("business_type", "")[:120],
                    source=(vals.get("source") or default_source)[:120],
                    status=status,
                    deal_value=parse_money(vals.get("deal_value")),
                    created_at=parse_flex_date(vals.get("created_at")) or utcnow_naive())
        db.session.add(lead)
        db.session.flush()
        for np in note_parts:
            db.session.add(Note(lead_id=lead.id, body=np[:2000]))
        if email:
            by_email.setdefault(email, lead)  # dupes inside the same file collapse too
        if phone:
            by_phone.setdefault(phone, lead)  # phone is already the canonical key
        added += 1
    db.session.commit()
    bits = [f"{added} added"]
    if updated:
        bits.append(f"{updated} updated (blanks filled)")
    if skipped:
        bits.append(f"{skipped} skipped as duplicates")
    if unusable:
        bits.append(f"{unusable} rows had no name/phone/email — ignored")
    flash("CSV import done: " + " · ".join(bits), "sticky")
    return redirect(url_for("crm"))


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
                           owners=owners, host=hq_origin())


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


@app.route("/admin/forms/<int:form_id>/notify", methods=["POST"])
@login_required
def form_notify(form_id):
    form = Form.query.get_or_404(form_id)
    if not can_touch(form):
        abort(403)
    raw = request.form.get("notify_emails", "")
    emails = [e.strip() for e in raw.replace(";", ",").split(",") if e.strip()][:10]
    form.notify_emails = ", ".join(emails)[:500]
    db.session.commit()
    flash(("Lead emails for \u201c%s\u201d now go to: %s" % (form.name, form.notify_emails))
          if emails else "Recipients cleared — lead emails fall back to the owner's login email.")
    return redirect(url_for("forms"))


# ------------------------------------------------------------- client email
@app.route("/admin/email", methods=["GET", "POST"])
@login_required
def email_accounts():
    if request.method == "POST":
        if not session.get("admin"):
            abort(403)
        address = request.form.get("address", "").strip()[:200]
        password = request.form.get("password", "").strip()[:200]
        if not address or not password:
            flash("Address and password are both required.", "error")
            return redirect(url_for("email_accounts"))
        acct = EmailAccount(address=address, password=password,
                            notes=request.form.get("notes", "").strip()[:300],
                            owner_id=int(request.form["owner_id"])
                            if request.form.get("owner_id") else None)
        db.session.add(acct)
        db.session.commit()
        flash(f"Mailbox {address} saved — the client can now see it on their Email page.")
        return redirect(url_for("email_accounts"))
    rows = owner_filter(EmailAccount.query, EmailAccount).order_by(
        EmailAccount.created_at.desc()).all()
    users = User.query.order_by(User.name).all() if session.get("admin") else []
    owners = {u.id: u.name for u in users}
    my_forms = owner_filter(Form.query, Form).order_by(Form.name).all()
    return render_template("email.html", rows=rows, users=users, owners=owners,
                           my_forms=my_forms)


@app.route("/admin/email/<int:acct_id>/delete", methods=["POST"])
@login_required
def email_account_delete(acct_id):
    if not session.get("admin"):
        abort(403)
    acct = EmailAccount.query.get_or_404(acct_id)
    db.session.delete(acct)
    db.session.commit()
    flash("Mailbox removed from the dashboard (the actual Purelymail account is untouched).")
    return redirect(url_for("email_accounts"))


# ------------------------------------------------------- multi-page editing
@app.route("/admin/sites/<int:site_id>/pages")
@login_required
def site_pages(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    pages = github_list_pages(site.github_repo) if site.github_repo else None
    return render_template("site_pages.html", site=site, pages=pages,
                           has_token=bool(GITHUB_TOKEN))


@app.route("/edit-page/<int:site_id>")
@login_required
def page_editor(site_id):
    """WordPress-style shell: pages down the left, live editor on the right."""
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    pages = github_list_pages(site.github_repo) if site.github_repo else None
    path = request.args.get("path", "")
    if not PAGE_RE.match(path):
        path = "index.html" if (pages and "index.html" in pages) else (pages[0] if pages else "")
    return render_template("site_editor_shell.html", site=site, pages=pages or [],
                           path=path, has_token=bool(GITHUB_TOKEN))


@app.route("/edit-page/<int:site_id>/frame")
@login_required
def page_editor_frame(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    path = request.args.get("path", "")
    if not (site.github_repo and PAGE_RE.match(path)):
        abort(404)
    html = github_fetch_file(site.github_repo, path)
    if html is None:
        return Response(f"<body style='font-family:sans-serif;padding:40px'>"
                        f"Couldn't load <b>{path}</b> from GitHub — check the repo "
                        f"link and the GITHUB_TOKEN (Setup page).</body>",
                        mimetype="text/html")
    my_forms = owner_filter(Form.query, Form).all()
    view_url = (site.live_url.rstrip("/") + "/" + path) if site.live_url else ""
    # relative css/js/img resolve against the LIVE site, so the page looks real
    if site.live_url:
        base = f'<base href="{site.live_url.rstrip("/")}/" data-wys="1">'
        html = (html.replace("<head>", "<head>" + base, 1) if "<head>" in html
                else base + html)
    boot = ("<script data-wys=\"1\">window.WYS = " + json.dumps({
        "siteId": site.id, "slug": site.slug, "ai": bool(OPENAI_API_KEY),
        "pagePath": path, "viewUrl": view_url,
        "hqOrigin": hq_origin(),
        "forms": [{"name": f.name, "slug": f.slug} for f in my_forms],
    }) + ";</script>")
    inject = boot + editor_snippet()
    if "</body>" in html:
        html = html.replace("</body>", inject + "</body>", 1)
    else:
        html += inject
    return Response(html, mimetype="text/html")


@app.route("/edit-page/<int:site_id>/save", methods=["POST"])
@login_required
def page_editor_save(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    payload = request.get_json(silent=True) or {}
    path, html = payload.get("path", ""), payload.get("html", "")
    if not (site.github_repo and PAGE_RE.match(path) and html):
        return jsonify(ok=False, error="bad request"), 400
    ok, msg = github_push_file(site.github_repo, path, strip_editor_artifacts(html))
    site.last_push_at = utcnow_naive()
    site.last_push_ok = ok
    site.last_push_msg = f"{path}: {msg}"[:300]
    db.session.commit()
    return jsonify(ok=True, msg=msg, github="synced" if ok else "failed")


@app.route("/form/<slug>", methods=["GET", "POST", "OPTIONS"])
def form_submit(slug):
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    form = Form.query.filter_by(slug=slug).first_or_404()
    if request.method == "GET":  # hosted, shareable page — embeds keep working as-is
        return render_template("public_form.html", form=form)
    data = request.get_json(silent=True) or request.form.to_dict()
    if data.get("_gotcha"):  # honeypot
        return _cors(jsonify(ok=True))
    # accept Meta lead-ads / Zapier native field names without any mapping setup
    ALIASES = {"full_name": "name", "phone_number": "phone", "company_name": "business",
               "business_name": "business", "job_title": "business_type",
               "work_email": "email", "ad_name": "source"}
    for src, dst in ALIASES.items():
        if data.get(src) and not data.get(dst):
            data[dst] = data[src]
    if not data.get("name"):  # Meta sometimes splits the name
        parts = [data.get("first_name", ""), data.get("last_name", "")]
        joined = " ".join(p for p in parts if p).strip()
        if joined:
            data["name"] = joined
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
    dest = (data.get("_next") or form.redirect_url or "").strip()
    if dest and not dest.startswith(("http://", "https://", "/")):
        dest = "https://" + dest  # "60minutesites.com/thanks.html" style values
    return redirect(dest or url_for("form_thanks", slug=slug))


# -------------------------------------------- Meta Instant Form (lead ads) webhook
FB_FIELD_MAP = {
    "full_name": "name", "first_name": "first_name", "last_name": "last_name",
    "phone_number": "phone", "email": "email",
    "company_name": "business", "job_title": "business_type",
}


def _fb_lead_to_crm(leadgen_id, form_id=None, ad_id=None):
    """Fetch one lead from the Graph API and file it in the CRM."""
    if not FB_PAGE_TOKEN:
        return None
    try:
        r = http.get(f"https://graph.facebook.com/v21.0/{leadgen_id}",
                     params={"access_token": FB_PAGE_TOKEN,
                             "fields": "field_data,created_time,ad_id,form_id,campaign_name,ad_name"},
                     timeout=20)
        if r.status_code != 200:
            app.logger.warning("FB lead fetch failed %s: %s", r.status_code, r.text[:200])
            return None
        data = r.json()
    except Exception as e:
        app.logger.warning("FB lead fetch error: %s", e)
        return None

    vals, extras, first, last = {}, {}, "", ""
    for f in data.get("field_data", []):
        key = (f.get("name") or "").lower()
        val = (f.get("values") or [""])[0]
        if not val:
            continue
        target = FB_FIELD_MAP.get(key)
        if target == "first_name":
            first = val
        elif target == "last_name":
            last = val
        elif target:
            vals[target] = val[:200]
        else:  # custom qualifying questions
            extras[key.replace("_", " ").strip().capitalize()] = val
    if not vals.get("name"):
        vals["name"] = (first + " " + last).strip()

    # everything lands in one "Facebook Instant Form" bucket so notify/email works
    crm_form = Form.query.filter_by(slug="facebook-instant-form").first()
    if not crm_form:
        crm_form = Form(owner_id=None, name="Facebook Instant Form",
                        slug="facebook-instant-form")
        db.session.add(crm_form)
        db.session.flush()

    src = data.get("ad_name") or data.get("campaign_name") or "Facebook Instant Form"
    lead = Lead(owner_id=crm_form.owner_id, form_id=crm_form.id,
                source=str(src)[:120], status="New",
                name=vals.get("name") or "Unknown", phone=vals.get("phone", "")[:40],
                email=vals.get("email", ""), business=vals.get("business", ""),
                business_type=vals.get("business_type", ""))
    db.session.add(lead)
    db.session.flush()
    extras.update({"Source": "Meta Instant Form", "Leadgen id": str(leadgen_id)})
    if data.get("campaign_name"):
        extras["Campaign"] = data["campaign_name"]
    if data.get("ad_name"):
        extras["Ad"] = data["ad_name"]
    db.session.add(Note(lead_id=lead.id, body="Form extras: " +
                        json.dumps(extras, ensure_ascii=False)[:2000]))
    db.session.commit()
    notify_lead(crm_form, lead)
    return lead


@app.route("/webhooks/meta-leads", methods=["GET", "POST"])
def meta_leads_webhook():
    if request.method == "GET":  # subscription handshake
        if (request.args.get("hub.mode") == "subscribe"
                and FB_VERIFY_TOKEN
                and request.args.get("hub.verify_token") == FB_VERIFY_TOKEN):
            return Response(request.args.get("hub.challenge", ""), mimetype="text/plain")
        return Response("verification failed", status=403)

    raw = request.get_data()
    if FB_APP_SECRET:  # authenticity check — Meta signs every delivery
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(FB_APP_SECRET.encode(), raw,
                                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return Response("bad signature", status=403)

    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            if ch.get("field") != "leadgen":
                continue
            v = ch.get("value", {})
            if v.get("leadgen_id"):
                try:
                    _fb_lead_to_crm(v["leadgen_id"], v.get("form_id"), v.get("ad_id"))
                except Exception as e:  # never let Meta retry-storm us
                    db.session.rollback()
                    app.logger.warning("FB lead handling failed: %s", e)
    return jsonify(ok=True)  # always 200 so Meta doesn't disable the subscription


# ---------------------------------------------------------- e-sign agreements
SIGN_MARKER = "SIGNED-AGREEMENT-JSON: "


def _sign_token(lead_id):
    import hmac as _hmac, hashlib as _hashlib
    return _hmac.new(app.secret_key.encode(), f"sign-{lead_id}".encode(),
                     _hashlib.sha256).hexdigest()[:20]


def _latest_signature(lead_id):
    for n in (Note.query.filter_by(lead_id=lead_id)
              .order_by(Note.created_at.desc()).all()):
        if n.body.startswith(SIGN_MARKER):
            try:
                d = json.loads(n.body[len(SIGN_MARKER):])
                d["when"] = (n.created_at.strftime("%B %-d, %Y at %-I:%M %p UTC")
                             if n.created_at else "")
                return d
            except ValueError:
                continue
    return None


@app.route("/sign/<int:lead_id>/<token>", methods=["GET", "POST"])
def sign_agreement(lead_id, token):
    if token != _sign_token(lead_id):
        abort(404)
    lead = Lead.query.get_or_404(lead_id)
    if request.method == "GET":
        return render_template("sign.html", lead=lead)
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:120]
    sig = str(data.get("signature", ""))
    if not name or not sig.startswith("data:image/png;base64,") or len(sig) > 300_000:
        return jsonify(ok=False), 400
    db.session.add(Note(lead_id=lead.id, body=SIGN_MARKER + json.dumps(
        {"name": name, "signature": sig,
         "ua": request.headers.get("User-Agent", "")[:200]})))
    db.session.commit()
    return jsonify(ok=True)


@app.route("/admin/crm/<int:lead_id>/agreement")
@login_required
def lead_agreement(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if not can_touch(lead):
        abort(403)
    sig = _latest_signature(lead_id)
    sign_url = hq_origin() + f"/sign/{lead_id}/{_sign_token(lead_id)}"
    return render_template("agreement_admin.html", lead=lead, signed=bool(sig),
                           sig=sig, sign_url=sign_url)


@app.route("/admin/ai-studio")
@login_required
def ai_studio():
    sites = owner_filter(Site.query, Site).order_by(Site.business_name).all()
    return render_template("ai_studio.html", sites=sites, has_ai=bool(OPENAI_API_KEY))


@app.route("/admin/invoices")
@login_required
def invoices():
    return render_template("invoices.html")


@app.route("/debug/echo", methods=["GET", "POST", "PUT"])
def debug_echo():
    """Point any integration here to see EXACTLY what it sends. Read-only,
    stores nothing. Invaluable when a webhook 'works' but arrives empty."""
    body = request.get_data(as_text=True)[:4000]
    return _cors(jsonify(
        ok=True,
        method=request.method,
        content_type=request.headers.get("Content-Type", ""),
        parsed_json=request.get_json(silent=True),
        parsed_form=request.form.to_dict(),
        query=request.args.to_dict(),
        raw_body=body,
        field_names=sorted(list((request.get_json(silent=True) or {}).keys())
                           or list(request.form.keys())),
    ))


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
            want_team = bool(request.form.get("feature_multi_user"))
            want_dialer = bool(request.form.get("feature_dialer"))
            want_enrich = bool(request.form.get("feature_enrichment"))
            seats = request.form.get("seat_limit", type=int) or 5
            db.session.add(User(name=name, email=email, phone=phone,
                                monthly_price=parse_money(request.form.get("monthly_price")),
                                setup_fee=parse_money(request.form.get("setup_fee")),
                                password_hash=generate_password_hash(password),
                                role="owner", active=True,
                                feature_multi_user=want_team,
                                feature_dialer=want_dialer,
                                feature_enrichment=want_enrich,
                                seat_limit=(max(1, min(seats, 200)) if want_team else 1)))
            db.session.commit()
            flash(f"Customer “{name}” created — password: {password}", "sticky")
        return redirect(url_for("customers"))
    rows = User.query.filter(User.account_id.is_(None)) \
        .order_by(User.created_at.desc()).all()
    stats = {u.id: {"sites": Site.query.filter_by(owner_id=u.id).count(),
                    "leads": Lead.query.filter_by(owner_id=u.id).count()}
             for u in rows}
    mrr = sum(u.monthly_price or 0 for u in rows)
    return render_template("customers.html", rows=rows, stats=stats, mrr=mrr,
                           TOOLS=TOOLS, TOOL_BLURBS=TOOL_BLURBS,
                           TOOLS_ALWAYS_ON=TOOLS_ALWAYS_ON)


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
    elif action == "tools":
        # Which tools this client sees. Storing what to HIDE means an account
        # nobody has configured keeps seeing everything, which is how they all
        # behaved before this existed.
        keep = set(request.form.getlist("tool"))
        hide = [k for k, _, _, _, _, _ in TOOLS
                if k not in keep and k not in TOOLS_ALWAYS_ON]
        user.hidden_tools = ",".join(hide)
        shown = len(TOOLS) - len(hide)
        flash(f"{user.name} now sees {shown} of {len(TOOLS)} tools."
              + (f" Hidden: {', '.join(TOOL_LABELS[h] for h in hide)}."
                 if hide else " Nothing is hidden."))
        try:
            from teams.models import log as _audit
            _audit("account.tools", target=user.email,
                   detail="hidden=" + (",".join(hide) or "none"),
                   account_id=user.id)
        except Exception:
            pass
    elif action == "features":
        user.feature_multi_user = bool(request.form.get("feature_multi_user"))
        user.feature_dialer = bool(request.form.get("feature_dialer"))
        user.feature_enrichment = bool(request.form.get("feature_enrichment"))
        seats = request.form.get("seat_limit", type=int)
        if seats:
            user.seat_limit = max(1, min(seats, 200))
        elif not user.feature_multi_user:
            user.seat_limit = 1
        bits = []
        if user.feature_multi_user:
            bits.append(f"multi-user ({user.seat_limit} seats)")
        if user.feature_dialer:
            bits.append("AI calling")
        if user.feature_enrichment:
            bits.append("enrichment")
        flash(f"{user.name}: " + (", ".join(bits) + " switched on."
                                  if bits else "both add-ons switched off."))
        try:
            from teams.models import log as _audit
            _audit("account.features", target=user.email,
                   detail=", ".join(bits) or "none", account_id=user.id)
        except Exception:
            pass
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
    # relative css/js/img resolve against the LIVE site so the page looks real
    if site.live_url and "<base" not in html[:2000]:
        base = f'<base href="{site.live_url.rstrip("/")}/" data-wys="1">'
        html = (html.replace("<head>", "<head>" + base, 1) if "<head>" in html
                else base + html)
    my_forms = owner_filter(Form.query, Form).all()
    boot = ("<script data-wys=\"1\">window.WYS = " + json.dumps({
        "siteId": site.id, "slug": site.slug, "ai": bool(OPENAI_API_KEY),
        "hqOrigin": hq_origin(),
        "forms": [{"name": f.name, "slug": f.slug} for f in my_forms],
    }) + ";</script>")
    inject = boot + editor_snippet()
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


@app.route("/admin/sites/<int:site_id>/liveurl", methods=["POST"])
@admin_required
def site_liveurl(site_id):
    """Record where a site actually lives (the client's Netlify domain) so ad
    links and View buttons use the real URL instead of the HQ-hosted /s/ copy."""
    site = Site.query.get_or_404(site_id)
    url = request.form.get("live_url", "").strip().rstrip("/")
    if url and not re.fullmatch(r"https?://[\w.-]+(:\d+)?(/[\w./-]*)?", url):
        flash("That doesn't look like a URL — e.g. https://toddtrope.com", "error")
        return redirect(url_for("sites"))
    site.live_url = url
    db.session.commit()
    flash(f"“{site.business_name}” live domain " +
          (f"set to {url} — ad links and View now use it." if url else "cleared."))
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
                           host=hq_origin())


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
    base = hq_origin()
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


# ------------------------------------------------------- backup & restore
BACKUP_TABLES = [  # (key, model, columns) — FK-safe insert order
    ("users", User, ["id", "name", "email", "phone", "password_hash",
                     "monthly_price", "setup_fee", "created_at"]),
    ("forms", Form, ["id", "owner_id", "name", "slug", "redirect_url", "created_at"]),
    ("sites", Site, ["id", "owner_id", "slug", "business_name", "template",
                     "github_repo", "html", "tagline", "phone", "email",
                     "services", "about", "color", "style", "created_at"]),
    ("leads", Lead, ["id", "owner_id", "form_id", "name", "phone", "email",
                     "business", "business_type", "source", "status",
                     "deal_value", "created_at"]),
    ("notes", Note, ["id", "lead_id", "body", "created_at"]),
    ("tasks", Task, ["id", "owner_id", "lead_id", "title", "kind", "due_at",
                     "done", "done_at", "created_at"]),
]


@app.route("/admin/export.json")
@admin_required
def export_json():
    """One-click full CRM backup (everything except uploaded media/flipbooks)."""
    def dump(model, cols):
        out = []
        for r in model.query.all():
            d = {}
            for c in cols:
                v = getattr(r, c)
                d[c] = v.isoformat() if isinstance(v, datetime) else v
            out.append(d)
        return out
    data = {"format": "60ms-backup-v1",
            "exported_at": datetime.now(timezone.utc).isoformat()}
    for key, model, cols in BACKUP_TABLES:
        data[key] = dump(model, cols)
    stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d-%H%M")
    return Response(json.dumps(data, ensure_ascii=False),
                    mimetype="application/json",
                    headers={"Content-Disposition":
                             f'attachment; filename="60ms-backup-{stamp}.json"'})


@app.route("/admin/import", methods=["POST"])
@admin_required
def import_json():
    """Restore a backup: inserts rows whose id doesn't exist yet (never overwrites)."""
    file = request.files.get("backup")
    try:
        data = json.loads(file.read().decode("utf-8")) if file else None
    except Exception:
        data = None
    if not data or data.get("format") != "60ms-backup-v1":
        flash("That doesn't look like a 60MS backup file (.json from Export).", "error")
        return redirect(url_for("setup_page"))
    dt_fields = {"created_at", "due_at", "done_at"}
    restored = []
    for key, model, cols in BACKUP_TABLES:
        n = 0
        for row in data.get(key, []):
            rid = row.get("id")
            if rid is None or db.session.get(model, rid) is not None:
                continue
            kwargs = {}
            for c in cols:
                v = row.get(c)
                if c in dt_fields and v:
                    try:
                        v = datetime.fromisoformat(v)
                    except ValueError:
                        v = None
                kwargs[c] = v
            db.session.add(model(**kwargs))
            n += 1
        if n:
            restored.append(f"{n} {key}")
    db.session.commit()
    if db.engine.dialect.name == "postgresql":
        # explicit-id inserts don't advance sequences; fix so new rows don't collide
        with db.engine.begin() as conn:
            for key, model, _ in BACKUP_TABLES:
                t = model.__tablename__
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{t}\"', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{t}\"), 1))"))
    flash("Restored: " + (", ".join(restored) if restored else
                          "nothing new (every row in the file already exists)"), "sticky")
    return redirect(url_for("setup_page"))


# --------------------------------------------------- demo account (sales prop)
DEMO_EMAIL = "johnmelody@gmail.com"
_D_FIRST = ["Mike", "Sarah", "Carlos", "Dana", "Priya", "Tom", "Angela", "Ray",
            "Nicole", "Marcus", "Beth", "Hector", "Wendy", "Sam", "Olivia",
            "Derek", "Tina", "Paul", "Grace", "Victor", "Lena", "Chris",
            "Maria", "Doug", "Renee", "Omar", "Kate", "Bill", "Jasmine", "Ted"]
_D_LAST = ["Rivera", "Chen", "Okafor", "Miller", "Patel", "Novak", "Brooks",
           "Silva", "Hansen", "Wright", "Kim", "Delgado", "Foster", "Nguyen",
           "Barone", "Ellis", "Romero", "Fitzgerald", "Yoder", "Grant",
           "Whitaker", "Sosa", "Lindstrom", "Beck", "Adeyemi", "Cole"]
_D_TRADES = [("Plumbing", "Plumber"), ("Roofing", "Roofer"), ("Electric", "Electrician"),
             ("Landscaping", "Landscaper"), ("HVAC", "HVAC"), ("Painting", "Painter"),
             ("Flooring", "Flooring"), ("Cleaning", "Cleaning service"),
             ("Concrete", "Concrete"), ("Fencing", "Fencing"), ("Salon", "Salon"),
             ("Bakery", "Bakery"), ("Auto Repair", "Mechanic"), ("Photography", "Photographer")]
_D_SUFFIX = ["LLC", "Co.", "& Sons", "Services", "Pros", "Bros", "Solutions", ""]
_D_SOURCES = ["website-form", "google", "facebook-ad", "referral", "yelp",
              "walk-in", "quote-form", "nextdoor"]
_D_NOTES = ["Called — {n} wants an estimate next week, sounded ready to move.",
            "Left a voicemail, will try again Thursday.",
            "Texted photos of the job. Bigger than expected — quote higher.",
            "Met at the property. Nice folks, dog is loud. Quote sent same day.",
            "Asked for references — sent the Hendersons and the bakery job.",
            "Price-shopping against two other bids. Follow up Friday.",
            "Wife handles scheduling — call after 5pm only.",
            "Repeat customer — did their gutters last spring.",
            "Wants it done before the holidays. Tight but doable.",
            "Sent the contract. Waiting on signature.",
            "Deposit received. Scheduling materials delivery.",
            "Referred by {r} — give them the referral discount."]
_D_TASKS_OPEN = [("Call", "Call {n} back about the estimate"),
                 ("Text", "Text {n} the updated quote"),
                 ("Email", "Email {n} the contract"),
                 ("Meeting", "Walk-through at {n}'s place"),
                 ("Follow-up", "Follow up with {n} — bid was pending"),
                 ("To-do", "Order materials for {n}'s job")]
_D_TASKS_DONE = [("Call", "Called {n} — quote accepted"),
                 ("Email", "Sent invoice to {n}"),
                 ("To-do", "Finished {n}'s job — ask for a review"),
                 ("Follow-up", "Checked in with {n} after the install")]


def _demo_site_html(quote_slug):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Melody Home Services — Repairs done right, the first time</title>
<style>
  :root {{ --blue: #1D4ED8; --ink: #10203A; --bg: #F5F7FB; }}
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ font-family: 'Segoe UI', -apple-system, sans-serif; color: var(--ink); background: #fff; line-height: 1.6; }}
  header {{ background: linear-gradient(135deg, #1D4ED8, #1E3A8A); color: #fff; padding: 72px 24px 84px; text-align: center; }}
  header h1 {{ font-size: 42px; letter-spacing: -0.02em; }}
  header p {{ font-size: 19px; opacity: .92; max-width: 560px; margin: 14px auto 26px; }}
  .cta {{ display: inline-block; background: #fff; color: var(--blue); font-weight: 800; padding: 15px 34px; border-radius: 10px; text-decoration: none; font-size: 17px; box-shadow: 0 10px 30px rgba(0,0,0,.25); }}
  section {{ padding: 64px 24px; max-width: 1000px; margin: 0 auto; }}
  h2 {{ font-size: 30px; text-align: center; margin-bottom: 34px; letter-spacing: -0.01em; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; }}
  .svc {{ background: var(--bg); border-radius: 14px; padding: 26px; }}
  .svc h3 {{ margin-bottom: 6px; font-size: 18px; }}
  .quotes {{ background: var(--bg); }}
  .q {{ background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 2px 10px rgba(16,32,58,.06); }}
  .q b {{ display: block; margin-top: 12px; color: var(--blue); }}
  form {{ max-width: 460px; margin: 0 auto; display: grid; gap: 12px; }}
  input, textarea {{ padding: 13px; border: 1.5px solid #D7DEEA; border-radius: 9px; font: inherit; }}
  button {{ background: var(--blue); color: #fff; border: 0; padding: 15px; border-radius: 9px; font-size: 16px; font-weight: 800; cursor: pointer; }}
  footer {{ background: var(--ink); color: #B9C4D8; text-align: center; padding: 34px 20px; font-size: 14px; }}
</style></head><body>
<header>
  <h1>Melody Home Services</h1>
  <p>Repairs done right, the first time. Licensed, insured, and on time — serving the whole metro since 2011.</p>
  <a class="cta" href="#quote">Get a free quote</a>
</header>
<section>
  <h2>What we do</h2>
  <div class="grid">
    <div class="svc"><h3>Repairs &amp; odd jobs</h3><p>Doors, drywall, fixtures, the list on your fridge — knocked out in one visit.</p></div>
    <div class="svc"><h3>Kitchens &amp; baths</h3><p>Tile, vanities, backsplashes, and full refreshes that don't drag on for months.</p></div>
    <div class="svc"><h3>Decks &amp; fences</h3><p>Build, repair, stain. Storm damage handled fast with photos for your insurer.</p></div>
    <div class="svc"><h3>Painting</h3><p>Interior and exterior, clean lines, furniture covered, zero mystery smudges.</p></div>
    <div class="svc"><h3>Gutters &amp; exterior</h3><p>Cleaning, guards, small roof fixes before they become big roof problems.</p></div>
    <div class="svc"><h3>Emergency calls</h3><p>Burst pipe? Broken lock? Same-day slots held open every weekday.</p></div>
  </div>
</section>
<section class="quotes">
  <h2>Neighbors talk</h2>
  <div class="grid">
    <div class="q">“John rebuilt our back steps in a day and the price matched the quote to the dollar.”<b>— Denise H., Maple Grove</b></div>
    <div class="q">“Three other guys no-showed. Melody Home Services showed up early. Twice.”<b>— Curtis W., Riverside</b></div>
    <div class="q">“Booked online at 9pm, fixed by Friday. The photo updates were a nice touch.”<b>— Alma R., Fairview</b></div>
  </div>
</section>
<section id="quote">
  <h2>Get your free quote</h2>
  <form action="/form/{quote_slug}" method="POST">
    <input type="text" name="_gotcha" style="display:none" tabindex="-1">
    <input type="text" name="name" placeholder="Your name" required>
    <input type="tel" name="phone" placeholder="Cell number" required>
    <input type="text" name="business" placeholder="Address or neighborhood">
    <textarea name="message" placeholder="What needs fixing?"></textarea>
    <button type="submit">Send — we reply within the hour</button>
  </form>
</section>
<footer>Melody Home Services · (555) 014-2266 · Licensed &amp; insured · Mon–Sat 7am–6pm</footer>
</body></html>"""


def _wipe_demo_data(user):
    """Delete everything the demo account owns (leads+notes+tasks, forms,
    sites+revisions). Touches ONLY rows with the demo user's owner_id."""
    lead_ids = [l.id for l in Lead.query.filter_by(owner_id=user.id)]
    if lead_ids:
        Note.query.filter(Note.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        Task.query.filter(Task.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        Lead.query.filter(Lead.id.in_(lead_ids)).delete(synchronize_session=False)
    Task.query.filter_by(owner_id=user.id).delete(synchronize_session=False)
    site_ids = [s.id for s in Site.query.filter_by(owner_id=user.id)]
    if site_ids:
        SiteRevision.query.filter(SiteRevision.site_id.in_(site_ids)).delete(synchronize_session=False)
        Site.query.filter(Site.id.in_(site_ids)).delete(synchronize_session=False)
    Form.query.filter_by(owner_id=user.id).delete(synchronize_session=False)


@app.route("/admin/setup/demo-delete", methods=["POST"])
@admin_required
def demo_delete():
    """Remove the demo account and every row it owns."""
    user = User.query.filter_by(email=DEMO_EMAIL).first()
    if not user:
        flash("No demo account exists — nothing to remove.")
        return redirect(url_for("setup_page"))
    _wipe_demo_data(user)
    db.session.delete(user)
    db.session.commit()
    flash("Demo account and all its data removed. Rebuild it any time.", "sticky")
    return redirect(url_for("setup_page"))


@app.route("/admin/setup/demo", methods=["POST"])
@admin_required
def demo_seed():
    """(Re)build the John Melody showcase account — a thriving business to
    demo to prospects. Password comes from DEMO_PASSWORD, never hardcoded."""
    pw = os.environ.get("DEMO_PASSWORD", "")
    if not pw:
        flash("Set a DEMO_PASSWORD variable on the server first (Railway → web "
              "→ Variables), then hit this button again.", "error")
        return redirect(url_for("setup_page"))
    user = User.query.filter_by(email=DEMO_EMAIL).first()
    if user:  # clean rebuild: wipe the demo account's data, keep the login
        _wipe_demo_data(user)
        user.password_hash = generate_password_hash(pw)
    else:
        user = User(name="John Melody", email=DEMO_EMAIL, phone="(555) 014-2266",
                    monthly_price=0, setup_fee=0,  # never pollutes YOUR revenue
                    password_hash=generate_password_hash(pw))
        db.session.add(user)
        db.session.flush()

    contact = Form(owner_id=user.id, name="Website contact", slug=slugify("melody contact"))
    quote = Form(owner_id=user.id, name="Free quote request", slug=slugify("melody quote"))
    db.session.add_all([contact, quote])
    db.session.flush()
    site = Site(owner_id=user.id, slug=slugify("melody home services"),
                business_name="Melody Home Services", template="demo",
                html=_demo_site_html(quote.slug))
    db.session.add(site)

    now = utcnow_naive()
    leads, notes, tasks = [], [], []
    for _ in range(750):
        first, last = random.choice(_D_FIRST), random.choice(_D_LAST)
        trade, ttype = random.choice(_D_TRADES)
        biz = f"{last} {trade} {random.choice(_D_SUFFIX)}".strip()
        days = int(random.triangular(0, 540, 25))
        created = now - timedelta(days=days, hours=random.randint(0, 23),
                                  minutes=random.randint(0, 59))
        if days < 7:
            status = random.choices(["New", "Contacted", "Booked", "Dead"],
                                    [45, 35, 15, 5])[0]
        elif days < 45:
            status = random.choices(LEAD_STATUSES, [5, 25, 20, 15, 20, 15])[0]
        else:
            status = random.choices(LEAD_STATUSES, [0, 4, 5, 6, 45, 40])[0]
        form = random.choice([contact, quote, None, None])
        lead = Lead(owner_id=user.id, form_id=form.id if form else None,
                    name=f"{first} {last}", business=biz, business_type=ttype,
                    phone=f"(555) {random.randint(100, 999)}-{random.randint(1000, 9999)}",
                    email=(f"{first}.{last}@{random.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'aol.com'])}".lower()
                           if random.random() < 0.8 else ""),
                    source=form.name.lower().replace(' ', '-') if form else random.choice(_D_SOURCES),
                    status=status,
                    deal_value=random.choice([79, 99, 99, 129, 149, 179, 199, 249])
                    if random.random() < 0.7 else None,
                    created_at=created)
        leads.append(lead)
    db.session.add_all(leads)
    db.session.flush()
    for lead in leads:
        if random.random() < 0.4:
            for _ in range(random.randint(1, 2)):
                body = random.choice(_D_NOTES).format(
                    n=lead.name.split()[0],
                    r=f"{random.choice(_D_FIRST)} {random.choice(_D_LAST)}")
                notes.append(Note(lead_id=lead.id, body=body,
                                  created_at=lead.created_at + timedelta(
                                      hours=random.randint(1, 96))))
    recent = [l for l in leads if l.status in ("New", "Contacted", "Booked", "Built")][:22]
    for i, lead in enumerate(recent):
        kind, tpl = random.choice(_D_TASKS_OPEN)
        due = now + timedelta(hours=random.choice([-30, -4, 2, 5, 26, 30, 70, 120, 200]))
        tasks.append(Task(owner_id=user.id, lead_id=lead.id, kind=kind,
                          title=tpl.format(n=lead.name.split()[0]), due_at=due))
    for lead in random.sample(leads, 55):
        kind, tpl = random.choice(_D_TASKS_DONE)
        done_at = lead.created_at + timedelta(days=random.randint(1, 20))
        tasks.append(Task(owner_id=user.id, lead_id=lead.id, kind=kind,
                          title=tpl.format(n=lead.name.split()[0]), done=True,
                          done_at=done_at, due_at=done_at))
    tasks.append(Task(owner_id=user.id, kind="To-do", title="Pick up van from the shop",
                      due_at=now + timedelta(hours=8)))
    tasks.append(Task(owner_id=user.id, kind="To-do",
                      title="Post before/after photos to the website"))
    db.session.add_all(notes + tasks)
    db.session.commit()
    flash(f"Demo account rebuilt: {DEMO_EMAIL} — {len(leads)} leads, {len(notes)} "
          f"notes, {len(tasks)} tasks, 2 forms, 1 site. Log in with your "
          "DEMO_PASSWORD to showcase it.", "sticky")
    return redirect(url_for("setup_page"))


@app.route("/admin/setup")
@admin_required
def setup_page():
    status = {
        "resend": bool(RESEND_KEY), "github": bool(GITHUB_TOKEN),
        "openai": bool(OPENAI_API_KEY), "admin_email": ADMIN_EMAIL,
        "host": hq_origin(),
        "sqlite": USING_SQLITE, "railway": IS_RAILWAY,
    }
    linked = Site.query.filter(Site.github_repo.isnot(None),
                               Site.github_repo != "").all()
    unlinked_clients = Site.query.filter(
        Site.owner_id.isnot(None),
        db.or_(Site.github_repo.is_(None), Site.github_repo == "")).count()
    # auto-detected completion per guide: green check = verified done
    done = {
        "postgres": not USING_SQLITE,
        "backups": not USING_SQLITE,
        "github": bool(GITHUB_TOKEN),
        "linksite": bool(GITHUB_TOKEN) and bool(linked) and unlinked_clients == 0,
        "resend": bool(RESEND_KEY) and bool(ADMIN_EMAIL),
        "billing": User.query.filter(User.monthly_price.is_(None)).count() == 0,
        "openai": bool(OPENAI_API_KEY),
        "demo": User.query.filter_by(email=DEMO_EMAIL).first() is not None,
    }
    return render_template("setup.html", s=status, linked_sites=linked,
                           done=done,
                           done_count=sum(done.values()), done_total=len(done))


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
def _toc_from_outline(doc):
    """PDF's own bookmarks -> [{'title', 'page'}] (top 2 levels, capped)."""
    out = []
    try:
        for level, title, page in doc.get_toc(simple=True):
            if level <= 2 and title.strip() and 1 <= page <= doc.page_count:
                out.append({"title": title.strip()[:120], "page": page})
    except Exception:
        pass
    return out[:60]


def _toc_from_ai(title, page_texts):
    """One-time AI pass over extracted page text -> TOC JSON. Best-effort."""
    if not OPENAI_API_KEY:
        return []
    condensed = "\n".join(f"[page {i + 1}] {t[:220]}"
                          for i, t in enumerate(page_texts[:80]) if t.strip())
    if not condensed.strip():
        return []
    try:
        out = _openai([
            {"role": "system", "content":
             "You build tables of contents. Given per-page text snippets from a "
             "publication, return ONLY a JSON array (no markdown fences) of its "
             "main sections: [{\"title\": \"...\", \"page\": N}] with 1-based "
             "pages, 5-25 entries, short human titles in reading order. If the "
             "content has no clear sections, return []."},
            {"role": "user", "content": f"Publication: {title}\n\n{condensed[:12000]}"},
        ], max_tokens=900)
        out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M).strip()
        toc = json.loads(out)
        clean = []
        for e in toc if isinstance(toc, list) else []:
            try:
                p = int(e.get("page"))
                t = str(e.get("title", "")).strip()
            except (AttributeError, TypeError, ValueError):
                continue
            if t and 1 <= p <= len(page_texts):
                clean.append({"title": t[:120], "page": p})
        return clean[:40]
    except Exception:
        return []


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
        page_texts = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            try:
                txt = page.get_text().strip()[:6000]
            except Exception:
                txt = ""
            page_texts.append(txt)
            db.session.add(FlipbookPage(flipbook_id=book.id, page_num=i,
                                        image=pix.tobytes("png"), text=txt,
                                        width=pix.width, height=pix.height))
        toc = _toc_from_outline(doc)
        toc_how = "from the PDF's own bookmarks" if toc else ""
        if not toc and request.form.get("ai_toc") == "1":
            toc = _toc_from_ai(title, page_texts)
            toc_how = "AI-built (one-time)" if toc else ""
        book.toc = json.dumps(toc) if toc else ""
        db.session.commit()
        extra = f" · TOC {toc_how}, {len(toc)} sections" if toc else ""
        searchable = sum(1 for t in page_texts if t)
        extra += f" · {searchable} searchable pages" if searchable else " · no text layer (search off)"
        flash(f"Flipbook “{title}” ready at /f/{book.slug}{extra}")
        return redirect(url_for("flipbooks"))
    rows = Flipbook.query.order_by(Flipbook.created_at.desc()).all()
    meta = {}
    for b in rows:
        try:
            toc_n = len(json.loads(b.toc)) if b.toc else 0
        except ValueError:
            toc_n = 0
        has_text = db.session.query(FlipbookPage.id).filter(
            FlipbookPage.flipbook_id == b.id, FlipbookPage.text.isnot(None),
            FlipbookPage.text != "").first() is not None
        meta[b.id] = {"toc": toc_n, "search": has_text}
    return render_template("flipbooks.html", rows=rows, meta=meta,
                           host=hq_origin(),
                           has_ai=bool(OPENAI_API_KEY))


@app.route("/admin/flipbooks/<int:book_id>/toc", methods=["POST"])
@admin_required
def flipbook_toc(book_id):
    """(Re)build a book's TOC with AI from the stored page text."""
    book = Flipbook.query.get_or_404(book_id)
    texts = [p.text or "" for p in book.pages]
    if not any(texts):
        flash("This book has no extracted text (uploaded before search existed, "
              "or it's a scanned/image PDF) — re-upload the PDF to enable "
              "search + TOC.", "error")
        return redirect(url_for("flipbooks"))
    toc = _toc_from_ai(book.title, texts)
    if not toc:
        flash("AI couldn't find clear sections in this one — TOC unchanged.", "error")
        return redirect(url_for("flipbooks"))
    book.toc = json.dumps(toc)
    db.session.commit()
    flash(f"TOC rebuilt for “{book.title}” — {len(toc)} sections.")
    return redirect(url_for("flipbooks"))


@app.route("/f/<slug>/search")
def flipbook_search(slug):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return _cors(jsonify(ok=True, hits=[]))
    hits = []
    ql = q.lower()
    for p in book.pages:
        t = p.text or ""
        i = t.lower().find(ql)
        if i == -1:
            continue
        start = max(0, i - 55)
        snippet = ("…" if start else "") + t[start:i + len(q) + 65].replace("\n", " ") + "…"
        hits.append({"page": p.page_num + 1, "snippet": snippet.strip()})
        if len(hits) >= 30:
            break
    return _cors(jsonify(ok=True, hits=hits, q=q))


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
    try:
        toc = json.loads(book.toc) if book.toc else []
    except ValueError:
        toc = []
    has_text = any((p.text or "").strip() for p in book.pages)
    return render_template("flipbook_view.html", book=book, first=first,
                           toc=toc, has_text=has_text,
                           embed=request.args.get("embed") == "1",
                           host=hq_origin())


@app.route("/f/<slug>/page/<int:num>.png")
def flipbook_page(slug, num):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    page = FlipbookPage.query.filter_by(flipbook_id=book.id, page_num=num).first()
    if not page:
        abort(404)
    return Response(page.image, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------- chat widget
CHAT_FALLBACK = ("Thanks for reaching out! Leave your name and number below "
                 "and {biz} will get back to you shortly.")


def _chat_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _chat_default_prompt(biz):
    return (f"You are the friendly virtual assistant for {biz}. Answer visitor "
            "questions about the business briefly (2-3 sentences max) and in a "
            "warm, professional tone. Your #1 goal is to get the visitor's name "
            "and phone number so the team can follow up — work it in naturally. "
            "Never invent prices, availability, or guarantees; if you don't know "
            "something, say the team will confirm and ask for their number. "
            "Never mention that you are an AI language model.")


def _chat_ai_available(w):
    """Roll the monthly counter and answer whether an AI reply may be used."""
    if not (w.ai_enabled and OPENAI_API_KEY):
        return False
    m = _chat_month()
    if w.used_month != m:
        w.used_month, w.used_count = m, 0
    return w.used_count < (w.monthly_limit or 0)


def _chat_notify_to(w):
    if w.notify_email:
        return w.notify_email
    owner = db.session.get(User, w.owner_id) if w.owner_id else None
    return owner.email if owner else ADMIN_EMAIL


def notify_chat(w, convo, subject, html):
    """Email update for chat activity via Resend (best-effort, like notify_lead)."""
    to = _chat_notify_to(w)
    if not (RESEND_KEY and to):
        return
    try:
        http.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {RESEND_KEY}"},
                  json={"from": RESEND_FROM, "to": [to], "subject": subject,
                        "html": html + "<p style='font-family:sans-serif;color:#888'>"
                                       "Full transcript in HQ → Chat → Conversations.</p>"},
                  timeout=15)
    except Exception:
        pass


@app.route("/admin/chat", methods=["GET", "POST"])
@login_required
def chat_widgets():
    if request.method == "POST":
        name = request.form.get("business_name", "").strip() or "My business"
        owner_id = my_owner_id()
        if session.get("admin") and request.form.get("owner_id"):
            owner_id = int(request.form["owner_id"])
        slug = base = slugify(name)
        n = 2
        while ChatWidget.query.filter_by(slug=slug).first():
            slug, n = f"{base}-{n}", n + 1
        w = ChatWidget(owner_id=owner_id, slug=slug, business_name=name,
                       system_prompt=_chat_default_prompt(name),
                       greeting=f"Hi! Welcome to {name} — how can we help?")
        db.session.add(w)
        db.session.commit()
        flash(f"Chat widget for “{name}” created — grab the embed code below.")
        return redirect(url_for("chat_widgets"))
    rows = owner_filter(ChatWidget.query, ChatWidget).order_by(
        ChatWidget.created_at.desc()).all()
    month = _chat_month()
    counts = {w.id: ChatConversation.query.filter_by(widget_id=w.id).count()
              for w in rows}
    users = User.query.order_by(User.name).all() if session.get("admin") else []
    owners = {u.id: u.name for u in users}
    return render_template("chat.html", rows=rows, counts=counts, month=month,
                           users=users, owners=owners,
                           host=hq_origin(),
                           has_ai=bool(OPENAI_API_KEY))


@app.route("/admin/chat/<int:wid>/update", methods=["POST"])
@login_required
def chat_update(wid):
    w = ChatWidget.query.get_or_404(wid)
    if not can_touch(w):
        abort(403)
    f = request.form
    w.enabled = bool(f.get("enabled"))
    w.ai_enabled = bool(f.get("ai_enabled"))
    w.business_name = f.get("business_name", w.business_name).strip() or w.business_name
    w.greeting = f.get("greeting", "").strip()
    w.system_prompt = f.get("system_prompt", "").strip() or _chat_default_prompt(w.business_name)
    w.accent = f.get("accent", w.accent).strip() or w.accent
    w.contact_phone = f.get("contact_phone", "").strip()
    w.contact_email = f.get("contact_email", "").strip()
    w.booking_url = f.get("booking_url", "").strip()
    w.notify_email = f.get("notify_email", "").strip()
    try:
        w.monthly_limit = max(0, int(f.get("monthly_limit", w.monthly_limit)))
    except ValueError:
        pass
    db.session.commit()
    flash(f"“{w.business_name}” chat settings saved.")
    return redirect(url_for("chat_widgets"))


@app.route("/admin/chat/<int:wid>/delete", methods=["POST"])
@login_required
def chat_delete(wid):
    w = ChatWidget.query.get_or_404(wid)
    if not can_touch(w):
        abort(403)
    for c in ChatConversation.query.filter_by(widget_id=w.id).all():
        db.session.delete(c)
    db.session.delete(w)
    db.session.commit()
    flash("Chat widget deleted (transcripts removed too).")
    return redirect(url_for("chat_widgets"))


@app.route("/admin/chat/<int:wid>/convos")
@login_required
def chat_convos(wid):
    w = ChatWidget.query.get_or_404(wid)
    if not can_touch(w):
        abort(403)
    convos = (ChatConversation.query.filter_by(widget_id=w.id)
              .order_by(ChatConversation.updated_at.desc()).limit(200).all())
    return render_template("chat_convos.html", w=w, convos=convos)


@app.route("/chat/widget.js")
def chat_widget_js():
    resp = send_from_directory(os.path.join(_here, "static"), "chatwidget.js",
                               mimetype="application/javascript")
    resp.headers["Cache-Control"] = "public, max-age=300"
    return _cors(resp)


@app.route("/chat/<slug>/boot")
def chat_boot(slug):
    w = ChatWidget.query.filter_by(slug=slug).first()
    if not w or not w.enabled:
        return _cors(jsonify(ok=True, enabled=False))
    return _cors(jsonify(
        ok=True, enabled=True, business=w.business_name,
        greeting=w.greeting or f"Hi! Welcome to {w.business_name} — how can we help?",
        accent=w.accent, phone=w.contact_phone, email=w.contact_email,
        booking=w.booking_url, ai=_chat_ai_available(w)))


@app.route("/chat/<slug>/message", methods=["POST", "OPTIONS"])
def chat_message(slug):
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    w = ChatWidget.query.filter_by(slug=slug).first_or_404()
    if not w.enabled:
        return _cors(jsonify(ok=False, error="disabled")), 403
    p = request.get_json(silent=True) or {}
    body = str(p.get("message", "")).strip()[:1000]
    if not body:
        return _cors(jsonify(ok=False, error="empty")), 400
    convo = None
    if p.get("conversation_id"):
        convo = db.session.get(ChatConversation, int(p["conversation_id"]))
        if convo and convo.widget_id != w.id:
            convo = None
    first_message = convo is None
    if convo is None:
        convo = ChatConversation(widget_id=w.id,
                                 page_url=str(p.get("page", ""))[:400])
        db.session.add(convo)
        db.session.flush()
    if ChatMessage.query.filter_by(conversation_id=convo.id).count() >= 80:
        return _cors(jsonify(ok=False, error="conversation full")), 429
    prior = [{"role": m.role, "content": m.body}
             for m in convo.messages[-12:] if m.role in ("user", "assistant")]
    db.session.add(ChatMessage(conversation_id=convo.id, role="user", body=body))
    ai_ok = _chat_ai_available(w)
    if ai_ok:
        history = prior + [{"role": "user", "content": body}]
        try:
            reply = _openai(
                [{"role": "system",
                  "content": (w.system_prompt or _chat_default_prompt(w.business_name))}]
                + history, max_tokens=300)
            w.used_count = (w.used_count or 0) + 1
        except Exception:
            ai_ok, reply = False, CHAT_FALLBACK.format(biz=w.business_name)
    else:
        reply = CHAT_FALLBACK.format(biz=w.business_name)
    db.session.add(ChatMessage(conversation_id=convo.id, role="assistant", body=reply))
    db.session.commit()
    if first_message and not convo.notified:
        convo.notified = True
        db.session.commit()
        notify_chat(w, convo, f"New chat on {w.business_name}",
                    f"<h2 style='font-family:sans-serif'>New chat conversation</h2>"
                    f"<p style='font-family:sans-serif'>Page: {convo.page_url or '—'}<br>"
                    f"First message: <b>{body[:500]}</b></p>")
    return _cors(jsonify(ok=True, conversation_id=convo.id, reply=reply, ai=ai_ok))


@app.route("/chat/<slug>/contact", methods=["POST", "OPTIONS"])
def chat_contact(slug):
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    w = ChatWidget.query.filter_by(slug=slug).first_or_404()
    p = request.get_json(silent=True) or {}
    name = str(p.get("name", "")).strip()[:120]
    phone = str(p.get("phone", "")).strip()[:40]
    email = str(p.get("email", "")).strip()[:120]
    if not (name or phone or email):
        return _cors(jsonify(ok=False, error="empty")), 400
    convo = None
    if p.get("conversation_id"):
        convo = db.session.get(ChatConversation, int(p["conversation_id"]))
        if convo and convo.widget_id != w.id:
            convo = None
    lead = Lead(owner_id=w.owner_id, name=name or "Chat visitor", phone=phone,
                email=email, business="", source=f"Chat — {w.business_name}")
    db.session.add(lead)
    db.session.flush()
    if convo:
        convo.visitor_name, convo.visitor_phone = name, phone
        convo.visitor_email, convo.lead_id = email, lead.id
        transcript = "".join(f"<p style='font-family:sans-serif;margin:2px 0'>"
                             f"<b>{'Visitor' if m.role == 'user' else 'Assistant'}:</b> "
                             f"{m.body[:400]}</p>" for m in convo.messages[-20:])
    else:
        transcript = ""
    db.session.commit()
    notify_chat(w, convo, f"Chat lead: {name or phone} — {w.business_name}",
                f"<h2 style='font-family:sans-serif'>Chat visitor left their info</h2>"
                f"<table style='font-family:sans-serif;font-size:15px'>"
                f"<tr><td style='padding:4px 12px 4px 0;color:#888'>Name</td><td><b>{name}</b></td></tr>"
                f"<tr><td style='padding:4px 12px 4px 0;color:#888'>Cell</td><td><b>{phone}</b></td></tr>"
                f"<tr><td style='padding:4px 12px 4px 0;color:#888'>Email</td><td><b>{email}</b></td></tr>"
                f"</table><p style='font-family:sans-serif'>It's already in the CRM.</p>{transcript}")
    return _cors(jsonify(ok=True))


# ---------------------------------------------------------------- blueprints
# Imported LAST, after db and every core model exists: the packages do
# `from app import db, Lead, ...` and this is the point where that resolves.
import dialer  # noqa: E402
import enrich  # noqa: E402
import teams  # noqa: E402

dialer.init_app(app)
teams.init_app(app)
enrich.init_app(app)

with app.app_context():
    ensure_schema()          # picks up the dialer/teams tables declared above
    try:
        from dialer.compliance import seed_state_rules
        seed_state_rules()
    except Exception:         # never let seeding stop the app from booting
        pass


if __name__ == "__main__":
    # NOTE: not 5060/5061 — Chrome refuses to load that port (ERR_UNSAFE_PORT — both are SIP ports)
    app.run(debug=True, port=5062)
