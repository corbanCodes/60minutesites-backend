"""The guard for the mistake that took the site down on 2026-10-02.

A column was added to the User model and to the backfill list, but the edit
that adds it to ensure_schema's migration list silently failed. Every test
still passed, because the test database is built by create_all() from the
models -- so SQLite had the column and Postgres never got it. The first query
against a real database after deploy raised UndefinedColumn on every page
that touches a user, which is all of them.

This file closes that hole: for every table ensure_schema manages, every
column declared on the model must also appear in the migration list. A test
suite that builds its schema from the models cannot otherwise see the gap.
"""
import pytest

import app as app_module
from app import (EmailAccount, Flipbook, Form, Lead, Note, Site, Task,
                 User, db)

# Columns that shipped in the very first version of each table and therefore
# predate the migration list. ensure_schema only needs to know about columns
# added AFTER a table existed in the wild.
ORIGINAL = {
    "user": {"id", "name", "email", "password_hash", "created_at"},
    "lead": {"id", "name", "phone", "email", "business", "business_type",
             "source", "status", "created_at"},
    "task": {"id", "owner_id", "lead_id", "title", "kind", "due_at", "done",
             "done_at", "created_at"},
    "note": {"id", "lead_id", "body", "created_at"},
    "form": {"id", "owner_id", "name", "slug", "redirect_url", "created_at"},
    "site": {"id", "slug", "business_name", "tagline", "phone", "email",
             "services", "about", "color", "style", "created_at",
             "updated_at"},
    "flipbook": {"id", "owner_id", "slug", "title", "pages", "created_at",
                 "name", "page_count"},
    "flipbook_page": {"id", "flipbook_id", "num", "png", "created_at",
                      "width", "height"},
}

MODELS = {"user": User, "lead": Lead, "task": Task, "note": Note,
          "form": Form, "site": Site}


def _managed_tables():
    """Every table ensure_schema is responsible for, model included.

    The guard originally watched only the six CRM tables, because those were
    the ones that existed when it was written. The dialer and teams tables
    are in production now and create_all() will not alter one that already
    exists, so a column added to any of them needs a migration line exactly
    like a column on `user` does. This finds them rather than relying on
    somebody remembering to add them to a list.
    """
    out = {}
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        name = getattr(cls, "__tablename__", None)
        if name:
            out[name] = cls
    return out


