"""Dialer UI: home, the setup wizard, numbers, playbooks, agents, voicemail."""
import json
from datetime import datetime, timezone
from functools import wraps

from flask import (abort, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from app import Media, db
from teams import perms
from teams.models import log

from dialer import bp, readiness, wizard
from dialer.models import (AiAgent, Call, Campaign, PhoneNumber, Playbook,
                           VoicemailDrop)
from dialer.providers import registry
from dialer.settings_store import get_settings


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require(perm):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if not perms.can(getattr(g, "member", None), perm):
                return render_template("teams/denied.html", perm=perm), 403
            return fn(*a, **kw)
        return wrapped
    return deco


def ctx():
    """Everything a dialer template needs about the account's state."""
    s = get_settings(g.account_id)
    return s, readiness.check(s, g.account_id), wizard.progress(s, g.account_id)


# ------------------------------------------------------------------ home
@bp.route("/")
def home():
    s, ready, prog = ctx()
    recent = (Call.query.filter_by(account_id=g.account_id)
              .order_by(Call.started_at.desc()).limit(8).all())
    campaigns = (Campaign.query.filter_by(account_id=g.account_id)
                 .filter(Campaign.status.in_(["running", "paused"]))
                 .order_by(Campaign.started_at.desc()).all())
    today = _now().date()
    todays = [c for c in Call.query.filter_by(account_id=g.account_id).all()
              if c.started_at and c.started_at.date() == today]
    stats = {
        "dials": len(todays),
        "connects": sum(1 for c in todays if c.answered_live),
        "talk": sum(c.duration_s or 0 for c in todays),
        "meetings": sum(1 for c in todays
                        if c.disposition in ("meeting_set", "qualified")),
    }
    return render_template("dialer/home.html", s=s, ready=ready, prog=prog,
                           recent=recent, campaigns=campaigns, stats=stats,
                           steps=wizard.STEPS)


# ----------------------------------------------------------------- wizard
@bp.route("/setup")
@bp.route("/setup/<int:step>")
def setup(step=None):
    s, ready, prog = ctx()
    if step is None:
        nxt = prog["next"]
        step = nxt["n"] if nxt else 1
    current = wizard.BY_N.get(step)
    if not current:
        abort(404)
    data = _step_data(current["key"], s)
    return render_template(f"dialer/setup/{current['key']}.html",
                           s=s, ready=ready, prog=prog, steps=wizard.STEPS,
                           step=current, status=prog["status"], **data)


def _step_data(key, s):
    """Extra context a given step needs."""
    acct = g.account_id
    if key == "numbers":
        return {"numbers": PhoneNumber.query.filter_by(account_id=acct)
                .order_by(PhoneNumber.pool, PhoneNumber.e164).all()}
    if key == "elevenlabs":
        voices = []
        if s.has_elevenlabs or registry.simulating(s):
            r = registry.voice_agent(s).list_voices()
            voices = r.get("voices", []) if r.get("ok") else []
        return {"voices": voices}
    if key == "voice":
        voices = []
        if s.has_elevenlabs or registry.simulating(s):
            r = registry.voice_agent(s).list_voices()
            voices = r.get("voices", []) if r.get("ok") else []
        return {"voices": voices,
                "numbers": PhoneNumber.query.filter_by(account_id=acct).all()}
    if key == "playbook":
        return {"playbooks": Playbook.query.filter_by(account_id=acct).all()}
    if key == "voicemail":
        return {"drops": VoicemailDrop.query.filter_by(account_id=acct).all()}
    if key == "compliance":
        from dialer.models import StateRule
        return {"states": StateRule.query.order_by(StateRule.state_code).all()}
    if key == "test":
        return {"agents": AiAgent.query.filter_by(account_id=acct).all(),
                "numbers": PhoneNumber.query.filter_by(account_id=acct).all()}
    return {}


@bp.route("/setup/<key>/save", methods=["POST"])
@require("dialer.settings")
def setup_save(key):
    s = get_settings(g.account_id)
    f = request.form

    if key == "intent":
        s.intent = f.get("intent", "")
        wizard.mark(s, "intent", done=True)
    elif key == "compliance":
        s.recording_enabled = bool(f.get("recording_enabled"))
        s.recording_announce = bool(f.get("recording_announce"))
        s.announce_text = (f.get("announce_text") or "").strip()[:400]
        s.announce_mode = f.get("announce_mode", "proceed")
        s.ai_disclosure_enabled = bool(f.get("ai_disclosure_enabled"))
        s.ai_disclosure_name = (f.get("ai_disclosure_name") or "").strip()[:160]
        s.ai_callback_number = (f.get("ai_callback_number") or "").strip()[:32]
        s.window_start = f.get("window_start") or "09:00"
        s.window_end = f.get("window_end") or "19:00"
        s.window_days = ",".join(f.getlist("window_days")) or "1,2,3,4,5,6"
        s.smart_window = bool(f.get("smart_window"))
        s.enforce_window = bool(f.get("enforce_window"))
        s.honor_state_rules = bool(f.get("honor_state_rules"))
        s.honor_national_dnc = bool(f.get("honor_national_dnc"))
        s.retention_days = f.get("retention_days", type=int) or 90
        wizard.mark(s, "compliance", done=True)
    elif key == "voice":
        s.elevenlabs_default_voice_id = f.get("voice_id", "")
        s.max_call_seconds = f.get("max_call_seconds", type=int) or 600
        s.idle_hangup_seconds = f.get("idle_hangup_seconds", type=int) or None
        s.rep_idle_teardown_seconds = f.get("rep_idle_teardown_seconds",
                                            type=int) or 300
        s.background_noise = bool(f.get("background_noise"))
        s.background_preset = f.get("background_preset", "office1")
        s.transfer_mode = f.get("transfer_mode", "browser")
        s.transfer_number = (f.get("transfer_number") or "").strip()[:32]
        s.amd_default = bool(f.get("amd_default"))
        s.live_transcription = bool(f.get("live_transcription"))
        wizard.mark(s, "voice", done=True)
    elif key == "skip":
        wizard.mark(s, f.get("step", ""), skipped=True)
        db.session.commit()
        return redirect(url_for("dialer.setup"))
    else:
        abort(404)

    db.session.commit()
    flash("Saved.")
    nxt = wizard.progress(s, g.account_id)["next"]
    return redirect(url_for("dialer.setup", step=nxt["n"]) if nxt
                    else url_for("dialer.setup"))


# ------------------------------------------------------------ vendor keys
@bp.route("/setup/keys/<vendor>", methods=["POST"])
@require("dialer.keys")
def save_keys(vendor):
    s = get_settings(g.account_id)
    f = request.form
    if vendor == "twilio":
        sid = (f.get("account_sid") or "").strip()
        token = (f.get("auth_token") or "").strip()
        if sid:
            s.set_secret("twilio_account_sid", sid, "twilio_sid_last4")
        if token:
            s.set_secret("twilio_auth_token", token)
        s.twilio_verified_at = None
    elif vendor == "elevenlabs":
        key = (f.get("api_key") or "").strip()
        if key:
            s.set_secret("elevenlabs_key", key, "elevenlabs_last4")
        s.elevenlabs_verified_at = None
    elif vendor == "llm":
        key = (f.get("api_key") or "").strip()
        s.llm_provider = f.get("provider", "openai")
        if f.get("model"):
            s.llm_model = f.get("model")[:60]
        if key:
            s.set_secret("llm_key", key, "llm_last4")
        s.llm_verified_at = None
    else:
        abort(404)
    log(f"keys.{vendor}", target=vendor, detail="key saved",
        account_id=g.account_id, user=g.member)
    db.session.commit()
    return _test_vendor(vendor, s, redirect_after=True)


@bp.route("/setup/test/<vendor>", methods=["POST"])
@require("dialer.keys")
def test_vendor(vendor):
    return _test_vendor(vendor, get_settings(g.account_id), redirect_after=True)


def _test_vendor(vendor, s, redirect_after=False):
    """Actually call the vendor. A step is only 'done' because this passed."""
    step = {"twilio": 2, "elevenlabs": 6, "llm": 5}.get(vendor, 2)
    if vendor == "twilio":
        r = registry.telephony(s).verify()
        if r.get("ok"):
            s.twilio_verified_at = _now()
            s.twilio_verify_error = ""
            s.twilio_balance = str(r.get("balance", ""))[:32]
            s.twilio_is_trial = bool(r.get("is_trial"))
            pcp = registry.telephony(s).customer_profiles()
            if pcp.get("ok"):
                s.twilio_pcp_status = pcp.get("status", "none")
                s.twilio_pcp_checked_at = _now()
            _ensure_twilio_objects(s)
            flash(f"Twilio connected — {r.get('account_name', 'account')}"
                  + (f", balance ${r.get('balance')}" if r.get("balance") else ""))
        else:
            s.twilio_verify_error = r.get("error", "")[:300]
            flash(f"Twilio didn't accept that: {r.get('error')}", "error")
    elif vendor == "elevenlabs":
        va = registry.voice_agent(s)
        r = va.verify()
        if r.get("ok"):
            s.elevenlabs_verified_at = _now()
            s.elevenlabs_verify_error = ""
            s.elevenlabs_tier = str(r.get("tier", ""))[:32]
            s.elevenlabs_concurrency = int(r.get("concurrency") or 0)
            # the post-call webhook is created FIRST, so an under-privileged
            # key fails here rather than three steps later
            if not s.elevenlabs_webhook_id:
                from dialer import urls as _u
                w = va.ensure_webhook(_u.elevenlabs_post_call(),
                                      "60MS HQ post-call")
                if w.get("ok"):
                    s.elevenlabs_webhook_id = w.get("webhook_id", "")[:64]
                    s.set_secret("elevenlabs_webhook_secret", w.get("secret"))
                else:
                    flash("Connected, but we couldn't create the results "
                          f"webhook: {w.get('error')}. Use a key made by the "
                          "workspace owner or an admin.", "error")
            flash(f"ElevenLabs connected — {s.elevenlabs_tier} plan, "
                  f"{s.elevenlabs_concurrency} calls at once.")
        else:
            s.elevenlabs_verify_error = r.get("error", "")[:300]
            flash(f"ElevenLabs didn't accept that: {r.get('error')}", "error")
    elif vendor == "llm":
        r = registry.llm(s).verify()
        if r.get("ok"):
            s.llm_verified_at = _now()
            s.llm_verify_error = ""
            flash("AI key works — transcripts, summaries and scoring are on.")
        else:
            s.llm_verify_error = r.get("error", "")[:300]
            flash(f"That key didn't work: {r.get('error')}", "error")
    db.session.commit()
    if redirect_after:
        return redirect(url_for("dialer.setup", step=step))
    return None


def _ensure_twilio_objects(s):
    """A TwiML app and an API key, created once, so the browser phone works."""
    tel = registry.telephony(s)
    if not s.twilio_twiml_app_sid:
        from dialer import urls as _u
        r = tel.ensure_twiml_app(_u.twilio_outgoing(g.account_id),
                                 "60MS HQ Dialer")
        if r.get("ok"):
            s.twilio_twiml_app_sid = r.get("sid", "")[:64]
    if not s.twilio_api_key_sid_enc:
        r = tel.ensure_api_key("60MS HQ Dialer")
        if r.get("ok"):
            s.set_secret("twilio_api_key_sid", r.get("sid"))
            s.set_secret("twilio_api_key_secret", r.get("secret"))


@bp.route("/setup/business/recheck", methods=["POST"])
@require("dialer.settings")
def recheck_business():
    s = get_settings(g.account_id)
    r = registry.telephony(s).customer_profiles()
    if r.get("ok"):
        s.twilio_pcp_status = r.get("status", "none")
        s.twilio_pcp_checked_at = _now()
        db.session.commit()
        flash({"business": "Approved — you're on full throughput.",
               "individual": "Twilio approved an Individual profile. That caps "
                             "you at 3 calls at once; re-register as a business.",
               "pending": "Still in review with Twilio.",
               "none": "Twilio has no profile for this account yet."}.get(
                   s.twilio_pcp_status, "Checked."))
    else:
        flash(f"Couldn't reach Twilio: {r.get('error')}", "error")
    return redirect(url_for("dialer.setup", step=3))
