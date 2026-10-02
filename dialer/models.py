"""Dialer tables. Additive only -- new tables plus new columns on `lead`,
`task`, `note` and `user` (those are added by ensure_schema in app.py).
"""
import json
from datetime import datetime, timezone

from app import db
from dialer import crypto


def _utcnow():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- vocabularies
LANES = ["manual", "power", "ai_outbound", "ai_inbound", "voicemail"]

# What the system observed (derived from the carrier), drives retry/backoff.
SYSTEM_OUTCOMES = ["answered_human", "answered_machine", "busy", "no_answer",
                   "failed", "canceled", "unknown"]

# What a person (or the AI) decided, drives lead stage. Kept short on purpose:
# reps pick these under time pressure between dials.
DISPOSITIONS = [
    ("dm_reached",    "Decision maker",  "bi-person-check",     "1"),
    ("gatekeeper",    "Gatekeeper",      "bi-person-lock",      "2"),
    ("callback",      "Call back later", "bi-clock-history",    "3"),
    ("meeting_set",   "Meeting set",     "bi-calendar-check",   "4"),
    ("qualified",     "Qualified",       "bi-patch-check",      "5"),
    ("not_interested", "Not interested", "bi-hand-thumbs-down", "6"),
    ("voicemail_left", "Voicemail left", "bi-voicemail",        "7"),
    ("wrong_number",  "Wrong number",    "bi-telephone-x",      "8"),
    ("dnc",           "Do not call",     "bi-slash-circle",     "9"),
]
DISPOSITION_KEYS = [d[0] for d in DISPOSITIONS]
DISPOSITION_LABELS = {d[0]: d[1] for d in DISPOSITIONS}
DISPOSITION_ICONS = {d[0]: d[2] for d in DISPOSITIONS}
DISPOSITION_HOTKEYS = {d[0]: d[3] for d in DISPOSITIONS}

# disposition -> lead stage. Editable per account via DialerSettings.stage_map_json.
DEFAULT_STAGE_MAP = {
    "dm_reached": "Contacted", "gatekeeper": "Contacted", "callback": "Contacted",
    "voicemail_left": "Contacted", "meeting_set": "Qualified", "qualified": "Qualified",
    "not_interested": "Dead", "wrong_number": "", "dnc": "Dead",
}
# stages we will only ever move a lead FORWARD from (never demote a Client)
PROTECTED_STAGES = {"Client", "Built", "Booked"}

LINE_TYPES = ["landline", "mobile", "fixedVoip", "nonFixedVoip", "tollFree",
              "voicemail", "unknown"]
# Treated as "could be a cell" unless the account overrides.
RESTRICTED_LINE_TYPES = {"mobile", "nonFixedVoip", "fixedVoip", "voicemail", "unknown"}

CONSENT_KINDS = ["none", "express", "written", "inbound", "existing_relationship"]