# What each dialer/teams table shipped with, captured at the commit that put
# them in production. This is written down rather than read back off the
# models, because reading it off the models compares them to themselves and
# the test can never fail -- which is exactly what the first version of this
# did. A column added to any of these tables from now on has to appear in
# ensure_schema's migration list, and this snapshot is what notices.
#
# Updating a line here is correct ONLY when the table itself is brand new, so
# create_all() will build it complete wherever it does not exist yet.
SHIPPED_WITH_TABLE = {
    "ai_agent": {"account_id", "active", "background_preset", "company_facts", "created_at", "direction", "dtmf_enabled", "elevenlabs_agent_id", "first_message", "id", "knowledge_text", "language", "last_sync_error", "llm_model", "max_duration_seconds", "name", "persona", "playbook_id", "synced_at", "transfer_rules", "updated_at", "voice_id", "voice_name", "voicemail_behavior", "voicemail_drop_id", "voicemail_message"},
    "email_account": {"address", "created_at", "id", "notes", "owner_id", "password"},
    "audit_log": {"account_id", "action", "actor", "created_at", "detail", "id", "ip", "target", "user_id"},
    "call": {"account_id", "agent_user_id", "ai_agent_id", "announce_played_at", "answered_at", "answered_live", "billable_minutes", "campaign_id", "campaign_lead_id", "coaching_json", "conference_name", "conference_sid", "connected_within_2s", "consent_at_dial", "cost_estimate", "created_at", "direction", "disclosure_text", "disposition", "disposition_by", "dtmf_log", "duration_s", "elevenlabs_conversation_id", "ended_at", "error", "finalized_at", "from_number", "gate_decision", "id", "lead_id", "line_type_at_dial", "mode", "notes_draft", "objections_json", "qualification_json", "recording_deleted_at", "recording_duration_s", "recording_sid", "recording_started_at", "recording_url", "revocation_detected", "score", "started_at", "status", "summary", "system_outcome", "to_number", "transcript", "transferred_to", "twilio_sid", "vendor_cost", "voicemail_dropped"},
    "call_event": {"account_id", "at", "call_id", "detail", "id", "kind", "payload"},
    "campaign": {"account_id", "ai_agent_id", "amd_enabled", "created_at", "created_by", "finished_at", "id", "max_concurrent", "mode", "name", "number_pool", "paused_reason", "playbook_id", "segment_json", "started_at", "stats_json", "status", "voicemail_drop_id", "window_override_json"},
    "campaign_lead": {"account_id", "attempts", "campaign_id", "created_at", "id", "last_call_id", "lead_id", "lead_tz", "lease_until", "locked_at", "locked_by", "next_attempt_at", "outcome", "position", "skip_reason", "state"},
    "chat_conversation": {"created_at", "id", "lead_id", "notified", "page_url", "updated_at", "visitor_email", "visitor_name", "visitor_phone", "widget_id"},
    "chat_message": {"body", "conversation_id", "created_at", "id", "role"},
    "chat_widget": {"accent", "ai_enabled", "booking_url", "business_name", "contact_email", "contact_phone", "created_at", "enabled", "greeting", "id", "monthly_limit", "notify_email", "owner_id", "slug", "system_prompt", "used_count", "used_month"},
    "coach_tick": {"at", "body", "call_id", "id", "kind", "objection", "seq", "step"},
    "consent_record": {"account_id", "captured_at", "created_by", "evidence_url", "id", "kind", "lead_id", "phone_key", "revoked_at", "source", "text"},
    "dialer_settings": {"account_id", "ai_callback_number", "ai_disclosure_enabled", "ai_disclosure_name", "ai_disclosure_text", "amd_default", "announce_mode", "announce_text", "background_gain", "background_noise", "background_preset", "created_at", "elevenlabs_bursting", "elevenlabs_concurrency", "elevenlabs_default_voice_id", "elevenlabs_key_enc", "elevenlabs_last4", "elevenlabs_tier", "elevenlabs_verified_at", "elevenlabs_verify_error", "elevenlabs_webhook_error", "elevenlabs_webhook_id", "elevenlabs_webhook_secret_enc", "enforce_window", "gate_ai_line_type", "gate_ai_line_type_off_at", "gate_ai_line_type_off_by", "gate_attestation", "honor_national_dnc", "honor_state_rules", "id", "idle_hangup_seconds", "intent", "line_type_max_age_days", "live_transcription", "llm_key_enc", "llm_last4", "llm_model", "llm_provider", "llm_verified_at", "llm_verify_error", "max_call_seconds", "max_concurrent_ai", "recording_announce", "recording_enabled", "rep_idle_teardown_seconds", "retention_days", "retry_json", "simulation", "smart_window", "stage_map_json", "stt_model", "transfer_mode", "transfer_number", "treat_voip_as_mobile", "twilio_account_sid_enc", "twilio_api_key_secret_enc", "twilio_api_key_sid_enc", "twilio_auth_token_enc", "twilio_balance", "twilio_concurrency_cap", "twilio_cps", "twilio_is_trial", "twilio_pcp_checked_at", "twilio_pcp_status", "twilio_sid_last4", "twilio_twiml_app_sid", "twilio_verified_at", "twilio_verify_error", "updated_at", "window_days", "window_end", "window_start", "wizard_state"},
    "enrich_job": {"account_id", "columns_json", "config_json", "cost", "created_at", "created_by", "done", "error", "failed", "finished_at", "id", "kind", "mapping_json", "model", "name", "reused", "source_filename", "source_media_id", "started_at", "status", "tokens_in", "tokens_out", "total"},
    "enrich_row": {"account_id", "cost", "domain", "done_at", "error", "id", "idx", "input_json", "job_id", "output_json", "reused", "state"},
    "enrich_settings": {"account_id", "available_models", "created_at", "default_model", "id", "monthly_spend_cap", "openai_key_enc", "openai_last4", "scrape_max_chars", "scrape_timeout", "spend_month", "spend_this_month", "updated_at", "verified_at", "verify_error"},
    "invitation": {"accepted_at", "account_id", "cancelled_at", "created_at", "email", "expires_at", "id", "invited_by", "job_title", "name", "role"},
    "media": {"created_at", "data", "filename", "id", "mimetype", "owner_id"},
    "phone_number": {"account_id", "answer_rate_7d", "area_code", "calls_today", "calls_today_date", "cnam_status", "cnam_value", "created_at", "daily_cap", "e164", "elevenlabs_phone_id", "first_outbound_at", "friendly_name", "id", "last_outbound_at", "notes", "parked_until", "pool", "purpose", "region", "state", "twilio_sid", "voice_integrity_status"},
    "playbook": {"account_id", "created_at", "description", "id", "is_default", "name", "never_do", "objections_json", "questions_json", "steps_json", "transfer_criteria", "updated_at"},
    "prompt_template": {"account_id", "body_prompt", "created_at", "id", "kind", "max_words", "model", "name", "separate_subject", "subject_prompt", "tone", "updated_at", "variants"},
    "rep_presence": {"account_id", "available_for_transfers", "campaign_id", "conference_name", "connects_today", "current_call_id", "dials_today", "id", "last_seen_at", "on_shift", "rep_call_sid", "shift_started_at", "stats_date", "talk_seconds_today", "user_id"},
    "scraped_site": {"account_id", "cost", "domain", "error", "final_url", "id", "model", "prompt_fingerprint", "scraped_at", "status", "summarized_at", "summary", "text", "text_chars", "title", "tokens_in", "tokens_out", "url"},
    "site_revision": {"created_at", "html", "id", "site_id"},
    "state_rule": {"ai_outbound", "all_party_recording", "id", "identify_within_seconds", "max_calls_per_day", "name", "no_sunday", "notes", "state_code", "updated_at", "window_end", "window_start"},
    "suppression": {"account_id", "call_id", "created_at", "created_by", "id", "lead_id", "phone_key", "reason", "source"},
    "trusthub_bundle": {"account_id", "bundle_sid", "created_at", "failure_json", "id", "kind", "last_checked_at", "next_check_at", "status"},
    "voicemail_drop": {"account_id", "created_at", "duration_s", "id", "is_default", "media_id", "mimetype", "name", "transcript"},
    "webhook_inbox": {"account_id", "attempts", "dedupe_key", "error", "id", "kind", "payload", "processed_at", "received_at", "signature_ok", "source"}
}


