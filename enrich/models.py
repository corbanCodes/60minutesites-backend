"""Data enrichment: website research and email personalisation.

Both tools are long-running work over a spreadsheet, so both run as a Job made
of Rows. Rows carry their own state, which means a job survives a closed tab,
a deploy, or a vendor hiccup -- you reopen it and it carries on from the row
it reached.
"""
import json
from datetime import datetime, timezone

from app import db
from dialer import crypto


def _utcnow():
    return datetime.now(timezone.utc)


# OpenAI models worth offering, with their published per-million-token prices.
# Shown in the cost estimate before anyone spends money.
MODELS = [
    {"id": "gpt-4o-mini", "label": "GPT-4o mini",
     "blurb": "The default. Fast and very cheap; good enough for summaries "
              "and first-draft emails.",
     "in": 0.15, "out": 0.60},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini",
     "blurb": "A step up in writing quality for a few times the price.",
     "in": 0.40, "out": 1.60},
    {"id": "gpt-4.1", "label": "GPT-4.1",
     "blurb": "Best writing. Use it when the list is small and the email matters.",
     "in": 2.00, "out": 8.00},
    {"id": "gpt-4o", "label": "GPT-4o",
     "blurb": "Strong all-rounder.", "in": 2.50, "out": 10.00},
]
MODEL_BY_ID = {m["id"]: m for m in MODELS}
DEFAULT_MODEL = "gpt-4o-mini"

JOB_KINDS = ["scrape", "personalize"]
JOB_STATES = ["draft", "running", "paused", "done", "failed"]
ROW_STATES = ["pending", "done", "skipped", "failed"]


class EnrichSettings(db.Model):
    """One row per account. The OpenAI key is theirs, encrypted, and never
    rendered -- only its last four characters are."""
    __tablename__ = "enrich_settings"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    openai_key_enc = db.Column(db.Text)
    openai_last4 = db.Column(db.String(8), default="")
    verified_at = db.Column(db.DateTime)
    verify_error = db.Column(db.String(300), default="")
    available_models = db.Column(db.Text, default="")   # JSON list, from the key
    default_model = db.Column(db.String(60), default=DEFAULT_MODEL)
    scrape_timeout = db.Column(db.Integer, default=15)
    scrape_max_chars = db.Column(db.Integer, default=12000)
    monthly_spend_cap = db.Column(db.Float)             # None = no cap
    spend_this_month = db.Column(db.Float, default=0.0)
    spend_month = db.Column(db.String(7), default="")   # YYYY-MM
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    @property
    def has_key(self):
        return bool(self.openai_key_enc and self.verified_at)

    def key(self):
        return crypto.decrypt(self.openai_key_enc)

    def set_key(self, value):
        self.openai_key_enc = crypto.encrypt(value)
        self.openai_last4 = crypto.last4(value)

    @property
    def models(self):
        """Models this key can actually use, intersected with the ones we price."""
        try:
            allowed = set(json.loads(self.available_models or "[]"))
        except ValueError:
            allowed = set()
        if not allowed:
            return MODELS
        return [m for m in MODELS if m["id"] in allowed] or MODELS


class ScrapedSite(db.Model):
    """One row per domain per account. This table IS the deduplication: a list
    with forty contacts at the same company costs one fetch and one summary."""
    __tablename__ = "scraped_site"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    domain = db.Column(db.String(200), nullable=False, index=True)
    url = db.Column(db.String(600), default="")
    final_url = db.Column(db.String(600), default="")
    title = db.Column(db.String(400), default="")
    text = db.Column(db.Text, default="")
    text_chars = db.Column(db.Integer, default=0)
    summary = db.Column(db.Text, default="")
    model = db.Column(db.String(60), default="")
    prompt_fingerprint = db.Column(db.String(64), default="")
    tokens_in = db.Column(db.Integer, default=0)
    tokens_out = db.Column(db.Integer, default=0)
    cost = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default="ok")   # ok|fetch_failed|ai_failed
    error = db.Column(db.String(400), default="")
    scraped_at = db.Column(db.DateTime, default=_utcnow, index=True)
    summarized_at = db.Column(db.DateTime)

    __table_args__ = (db.UniqueConstraint("account_id", "domain",
                                          name="uq_scraped_account_domain"),)


class EnrichJob(db.Model):
    __tablename__ = "enrich_job"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(20), default="scrape")
    name = db.Column(db.String(200), default="")
    status = db.Column(db.String(12), default="draft", index=True)
    source_filename = db.Column(db.String(300), default="")
    source_media_id = db.Column(db.Integer)
    columns_json = db.Column(db.Text, default="[]")     # header row
    mapping_json = db.Column(db.Text, default="{}")     # which column is what
    config_json = db.Column(db.Text, default="{}")      # prompts, variants, model
    model = db.Column(db.String(60), default=DEFAULT_MODEL)
    total = db.Column(db.Integer, default=0)
    done = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    reused = db.Column(db.Integer, default=0)           # dedupe hits
    cost = db.Column(db.Float, default=0.0)
    tokens_in = db.Column(db.Integer, default=0)
    tokens_out = db.Column(db.Integer, default=0)
    error = db.Column(db.String(400), default="")
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    def _load(self, field, fallback):
        try:
            return json.loads(getattr(self, field) or "")
        except (ValueError, TypeError):
            return fallback

    @property
    def columns(self):
        return self._load("columns_json", [])

    @property
    def mapping(self):
        return self._load("mapping_json", {})

    @property
    def config(self):
        return self._load("config_json", {})

    @property
    def pct(self):
        return round(100 * (self.done or 0) / self.total) if self.total else 0

    @property
    def remaining(self):
        return max(0, (self.total or 0) - (self.done or 0) - (self.failed or 0))


class EnrichRow(db.Model):
    """One spreadsheet row. Keeping per-row state is what makes a job
    resumable and makes a partial export honest."""
    __tablename__ = "enrich_row"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, index=True)
    idx = db.Column(db.Integer, default=0)
    state = db.Column(db.String(12), default="pending", index=True)
    input_json = db.Column(db.Text, default="{}")
    output_json = db.Column(db.Text, default="{}")
    domain = db.Column(db.String(200), default="")
    reused = db.Column(db.Boolean, default=False)
    cost = db.Column(db.Float, default=0.0)
    error = db.Column(db.String(400), default="")
    done_at = db.Column(db.DateTime)

    def _load(self, field):
        try:
            return json.loads(getattr(self, field) or "{}")
        except (ValueError, TypeError):
            return {}

    @property
    def input(self):
        return self._load("input_json")

    @property
    def output(self):
        return self._load("output_json")


class PromptTemplate(db.Model):
    """A saved personalisation setup, so a good prompt gets reused instead of
    rewritten from memory every time."""
    __tablename__ = "prompt_template"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(20), default="personalize")
    subject_prompt = db.Column(db.Text, default="")
    body_prompt = db.Column(db.Text, default="")
    separate_subject = db.Column(db.Boolean, default=True)
    variants = db.Column(db.Integer, default=1)
    model = db.Column(db.String(60), default=DEFAULT_MODEL)
    tone = db.Column(db.String(200), default="")
    max_words = db.Column(db.Integer, default=120)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