# ------------------------------------------------------------------- settings
class DialerSettings(db.Model):
    """One row per account. Vendor keys are stored encrypted; the UI only ever
    renders the *_last4 columns."""
    __tablename__ = "dialer_settings"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, unique=True, index=True)

    # --- Twilio
    twilio_account_sid_enc = db.Column(db.Text)
    twilio_auth_token_enc = db.Column(db.Text)
    twilio_api_key_sid_enc = db.Column(db.Text)
    twilio_api_key_secret_enc = db.Column(db.Text)
    twilio_twiml_app_sid = db.Column(db.String(64), default="")
    twilio_sid_last4 = db.Column(db.String(8), default="")
    twilio_verified_at = db.Column(db.DateTime)
    twilio_verify_error = db.Column(db.String(300), default="")
    twilio_balance = db.Column(db.String(32), default="")
    twilio_is_trial = db.Column(db.Boolean, default=False)
    twilio_pcp_status = db.Column(db.String(20), default="none")  # none|individual|business|pending
    twilio_pcp_checked_at = db.Column(db.DateTime)
    twilio_cps = db.Column(db.Integer, default=1)
    twilio_concurrency_cap = db.Column(db.Integer)

    # --- ElevenLabs
    elevenlabs_key_enc = db.Column(db.Text)
    elevenlabs_last4 = db.Column(db.String(8), default="")
    elevenlabs_verified_at = db.Column(db.DateTime)
    elevenlabs_verify_error = db.Column(db.String(300), default="")
    elevenlabs_tier = db.Column(db.String(32), default="")
    elevenlabs_concurrency = db.Column(db.Integer, default=0)
    elevenlabs_webhook_id = db.Column(db.String(64), default="")
    # Why the webhook could not be created, in ElevenLabs' own words. Kept
    # because the only place this used to appear was a flash message, so the
    # page afterwards could say nothing but "Missing" and a guess at the cause.
    elevenlabs_webhook_error = db.Column(db.String(400), default="")
    elevenlabs_webhook_secret_enc = db.Column(db.Text)
    elevenlabs_default_voice_id = db.Column(db.String(64), default="")
    elevenlabs_bursting = db.Column(db.Boolean, default=False)

    # --- LLM / transcription
    llm_provider = db.Column(db.String(20), default="openai")   # openai|anthropic
    llm_key_enc = db.Column(db.Text)
    llm_last4 = db.Column(db.String(8), default="")
    llm_model = db.Column(db.String(60), default="gpt-4o-mini")
    llm_verified_at = db.Column(db.DateTime)
    llm_verify_error = db.Column(db.String(300), default="")
    stt_model = db.Column(db.String(60), default="gpt-4o-mini-transcribe")

    # --- compliance
    recording_enabled = db.Column(db.Boolean, default=True)
    recording_announce = db.Column(db.Boolean, default=True)
    announce_text = db.Column(db.String(400),
                              default="This call may be recorded for quality and training.")
    announce_mode = db.Column(db.String(20), default="proceed")  # proceed|verbal_yes
    ai_disclosure_enabled = db.Column(db.Boolean, default=True)
    ai_disclosure_name = db.Column(db.String(160), default="")
    ai_callback_number = db.Column(db.String(32), default="")
    ai_disclosure_text = db.Column(db.String(400), default="")
    window_start = db.Column(db.String(5), default="09:00")   # lead-local HH:MM
    window_end = db.Column(db.String(5), default="19:00")
    window_days = db.Column(db.String(20), default="1,2,3,4,5,6")  # iso weekdays
    smart_window = db.Column(db.Boolean, default=False)       # 2-4pm hospitality
    enforce_window = db.Column(db.Boolean, default=True)
    # The gate. Default ON. An owner/admin may switch these off; doing so writes
    # an audit row with the attestation text and stamps *_at / *_by.
    gate_ai_line_type = db.Column(db.Boolean, default=True)
    gate_ai_line_type_off_at = db.Column(db.DateTime)
    gate_ai_line_type_off_by = db.Column(db.Integer)
    gate_attestation = db.Column(db.Text, default="")
    treat_voip_as_mobile = db.Column(db.Boolean, default=True)
    line_type_max_age_days = db.Column(db.Integer, default=30)
    honor_state_rules = db.Column(db.Boolean, default=True)
    honor_national_dnc = db.Column(db.Boolean, default=False)
    retention_days = db.Column(db.Integer, default=90)

    # --- behaviour
    max_call_seconds = db.Column(db.Integer, default=600)
    idle_hangup_seconds = db.Column(db.Integer)
    rep_idle_teardown_seconds = db.Column(db.Integer, default=300)
    background_noise = db.Column(db.Boolean, default=False)
    background_preset = db.Column(db.String(20), default="office1")
    background_gain = db.Column(db.Float, default=0.15)
    transfer_mode = db.Column(db.String(20), default="browser")  # browser|number
    transfer_number = db.Column(db.String(32), default="")
    amd_default = db.Column(db.Boolean, default=False)
    live_transcription = db.Column(db.Boolean, default=False)
    max_concurrent_ai = db.Column(db.Integer, default=2)
    retry_json = db.Column(db.Text, default="")
    stage_map_json = db.Column(db.Text, default="")

    # --- wizard / mode
    wizard_state = db.Column(db.Text, default="")
    simulation = db.Column(db.Boolean, default=False)
    intent = db.Column(db.String(40), default="")  # human|ai_inbound|ai_outbound|both

    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # ---- convenience
    def secret(self, field):
        return crypto.decrypt(getattr(self, field + "_enc", None))

    def set_secret(self, field, value, last4_field=None):
        setattr(self, field + "_enc", crypto.encrypt(value))
        if last4_field:
            setattr(self, last4_field, crypto.last4(value))

    @property
    def wizard(self):
        try:
            return json.loads(self.wizard_state or "{}")
        except ValueError:
            return {}

    def set_wizard(self, data):
        self.wizard_state = json.dumps(data)

    @property
    def stage_map(self):
        try:
            m = json.loads(self.stage_map_json or "{}")
        except ValueError:
            m = {}
        out = dict(DEFAULT_STAGE_MAP)
        out.update({k: v for k, v in m.items() if k in DEFAULT_STAGE_MAP})
        return out

    @property
    def retry_policy(self):
        default = {"busy": {"attempts": 2, "minutes": 20},
                   "no_answer": {"attempts": 2, "minutes": 1440},
                   "answered_machine": {"attempts": 1, "minutes": 1440},
                   "failed": {"attempts": 0, "minutes": 0}}
        try:
            d = json.loads(self.retry_json or "{}")
        except ValueError:
            d = {}
        for k, v in (d or {}).items():
            if k in default and isinstance(v, dict):
                default[k].update(v)
        return default

    @property
    def window_weekdays(self):
        try:
            return {int(x) for x in (self.window_days or "").split(",") if x.strip()}
        except ValueError:
            return {1, 2, 3, 4, 5, 6}

    @property
    def has_twilio(self):
        return bool(self.twilio_account_sid_enc and self.twilio_verified_at)

    @property
    def has_elevenlabs(self):
        return bool(self.elevenlabs_key_enc and self.elevenlabs_verified_at)

    @property
    def has_llm(self):
        return bool(self.llm_key_enc and self.llm_verified_at)

    # Booleans whose column default only applies on INSERT. Reading them off
    # an unsaved row gives None, and "None" must mean the SAFE answer, not off.
    @property
    def disclose_ai(self):
        return self.ai_disclosure_enabled is not False

    @property
    def announce_recording(self):
        return self.recording_announce is not False

    @property
    def records_calls(self):
        return self.recording_enabled is not False

    @property
    def gate_on(self):
        return self.gate_ai_line_type is not False

    @property
    def effective_disclosure(self):
        if self.ai_disclosure_text:
            return self.ai_disclosure_text
        who = self.ai_disclosure_name or "our company"
        line = f"Hi, this is an automated AI assistant calling on behalf of {who}."
        if self.ai_callback_number:
            line += f" You can reach a person any time at {self.ai_callback_number}."
        return line