def _wanted():
    """Re-read the migration list the way ensure_schema builds it."""
    import inspect as pyinspect
    import re
    src = pyinspect.getsource(app_module._ensure_schema_inner)
    start = src.index("wanted = {")
    depth, i = 0, start + len("wanted = ")
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    # strip comments so eval sees a plain literal
    literal = re.sub(r"#.*", "", src[i:end])
    return eval(literal)   # noqa: S307 - our own source, not user input


@pytest.mark.parametrize("table", sorted(MODELS))
def test_every_model_column_is_in_the_migration_list(ctx, table):
    """If this fails, the column exists in tests and will NOT exist in
    production. Add it to the `wanted` dict in ensure_schema."""
    model = MODELS[table]
    wanted = _wanted()
    declared = {c.name for c in model.__table__.columns}
    covered = set(wanted.get(table, {})) | ORIGINAL.get(table, set())
    missing = declared - covered
    assert not missing, (
        f"{table}: {sorted(missing)} are declared on the model but are not in "
        f"ensure_schema's migration list, so a real Postgres database will "
        f"never get them.")


def test_the_backfill_only_names_columns_the_migration_adds(ctx):
    """A backfill for a column that is never added is dead code, and a sign
    the two lists have drifted apart."""
    import inspect as pyinspect
    import re
    src = pyinspect.getsource(app_module._ensure_schema_inner)
    pairs = set(re.findall(r'\("(\w+)",\s*"(\w+)"\):', src))
    wanted = _wanted()
    for table, col in sorted(pairs):
        assert col in wanted.get(table, {}), (
            f'backfill names {table}.{col} but ensure_schema never adds it')


def test_running_the_migration_twice_is_a_no_op(ctx):
    app_module.ensure_schema()
    app_module.ensure_schema()


def test_the_feature_columns_are_all_covered(ctx):
    """The three add-on flags and the tool-visibility column specifically,
    because these are the ones that broke."""
    wanted = _wanted()
    for col in ("feature_multi_user", "feature_dialer", "feature_enrichment",
                "hidden_tools", "account_id", "role", "active", "seat_limit"):
        assert col in wanted["user"], f"user.{col} missing from the migration list"


# --------------------------------------------------- the dialer/teams tables
def test_a_new_dialer_column_must_be_in_the_migration_list(ctx):
    """The gap this file was written to close, left open for half the schema.

    ensure_schema's create_all() creates a table that does not exist and does
    nothing at all to one that does. So the first column added to any dialer
    or teams table after it shipped would be present in SQLite, absent in
    Postgres, and would 500 every page that touched it -- which is exactly
    the outage this file exists to prevent, one table over.

    The snapshot is taken from the models themselves, so it does not need
    maintaining; it only asks that anything beyond what a table shipped with
    is declared.
    """
    wanted = _wanted()
    managed = _managed_tables()
    problems = []
    for table, shipped in SHIPPED_WITH_TABLE.items():
        cls = managed.get(table)
        if cls is None:
            continue
        declared = {c.name for c in cls.__table__.columns}
        later = declared - set(shipped) - set(wanted.get(table, {}))
        if later:
            problems.append(f"{table}: {sorted(later)}")
    assert not problems, (
        "columns on a live table that ensure_schema would never add: "
        + "; ".join(problems))


def test_the_elevenlabs_webhook_error_column_is_migrated(ctx):
    """A named case, because this is the column that prompted the check and a
    regression here is silent until an ElevenLabs key is connected."""
    assert "elevenlabs_webhook_error" in _wanted().get("dialer_settings", {})


def test_the_shipped_snapshot_actually_covers_the_live_tables(ctx):
    """Keeps the guard above honest. If the snapshot drifts out of sync with
    the models -- a table renamed, a table dropped -- the comparison quietly
    checks nothing, which is the failure mode this whole file exists to
    prevent one level down."""
    managed = set(_managed_tables())
    core = set(MODELS) | set(ORIGINAL)
    unwatched = sorted(managed - core - set(SHIPPED_WITH_TABLE))
    assert not unwatched, (
        f"these tables are in no snapshot and no migration list, so a new "
        f"column on them is invisible to every test here: {unwatched}")