# -------------------------------------------------------------------- numbers
class PhoneNumber(db.Model):
    """A Twilio DID. `pool` matters: a number imported into ElevenLabs has its
    Twilio voice webhook owned by ElevenLabs, so it cannot also serve the human
    dialer's callbacks."""
    __tablename__ = "phone_number"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    e164 = db.Column(db.String(20), nullable=False)
    twilio_sid = db.Column(db.String(64), default="")
    friendly_name = db.Column(db.String(120), default="")
    pool = db.Column(db.String(10), default="rep")        # rep|ai
    purpose = db.Column(db.String(12), default="both")    # outbound|inbound|both
    elevenlabs_phone_id = db.Column(db.String(64), default="")
    state = db.Column(db.String(12), default="active")    # active|parked|released
    area_code = db.Column(db.String(5), default="")
    region = db.Column(db.String(60), default="")
    daily_cap = db.Column(db.Integer, default=120)
    calls_today = db.Column(db.Integer, default=0)
    calls_today_date = db.Column(db.Date)
    answer_rate_7d = db.Column(db.Float)
    first_outbound_at = db.Column(db.DateTime)
    last_outbound_at = db.Column(db.DateTime)
    parked_until = db.Column(db.DateTime)
    cnam_status = db.Column(db.String(24), default="")
    cnam_value = db.Column(db.String(20), default="")
    voice_integrity_status = db.Column(db.String(24), default="")
    notes = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=_utcnow)

    @property
    def pretty(self):
        d = "".join(c for c in (self.e164 or "") if c.isdigit())
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        if len(d) == 10:
            return f"({d[:3]}) {d[3:6]}-{d[6:]}"
        return self.e164 or ""


# --------------------------------------------------------------------- agents
class AiAgent(db.Model):
    __tablename__ = "ai_agent"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    direction = db.Column(db.String(10), default="outbound")  # outbound|inbound
    elevenlabs_agent_id = db.Column(db.String(64), default="")
    voice_id = db.Column(db.String(64), default="")
    voice_name = db.Column(db.String(80), default="")
    llm_model = db.Column(db.String(60), default="gemini-2.0-flash")
    language = db.Column(db.String(10), default="en")
    first_message = db.Column(db.Text, default="")
    persona = db.Column(db.Text, default="")
    company_facts = db.Column(db.Text, default="")
    playbook_id = db.Column(db.Integer)
    transfer_rules = db.Column(db.Text, default="")
    max_duration_seconds = db.Column(db.Integer, default=420)
    voicemail_behavior = db.Column(db.String(16), default="leave_tts")  # hangup|leave_tts|drop
    voicemail_message = db.Column(db.Text, default="")
    voicemail_drop_id = db.Column(db.Integer)
    dtmf_enabled = db.Column(db.Boolean, default=True)
    background_preset = db.Column(db.String(20), default="")
    knowledge_text = db.Column(db.Text, default="")
    active = db.Column(db.Boolean, default=True)
    synced_at = db.Column(db.DateTime)
    last_sync_error = db.Column(db.String(400), default="")
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class Playbook(db.Model):
    """Reusable scripts, objections and qualification questions. Shared by the
    AI prompt builder and the human rep's rail."""
    __tablename__ = "playbook"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    steps_json = db.Column(db.Text, default="[]")
    objections_json = db.Column(db.Text, default="[]")
    questions_json = db.Column(db.Text, default="[]")
    transfer_criteria = db.Column(db.Text, default="")
    never_do = db.Column(db.Text, default="")
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def _load(self, field, fallback):
        try:
            v = json.loads(getattr(self, field) or "")
            return v if isinstance(v, list) else fallback
        except (ValueError, TypeError):
            return fallback

    @property
    def steps(self):
        return self._load("steps_json", [])

    @property
    def objections(self):
        return self._load("objections_json", [])

    @property
    def questions(self):
        return self._load("questions_json", [])


class VoicemailDrop(db.Model):
    __tablename__ = "voicemail_drop"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    media_id = db.Column(db.Integer)
    mimetype = db.Column(db.String(60), default="audio/wav")
    duration_s = db.Column(db.Float)
    transcript = db.Column(db.Text, default="")
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)


# ------------------------------------------------------------------ campaigns
class Campaign(db.Model):
    __tablename__ = "campaign"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    mode = db.Column(db.String(16), default="power")  # power|ai|voicemail
    ai_agent_id = db.Column(db.Integer)
    playbook_id = db.Column(db.Integer)
    voicemail_drop_id = db.Column(db.Integer)
    number_pool = db.Column(db.String(10), default="rep")
    segment_json = db.Column(db.Text, default="{}")
    status = db.Column(db.String(12), default="draft")  # draft|running|paused|done
    max_concurrent = db.Column(db.Integer, default=1)
    amd_enabled = db.Column(db.Boolean, default=False)
    window_override_json = db.Column(db.Text, default="")
    created_by = db.Column(db.Integer)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    paused_reason = db.Column(db.String(200), default="")
    stats_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=_utcnow)

    @property
    def segment(self):
        try:
            return json.loads(self.segment_json or "{}")
        except ValueError:
            return {}

    @property
    def stats(self):
        try:
            return json.loads(self.stats_json or "{}")
        except ValueError:
            return {}


class CampaignLead(db.Model):
    """The queue. Claimed with FOR UPDATE SKIP LOCKED so two workers (or two
    reps) can never take the same lead."""
    __tablename__ = "campaign_lead"
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, nullable=False, index=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    state = db.Column(db.String(12), default="queued", index=True)
    # queued|claimed|dialing|in_call|done|skipped|deferred
    attempts = db.Column(db.Integer, default=0)
    next_attempt_at = db.Column(db.DateTime, default=_utcnow, index=True)
    lead_tz = db.Column(db.String(40), default="America/New_York")
    last_call_id = db.Column(db.Integer)
    outcome = db.Column(db.String(30), default="")
    skip_reason = db.Column(db.String(120), default="")
    locked_by = db.Column(db.String(60), default="")
    locked_at = db.Column(db.DateTime)
    lease_until = db.Column(db.DateTime)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (db.UniqueConstraint("campaign_id", "lead_id",
                                          name="uq_campaign_lead"),)


# ---------------------------------------------------------------------- calls
class Call(db.Model):
    __tablename__ = "call"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    lead_id = db.Column(db.Integer, index=True)
    campaign_id = db.Column(db.Integer, index=True)
    campaign_lead_id = db.Column(db.Integer)
    direction = db.Column(db.String(10), default="outbound")
    mode = db.Column(db.String(16), default="manual")
    agent_user_id = db.Column(db.Integer)
    ai_agent_id = db.Column(db.Integer)
    from_number = db.Column(db.String(20), default="")
    to_number = db.Column(db.String(20), default="")

    # compliance evidence, frozen at dial time
    line_type_at_dial = db.Column(db.String(16), default="")
    consent_at_dial = db.Column(db.String(20), default="")
    gate_decision = db.Column(db.Text, default="")
    disclosure_text = db.Column(db.Text, default="")
    announce_played_at = db.Column(db.DateTime)

    twilio_sid = db.Column(db.String(64), index=True)
    conference_sid = db.Column(db.String(64), default="")
    conference_name = db.Column(db.String(120), default="")
    elevenlabs_conversation_id = db.Column(db.String(64), index=True)

    status = db.Column(db.String(20), default="queued")
    system_outcome = db.Column(db.String(20), default="")
    answered_live = db.Column(db.Boolean, default=False)
    connected_within_2s = db.Column(db.Boolean)
    disposition = db.Column(db.String(30), default="")
    disposition_by = db.Column(db.Integer)

    started_at = db.Column(db.DateTime, default=_utcnow, index=True)
    answered_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    duration_s = db.Column(db.Integer, default=0)
    billable_minutes = db.Column(db.Integer, default=0)

    recording_sid = db.Column(db.String(64), default="")
    recording_url = db.Column(db.String(500), default="")
    recording_duration_s = db.Column(db.Integer)
    recording_started_at = db.Column(db.DateTime)
    recording_deleted_at = db.Column(db.DateTime)

    transcript = db.Column(db.Text, default="")
    summary = db.Column(db.Text, default="")
    qualification_json = db.Column(db.Text, default="")
    score = db.Column(db.Integer)
    coaching_json = db.Column(db.Text, default="")
    objections_json = db.Column(db.Text, default="")
    revocation_detected = db.Column(db.Boolean, default=False)

    transferred_to = db.Column(db.String(120), default="")
    voicemail_dropped = db.Column(db.Boolean, default=False)
    dtmf_log = db.Column(db.String(200), default="")

    cost_estimate = db.Column(db.Float, default=0.0)
    vendor_cost = db.Column(db.Float)
    finalized_at = db.Column(db.DateTime)
    error = db.Column(db.String(400), default="")
    notes_draft = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_utcnow)

    @property
    def gate(self):
        try:
            return json.loads(self.gate_decision or "{}")
        except ValueError:
            return {}

    @property
    def qualification(self):
        try:
            return json.loads(self.qualification_json or "{}")
        except ValueError:
            return {}

    @property
    def coaching(self):
        try:
            return json.loads(self.coaching_json or "{}")
        except ValueError:
            return {}

    @property
    def duration_pretty(self):
        s = int(self.duration_s or 0)
        return f"{s // 60}:{s % 60:02d}"


class CallEvent(db.Model):
    """Every webhook and state change -- the debug timeline on a call page."""
    __tablename__ = "call_event"
    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, index=True)
    account_id = db.Column(db.Integer, index=True)
    at = db.Column(db.DateTime, default=_utcnow)
    kind = db.Column(db.String(40), default="")
    detail = db.Column(db.String(300), default="")
    payload = db.Column(db.Text, default="")


class WebhookInbox(db.Model):
    """Webhooks land here and return 204 immediately; the worker processes.
    dedupe_key makes replays idempotent."""
    __tablename__ = "webhook_inbox"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True)
    source = db.Column(db.String(30), default="")
    kind = db.Column(db.String(40), default="")
    dedupe_key = db.Column(db.String(200), unique=True)
    signature_ok = db.Column(db.Boolean, default=False)
    payload = db.Column(db.Text, default="")
    received_at = db.Column(db.DateTime, default=_utcnow, index=True)
    processed_at = db.Column(db.DateTime, index=True)
    attempts = db.Column(db.Integer, default=0)
    error = db.Column(db.String(400), default="")


# ----------------------------------------------------------------- compliance
class Suppression(db.Model):
    """Tenant-scoped do-not-call. Checked inside the queue claim, not at dial."""
    __tablename__ = "suppression"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    phone_key = db.Column(db.String(20), nullable=False, index=True)
    reason = db.Column(db.String(200), default="")
    source = db.Column(db.String(20), default="manual")
    lead_id = db.Column(db.Integer)
    call_id = db.Column(db.Integer)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (db.UniqueConstraint("account_id", "phone_key",
                                          name="uq_suppression_account_phone"),)


class ConsentRecord(db.Model):
    """Evidence that unlocks a lead for AI dialing regardless of line type."""
    __tablename__ = "consent_record"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    lead_id = db.Column(db.Integer, index=True)
    phone_key = db.Column(db.String(20), index=True)
    kind = db.Column(db.String(24), default="express")
    source = db.Column(db.String(120), default="")
    text = db.Column(db.Text, default="")
    evidence_url = db.Column(db.String(400), default="")
    captured_at = db.Column(db.DateTime, default=_utcnow)
    created_by = db.Column(db.Integer)
    revoked_at = db.Column(db.DateTime)


class StateRule(db.Model):
    """Per-state overlay, seeded then editable -- a lawyer can update it without
    a deploy."""
    __tablename__ = "state_rule"
    id = db.Column(db.Integer, primary_key=True)
    state_code = db.Column(db.String(2), nullable=False, unique=True)
    name = db.Column(db.String(40), default="")
    ai_outbound = db.Column(db.String(10), default="allow")  # allow|counsel|block
    window_start = db.Column(db.String(5), default="")
    window_end = db.Column(db.String(5), default="")
    max_calls_per_day = db.Column(db.Integer)
    identify_within_seconds = db.Column(db.Integer)
    all_party_recording = db.Column(db.Boolean, default=False)
    no_sunday = db.Column(db.Boolean, default=False)
    notes = db.Column(db.String(400), default="")
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class TrustHubBundle(db.Model):
    __tablename__ = "trusthub_bundle"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(20), default="")  # pcp|voice_integrity|cnam|shaken
    bundle_sid = db.Column(db.String(64), default="")
    status = db.Column(db.String(24), default="")
    last_checked_at = db.Column(db.DateTime)
    next_check_at = db.Column(db.DateTime)
    failure_json = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_utcnow)


class RepPresence(db.Model):
    """Who is on shift / available for AI transfers. One row per user."""
    __tablename__ = "rep_presence"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    on_shift = db.Column(db.Boolean, default=False)
    available_for_transfers = db.Column(db.Boolean, default=False)
    conference_name = db.Column(db.String(120), default="")
    rep_call_sid = db.Column(db.String(64), default="")
    current_call_id = db.Column(db.Integer)
    campaign_id = db.Column(db.Integer)
    last_seen_at = db.Column(db.DateTime, default=_utcnow)
    shift_started_at = db.Column(db.DateTime)
    dials_today = db.Column(db.Integer, default=0)
    connects_today = db.Column(db.Integer, default=0)
    talk_seconds_today = db.Column(db.Integer, default=0)
    stats_date = db.Column(db.Date)


class CoachTick(db.Model):
    """Live-coaching suggestions, polled by the rep's rail."""
    __tablename__ = "coach_tick"
    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, index=True)
    seq = db.Column(db.Integer, default=0)
    at = db.Column(db.DateTime, default=_utcnow)
    kind = db.Column(db.String(24), default="suggestion")
    step = db.Column(db.String(120), default="")
    objection = db.Column(db.String(200), default="")
    body = db.Column(db.Text, default="")
