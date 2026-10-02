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


# ElevenLabs' own category names, in words a customer recognises. "premade"
# and "professional" both mean a voice ElevenLabs supplies; what a buyer
# actually cares about is whether anyone else calling the same list could be
# using it too.
VOICE_KINDS = {
    "premade": "Stock",
    "professional": "Stock, premium",
    "high_quality": "Stock, premium",
    "famous": "Stock, famous",
    "cloned": "Yours",
    "generated": "Yours, generated",
}


@bp.app_context_processor
def _dialer_globals():
    """DISPOSITIONS and its label/icon/hotkey maps, available to every
    template, so nothing has to mirror the list in Jinja."""
    from dialer.models import (DISPOSITION_HOTKEYS, DISPOSITION_ICONS,
                               DISPOSITION_LABELS, DISPOSITIONS)
    return {"VOICE_KINDS": VOICE_KINDS,
            "DISPOSITIONS": DISPOSITIONS,
            "DISPOSITION_LABELS": DISPOSITION_LABELS,
            "DISPOSITION_ICONS": DISPOSITION_ICONS,
            "DISPOSITION_HOTKEYS": DISPOSITION_HOTKEYS}


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
    from dialer.demo import demo_present
    return render_template("dialer/home.html", s=s, ready=ready, prog=prog,
                           recent=recent, campaigns=campaigns, stats=stats,
                           steps=wizard.STEPS, demo=demo_present(g.account_id))


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
        from dialer.demo import DEMO_PREFIX
        rows = Playbook.query.filter_by(account_id=acct).all()
        # The wizard counts only playbooks the customer wrote, so the page
        # has to draw the same line or it says "1" beside a step that will
        # not go green and explains nothing.
        return {"playbooks": rows,
                "real_playbooks": [p for p in rows
                                   if not p.name.startswith(DEMO_PREFIX)],
                "DEMO_PREFIX": DEMO_PREFIX}
    if key == "voicemail":
        drops = VoicemailDrop.query.filter_by(account_id=acct).all()
        if _repair_voicemail_defaults(acct, drops):
            drops = VoicemailDrop.query.filter_by(account_id=acct).all()
        return {"drops": drops}
    if key == "compliance":
        from dialer.models import StateRule
        return {"states": StateRule.query.order_by(StateRule.state_code).all()}
    if key == "test":
        rows = PhoneNumber.query.filter_by(account_id=acct,
                                           state="active").all()
        # A sample number cannot place a real call, and listing it as one of
        # the numbers "it will call from" is how a test call went out on
        # +18655550101 and came back with Twilio error 21210.
        return {"agents": AiAgent.query.filter_by(account_id=acct).all(),
                "numbers": [n for n in rows if not n.is_placeholder],
                "fake_numbers": [n for n in rows if n.is_placeholder]}
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
@bp.route("/setup/reset", methods=["POST"])
@require("dialer.settings")
def setup_reset():
    """Clear the ticks this account has marked by hand.

    Only the hand-marked steps are stored at all -- the rest are derived from
    what is actually connected, so they cannot be reset, only disconnected.
    """
    s = get_settings(g.account_id)
    s.set_wizard({})
    s.intent = ""          # also a hand-made choice, not a connection
    log("dialer.setup_reset", account_id=g.account_id, user=g.member)
    db.session.commit()
    flash("Setup progress cleared. The steps that depend on a real connection "
          "still read from that connection.")
    return redirect(url_for("dialer.setup", step=1))


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
                _make_elevenlabs_webhook(s, va)
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
               "unknown": "Twilio approved a profile but didn't say which "
                          "type. Check it on Twilio's page — if it says "
                          "Business you're fine.",
               "pending": "Still in review with Twilio.",
               "none": "Twilio has no profile for this account yet."}.get(
                   s.twilio_pcp_status, "Checked."))
    else:
        flash(f"Couldn't reach Twilio: {r.get('error')}", "error")
    return redirect(url_for("dialer.setup", step=3))


# ---------------------------------------------------------------- numbers
@bp.route("/numbers")
@require("dialer.settings")
def numbers():
    s, ready, prog = ctx()
    rows = (PhoneNumber.query.filter_by(account_id=g.account_id)
            .order_by(PhoneNumber.pool, PhoneNumber.e164).all())
    _backfill_regions(rows)
    return render_template(
        "dialer/numbers.html", s=s, ready=ready, prog=prog,
        numbers=rows, results=[], q=request.args.get("area_code", ""))


def _backfill_regions(rows):
    """Fill in a state we could not name when the number was bought.

    The state table used to cover only the twenty states that had a calling
    rule, so a number bought in any other one stored an empty region and the
    page showed a bare area code where its state belongs. The table is
    complete now, but rows written before that keep the blank. Rather than a
    migration for two rows, each page view repairs what it is already looking
    at, and once repaired it never writes again.
    """
    from dialer import tz
    changed = False
    for n in rows:
        if n.region:
            continue
        state = tz.state_for(n.e164)
        if state:
            n.region = state
            changed = True
    if changed:
        db.session.commit()


@bp.route("/numbers/search")
@require("dialer.settings")
def numbers_search():
    s, ready, prog = ctx()
    area = (request.args.get("area_code") or "").strip()
    r = registry.telephony(s).search_numbers(area_code=area, limit=8)
    if not r.get("ok"):
        flash(f"Couldn't search Twilio: {r.get('error')}", "error")
    return render_template(
        "dialer/numbers.html", s=s, ready=ready, prog=prog,
        numbers=PhoneNumber.query.filter_by(account_id=g.account_id).all(),
        results=r.get("numbers", []), q=area)


@bp.route("/numbers/buy", methods=["POST"])
@require("dialer.settings")
def numbers_buy():
    from dialer import tz, urls
    s = get_settings(g.account_id)
    e164 = (request.form.get("e164") or "").strip()
    pool = request.form.get("pool", "rep")
    r = registry.telephony(s).buy_number(
        e164, urls.twilio_voice(g.account_id), urls.twilio_status(g.account_id))
    if not r.get("ok"):
        flash(f"Twilio wouldn't sell us that number: {r.get('error')}", "error")
        return redirect(url_for("dialer.numbers"))
    n = PhoneNumber(account_id=g.account_id, e164=r.get("e164", e164),
                    twilio_sid=r.get("sid", ""), pool=pool, state="active",
                    area_code=tz.area_code(e164),
                    region=tz.state_for(e164), friendly_name=e164)
    db.session.add(n)
    db.session.flush()
    if pool == "ai":
        _link_number_to_elevenlabs(s, n)
    log("numbers.buy", target=e164, detail=f"pool={pool}",
        account_id=g.account_id, user=g.member)
    db.session.commit()
    flash(f"{n.pretty} is yours. It costs $1.15 a month.")
    return redirect(url_for("dialer.numbers"))


@bp.route("/numbers/import", methods=["POST"])
@require("dialer.settings")
def numbers_import():
    from dialer import tz
    s = get_settings(g.account_id)
    r = registry.telephony(s).list_numbers()
    if not r.get("ok"):
        flash(f"Couldn't read your Twilio numbers: {r.get('error')}", "error")
        return redirect(url_for("dialer.numbers"))
    have = {n.e164 for n in PhoneNumber.query.filter_by(account_id=g.account_id)}
    added = 0
    for item in r.get("numbers", []):
        if item["e164"] in have:
            continue
        db.session.add(PhoneNumber(
            account_id=g.account_id, e164=item["e164"],
            twilio_sid=item.get("sid", ""), pool="rep", state="active",
            friendly_name=item.get("friendly_name", ""),
            area_code=tz.area_code(item["e164"]),
            region=item.get("region", "")))
        added += 1
    db.session.commit()
    flash(f"Brought in {added} number(s) from Twilio." if added
          else "Every number on your Twilio account is already here.")
    return redirect(url_for("dialer.numbers"))


@bp.route("/numbers/<int:number_id>/<action>", methods=["POST"])
@require("dialer.settings")
def number_action(number_id, action):
    s = get_settings(g.account_id)
    n = PhoneNumber.query.get_or_404(number_id)
    if n.account_id != g.account_id:
        abort(403)
    if action == "pool":
        n.pool = request.form.get("pool", "rep")
        if n.pool == "ai":
            _link_number_to_elevenlabs(s, n)
        flash(f"{n.pretty} is now in the {n.pool} pool.")
    elif action == "cap":
        n.daily_cap = max(1, min(request.form.get("daily_cap", type=int) or 120,
                                 1000))
        flash(f"{n.pretty} is capped at {n.daily_cap} calls a day.")
    elif action == "park":
        n.state = "parked"
        flash(f"{n.pretty} is parked. It still answers, so anyone who calls "
              f"back reaches you, but nothing new dials out from it.")
    elif action == "unpark":
        n.state = "active"
    elif action == "name":
        # A number people have to choose between needs a name they chose.
        # Twilio's own label is the number again, which tells you nothing
        # about which line is the AI and which one a human picks up.
        label = (request.form.get("friendly_name") or "").strip()[:120]
        n.friendly_name = label
        flash(f"{n.pretty} is now called \u201c{label}\u201d." if label
              else f"{n.pretty} has no label now.")
    elif action == "release":
        # People you have already called have this number in their phone.
        if n.first_outbound_at and request.form.get("confirm") != "yes":
            flash("That number has made outbound calls. Releasing it hands it "
                  "to a stranger and sends your callbacks to them. Park it "
                  "instead, or tick the confirmation.", "error")
            return redirect(url_for("dialer.numbers"))
        # A sample number was never bought, so there is nothing at Twilio to
        # give back. Asking Twilio to release a SID it has never issued fails,
        # which is how demo rows became impossible to remove: the error looked
        # like a billing problem and the row stayed put forever.
        if _is_local_only(n):
            db.session.delete(n)
            db.session.commit()
            flash(f"{n.pretty} removed. It was sample data, so nothing was "
                  f"released at Twilio and nothing was refunded or charged.")
            return redirect(url_for("dialer.numbers"))
        r = registry.telephony(s).release_number(n.twilio_sid)
        if not r.get("ok"):
            flash(f"Twilio wouldn't release it: {r.get('error')}", "error")
            return redirect(url_for("dialer.numbers"))
        n.state = "released"
        log("numbers.release", target=n.e164, account_id=g.account_id,
            user=g.member)
        flash(f"{n.pretty} released.")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("dialer.numbers"))


def _is_local_only(number):
    """True when this row has no real number behind it at Twilio.

    Thin wrapper over the model property so there is one definition; a
    renamed sample number is still recognised because the test is the SID's
    shape, not the name.
    """
    return bool(number.is_placeholder)


def _link_number_to_elevenlabs(s, number):
    """An AI-pool number has to exist inside ElevenLabs before an agent can
    dial from it."""
    if number.elevenlabs_phone_id or not (s.has_elevenlabs
                                          or registry.simulating(s)):
        return
    sid = s.secret("twilio_api_key_sid") or s.secret("twilio_account_sid")
    token = (s.secret("twilio_api_key_secret") or s.secret("twilio_auth_token"))
    r = registry.voice_agent(s).import_number(
        number.e164, sid, token, label=number.friendly_name or number.e164,
        account_auth_token=s.secret("twilio_auth_token"))
    if r.get("ok"):
        number.elevenlabs_phone_id = (r.get("phone_number_id") or "")[:64]
    else:
        flash(f"The number is yours, but ElevenLabs wouldn't take it: "
              f"{r.get('error')}", "error")


# -------------------------------------------------------------- voicemail
@bp.route("/vm/<int:drop_id>")
def voicemail_media(drop_id):
    """Served unauthenticated so Twilio can fetch it, but the id is opaque and
    the file is a recording the account made for exactly this purpose."""
    from flask import Response
    drop = VoicemailDrop.query.get_or_404(drop_id)
    media = db.session.get(Media, drop.media_id) if drop.media_id else None
    if media is None:
        abort(404)
    return Response(media.data, mimetype=media.mimetype or "audio/wav")


def _wav_seconds(data):
    """Length of a PCM WAV, read off its own header.

    The browser encodes to WAV before uploading, so this covers every
    recording made in the app. An uploaded mp3 returns None and the row shows
    a dash, which is honest; guessing at a length is worse than not showing
    one.
    """
    try:
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        import struct
        rate = struct.unpack("<I", data[24:28])[0]
        byte_rate = struct.unpack("<I", data[28:32])[0]
        if not byte_rate or not rate:
            return None
        return round(max(0, len(data) - 44) / float(byte_rate), 1) or None
    except Exception:
        return None


def _only_one_default(account_id, keep_id):
    """Exactly one message can be the one reps drop.

    Two rows both reading "Reps drop this one" is not a cosmetic problem: the
    campaign picks whichever the query returns first, so the label stops
    predicting what will actually play.
    """
    for row in VoicemailDrop.query.filter_by(account_id=account_id):
        row.is_default = (row.id == keep_id)


def _repair_voicemail_defaults(account_id, drops):
    """Move the default off a message that cannot be played, and off the
    extras if more than one claims it.

    Needed because the sample drop shipped marked default before anyone knew
    it would never have audio, and that row is already sitting in live
    accounts. Repairs on sight rather than needing a migration.
    """
    playable = [d for d in drops if d.media_id]
    flagged = [d for d in drops if d.is_default]
    broken = any(d for d in flagged if not d.media_id) or len(flagged) > 1
    if not broken:
        return False
    keep = next((d for d in flagged if d.media_id), None) or (
        playable[0] if playable else None)
    for d in drops:
        d.is_default = bool(keep and d.id == keep.id)
    db.session.commit()
    return True


@bp.route("/voicemail/new", methods=["POST"])
@require("playbooks.edit")
def voicemail_new():
    # The name is optional now, so an unnamed one still has to be tellable
    # apart from the next unnamed one.
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        n = VoicemailDrop.query.filter_by(account_id=g.account_id).count() + 1
        name = "Voicemail" if n == 1 else f"Voicemail {n}"
    f = request.files.get("audio")
    if f is None or not f.filename:
        flash("No recording came through — try again.", "error")
        return redirect(url_for("dialer.setup", step=10))
    data = f.read()
    if len(data) > 8 * 1024 * 1024:
        flash("That recording is too big. Keep it under 20 seconds.", "error")
        return redirect(url_for("dialer.setup", step=10))
    # Browsers hand back "video/webm" for a microphone recording, and an
    # <audio> element will not play a video type, so the drop looked saved
    # and silently refused to play back.
    mimetype = (f.mimetype or "").strip() or "audio/wav"
    if mimetype.startswith("video/"):
        mimetype = "audio/" + mimetype.split("/", 1)[1]
    media = Media(owner_id=g.account_id, filename=f.filename,
                  mimetype=mimetype, data=data)
    seconds = _wav_seconds(data)
    db.session.add(media)
    db.session.flush()
    # First one that can actually PLAY becomes the default. Counting rows
    # would hand the default to the sample, which has no audio.
    first = VoicemailDrop.query.filter_by(
        account_id=g.account_id).filter(
        VoicemailDrop.media_id.isnot(None)).count() == 0
    drop = VoicemailDrop(
        account_id=g.account_id, name=name, media_id=media.id,
        mimetype=media.mimetype, duration_s=seconds, is_default=first,
        transcript=(request.form.get("transcript") or "")[:2000])
    db.session.add(drop)
    db.session.flush()
    if first:
        _only_one_default(g.account_id, drop.id)
    db.session.commit()
    flash(f"“{name}” saved. Your reps can drop it with one click.")
    return redirect(url_for("dialer.setup", step=10))


@bp.route("/voicemail/<int:drop_id>/speak", methods=["POST"])
@require("playbooks.edit")
def voicemail_speak(drop_id):
    """Turn a written sample into audio you can listen to.

    Mostly so the sample stops being a wall of text you have to imagine. It
    saves as its own message, so if you like it you can use it, and the page
    still says a real voice does better.
    """
    src = VoicemailDrop.query.get_or_404(drop_id)
    if src.account_id != g.account_id:
        abort(403)
    s = get_settings(g.account_id)
    text = (src.transcript or "").strip()
    if not text:
        flash("There is no wording on that one to read out.", "error")
        return redirect(url_for("dialer.setup", step=10))
    if not (s.has_elevenlabs or registry.simulating(s)):
        flash("Connect ElevenLabs on step 6 first — that is what speaks it.",
              "error")
        return redirect(url_for("dialer.setup", step=10))

    r = registry.voice_agent(s).speak(text, s.elevenlabs_default_voice_id or "")
    if not r.get("ok"):
        flash(f"ElevenLabs could not read that: {r.get('error')}", "error")
        return redirect(url_for("dialer.setup", step=10))

    audio = r["audio"]
    media = Media(owner_id=g.account_id, filename="voicemail-ai.mp3",
                  mimetype=r.get("mimetype") or "audio/mpeg", data=audio)
    db.session.add(media)
    db.session.flush()
    drop = VoicemailDrop(
        account_id=g.account_id, name="AI voice: " + src.name[:100],
        media_id=media.id, mimetype=media.mimetype,
        duration_s=_wav_seconds(audio), is_default=False, transcript=text)
    db.session.add(drop)
    log("voicemail.speak", target=drop.name, account_id=g.account_id,
        user=g.member)
    db.session.commit()
    flash("Read out and saved as its own message. Have a listen — if you want "
          "reps to use it, press “Use this one”. A real voice still does "
          "better on a first call.", "sticky")
    return redirect(url_for("dialer.setup", step=10))


@bp.route("/voicemail/<int:drop_id>/default", methods=["POST"])
@require("playbooks.edit")
def voicemail_default(drop_id):
    """Choose which message a rep's one click actually sends.

    There was no way to pick, so whichever row happened to be created first
    was the one every campaign used, for ever.
    """
    drop = VoicemailDrop.query.get_or_404(drop_id)
    if drop.account_id != g.account_id:
        abort(403)
    if not drop.media_id:
        flash("That one has no audio behind it, so it cannot be the default "
              "— a rep would press the button and send silence.", "error")
        return redirect(url_for("dialer.setup", step=10))
    for other in VoicemailDrop.query.filter_by(account_id=g.account_id):
        other.is_default = (other.id == drop.id)
    db.session.commit()
    flash(f"“{drop.name}” is the one your reps will drop.")
    return redirect(url_for("dialer.setup", step=10))


@bp.route("/voicemail/<int:drop_id>/delete", methods=["POST"])
@require("playbooks.edit")
def voicemail_delete(drop_id):
    drop = VoicemailDrop.query.get_or_404(drop_id)
    if drop.account_id != g.account_id:
        abort(403)
    if drop.media_id:
        media = db.session.get(Media, drop.media_id)
        if media:
            db.session.delete(media)
    db.session.delete(drop)
    db.session.commit()
    flash("Recording deleted.")
    return redirect(url_for("dialer.setup", step=10))


# -------------------------------------------------------------- playbooks
DEFAULT_PLAYBOOK = {
    "steps": [
        {"title": "Opening", "say": "Hi, this is {rep} with {company}. Is the "
         "owner or manager around?", "goal": "Reach the decision maker"},
        {"title": "Who you are", "say": "We supply bars and restaurants with "
         "free napkins. They carry a small ad, so they cost you nothing.",
         "goal": "Explain in one line, then stop talking"},
        {"title": "Permission", "say": "I've got two quick questions to see if "
         "there's any fit — if there isn't I'll get out of your hair.",
         "goal": "Lower the guard"},
        {"title": "Qualify", "say": "Ask the qualifying questions in order.",
         "goal": "Disqualify cheaply, qualify properly"},
        {"title": "Close", "say": "This sounds like a fit. Let me get you over "
         "to the person who sets it up.", "goal": "Transfer or book"},
        {"title": "Log it", "say": "Set the outcome and the next step before "
         "the next dial.", "goal": "Nothing is left in your head"},
    ],
    "questions": [
        {"question": "Who handles your napkin and paper-goods orders?",
         "collect_as": "decision_maker", "disqualify_if": ""},
        {"question": "Roughly how many tables do you run?",
         "collect_as": "tables", "disqualify_if": ""},
        {"question": "How many cases of napkins do you go through in a week?",
         "collect_as": "napkin_volume", "disqualify_if": ""},
        {"question": "Who supplies them today, and is anything not working "
         "about it?", "collect_as": "current_supplier", "disqualify_if": ""},
    ],
    "objections": [
        {"trigger_phrases": ["not interested", "no thanks"],
         "response": "Fair enough. Can I ask — is that because you're happy "
                     "with your current supplier, or because free sounds like "
                     "a catch?"},
        {"trigger_phrases": ["what's the catch", "nothing is free"],
         "response": "There's an ad printed on the napkin. That's the whole "
                     "catch. The advertiser pays, you stop buying napkins."},
        {"trigger_phrases": ["we have a supplier", "already buy"],
         "response": "Most places your size do. We're not replacing them — "
                     "we're replacing the line item."},
        {"trigger_phrases": ["send me an email", "send information"],
         "response": "Happy to. What's the best address? And so I send "
                     "something useful rather than a brochure, can I ask you "
                     "two quick things?"},
        {"trigger_phrases": ["busy", "bad time", "in the middle of"],
         "response": "Totally understand. Is later this afternoon better, or "
                     "tomorrow morning?"},
    ],
    "transfer_criteria": "Transfer when you have a decision maker who buys "
                         "napkins, runs at least 20 tables, and has not said "
                         "no twice.",
    "never_do": "Never quote a price or a contract length. Never promise the "
                "venue money. Never claim to be a person. If they ask to be "
                "removed, record it and end the call politely.",
}


# The lane most people actually want: the AI establishes whether it has the
# decision maker, then puts a live person on the phone. Everything below is
# written as something a rep would really say.
QUALIFY_PLAYBOOK = {
    "steps": [
        {"title": "Open", "say": "Hi, this is an automated assistant calling "
         "on behalf of {company}. I'll be quick.",
         "goal": "Say who is calling, and that it is a machine"},
        {"title": "The offer in one line", "say": "{offer}",
         "goal": "Give them a reason to keep listening"},
        {"title": "The qualifying question", "say": "Would that be your call, "
         "or is there someone else I should be speaking to?",
         "goal": "Find out in one question whether this is the decision maker"},
        {"title": "If it is them", "say": "Perfect. Let me put you straight "
         "through to a colleague who can set it up — one moment.",
         "goal": "Transfer immediately, while they are interested"},
        {"title": "If it is not them", "say": "No problem at all. Who would I "
         "need to speak to, and when are they usually around?",
         "goal": "Get the name and a time, then end politely"},
        {"title": "Close", "say": "That's all I needed. Thanks for your time.",
         "goal": "Leave them in a good mood either way"},
    ],
    "questions": [
        {"question": "Are you the person who would decide on something like this?",
         "collect_as": "is_decision_maker",
         "disqualify_if": "they are clearly not interested at all"},
        {"question": "If not you, who is, and when are they usually in?",
         "collect_as": "right_person", "disqualify_if": ""},
        {"question": "What is the best direct number or email for them?",
         "collect_as": "right_person_contact", "disqualify_if": ""},
    ],
    "objections": [
        {"trigger_phrases": ["what's the catch", "nothing is free", "too good"],
         "response": "Fair question. The napkins carry a small ad, and the "
                     "advertiser pays for all of it. That's the whole catch."},
        {"trigger_phrases": ["not interested", "no thanks", "we're all set"],
         "response": "Understood. Before I let you go — is that a no to the "
                     "napkins, or a no to talking today?"},
        {"trigger_phrases": ["send me an email", "send information"],
         "response": "Happy to. What's the best address? And while I have you, "
                     "are you the one who'd decide on it?"},
        {"trigger_phrases": ["who is this", "what is this about", "are you a robot"],
         "response": "I'm an automated assistant calling for {company}. A real "
                     "person takes over the moment this looks like a fit."},
        {"trigger_phrases": ["busy", "bad time", "in the middle of"],
         "response": "Of course. Is there a better time this week, and are you "
                     "the right person for me to call back?"},
    ],
    "transfer_criteria": (
        "Transfer as soon as the person confirms they are the one who would "
        "decide, or says they are interested and wants details. Do not keep "
        "selling once they say yes — say a colleague is coming on and "
        "transfer. If nobody is available to take it, say a person will call "
        "back today, book the follow-up and end the call."),
    "never_do": (
        "Never quote a contract, a term length or anything beyond the stated "
        "offer. Never claim to be a person. Never argue with a no. If they "
        "ask to be removed from the list, confirm it, record it and end the "
        "call."),
}


@bp.route("/presets/qualify-transfer", methods=["POST"])
@require("agents.edit")
def preset_qualify_transfer():
    """Build the whole qualify-and-transfer setup in one go: the script, the
    agent, and the hand-off target. Someone should not have to assemble this
    from four screens to get the thing they came for."""
    s = get_settings(g.account_id)
    company = (request.form.get("company") or s.ai_disclosure_name
               or "our company").strip()[:160]
    offer = (request.form.get("offer") or "").strip() or (
        "We supply bars and restaurants with free napkins that carry a QR "
        "code, and we pay you two hundred dollars plus drinks on us.")
    target = request.form.get("transfer_to", "available")   # available|number
    number = (request.form.get("transfer_number") or "").strip()

    pb = Playbook(
        account_id=g.account_id, name="Qualify and transfer",
        description="The AI checks it has the decision maker, then puts a "
                    "live person on the call.",
        is_default=Playbook.query.filter_by(account_id=g.account_id).count() == 0,
        steps_json=json.dumps([
            dict(x, say=x["say"].replace("{company}", company)
                 .replace("{offer}", offer))
            for x in QUALIFY_PLAYBOOK["steps"]]),
        questions_json=json.dumps(QUALIFY_PLAYBOOK["questions"]),
        objections_json=json.dumps([
            dict(o, response=o["response"].replace("{company}", company))
            for o in QUALIFY_PLAYBOOK["objections"]]),
        transfer_criteria=QUALIFY_PLAYBOOK["transfer_criteria"],
        never_do=QUALIFY_PLAYBOOK["never_do"])
    db.session.add(pb)
    db.session.flush()

    agent = AiAgent(
        account_id=g.account_id, name="Qualifier", direction="outbound",
        playbook_id=pb.id, voice_id=s.elevenlabs_default_voice_id or "",
        company_facts=f"{company}. {offer}",
        persona="Brief, warm and unbothered. You are not selling, you are "
                "finding out in under a minute whether this is the right "
                "person. If it is, you get a colleague on the line fast.",
        first_message=(f"Hi, this is an automated assistant calling on behalf "
                       f"of {company}. I'll be quick — {offer}"),
        transfer_rules=(
            "The moment they confirm they are the decision maker, or ask for "
            "details, use the transfer tool. Say: 'Perfect, let me put you "
            "straight through to a colleague.' Then transfer. If the transfer "
            "does not connect, apologise, take the best time to call back, "
            "and book it."),
        max_duration_seconds=240, active=True)
    db.session.add(agent)

    s.transfer_mode = "browser" if target == "available" else "number"
    if target == "number" and number:
        s.transfer_number = number[:32]
    if not s.ai_disclosure_name:
        s.ai_disclosure_name = company
    db.session.flush()

    from dialer.agents import sync_agent
    res = sync_agent(agent, s)
    log("dialer.preset_qualify", target=agent.name,
        detail=f"transfer={target}", account_id=g.account_id, user=g.member)
    db.session.commit()
    flash("Built it: a “Qualify and transfer” script and a “Qualifier” agent "
          + ("that hands the live call to whoever is on shift."
             if target == "available"
             else f"that hands the live call to {number}.")
          + (" Open it to change the wording." if res.get("ok")
             else f" ElevenLabs hasn't accepted it yet: {res.get('error')}"),
          None if res.get("ok") else "error")
    return redirect(url_for("dialer.agent_edit", agent_id=agent.id))


@bp.route("/playbooks")
@require("playbooks.edit")
def playbooks():
    s, ready, prog = ctx()
    return render_template(
        "dialer/playbooks.html", s=s, ready=ready, prog=prog,
        playbooks=Playbook.query.filter_by(account_id=g.account_id).all())


@bp.route("/playbooks/new", methods=["POST"])
@require("playbooks.edit")
def playbook_new():
    first = Playbook.query.filter_by(account_id=g.account_id).count() == 0
    pb = Playbook(
        account_id=g.account_id,
        name=(request.form.get("name") or "Cold call playbook")[:120],
        is_default=first,
        steps_json=json.dumps(DEFAULT_PLAYBOOK["steps"]),
        questions_json=json.dumps(DEFAULT_PLAYBOOK["questions"]),
        objections_json=json.dumps(DEFAULT_PLAYBOOK["objections"]),
        transfer_criteria=DEFAULT_PLAYBOOK["transfer_criteria"],
        never_do=DEFAULT_PLAYBOOK["never_do"])
    db.session.add(pb)
    db.session.commit()
    flash("Playbook created from the cold-call template. Edit it to match how "
          "you actually talk.")
    return redirect(url_for("dialer.playbook_edit", playbook_id=pb.id))


@bp.route("/playbooks/draft", methods=["POST"])
@require("playbooks.edit")
def playbook_draft():
    """Write a first draft from a sentence about the business.

    It lands in the editor unsaved-feeling and clearly labelled a draft,
    because a script nobody has read is worse than no script: the rep reads
    it live for the first time in front of a prospect.
    """
    from dialer import playbook_ai
    s = get_settings(g.account_id)
    brief = (request.form.get("brief") or "").strip()
    back = request.form.get("back") or url_for("dialer.setup", step=9)

    if not (s.has_llm or registry.simulating(s)):
        flash("Add your AI key on step 5 first — that is the key that writes "
              "this.", "error")
        return redirect(back)

    r = playbook_ai.draft(s, brief, company=s.ai_disclosure_name or "")
    if not r.get("ok"):
        flash(r.get("error") or "Could not write that one.", "error")
        return redirect(back)

    d = r["playbook"]
    pb = Playbook(
        account_id=g.account_id, name=d["name"][:120],
        description=d["description"][:300],
        is_default=Playbook.query.filter_by(account_id=g.account_id).count() == 0,
        steps_json=json.dumps(d["steps"]),
        questions_json=json.dumps(d["questions"]),
        objections_json=json.dumps(d["objections"]),
        transfer_criteria=d["transfer_criteria"],
        never_do=d["never_do"])
    db.session.add(pb)
    log("playbooks.draft", target=pb.name, detail=f"brief={len(brief)} chars",
        account_id=g.account_id, user=g.member)
    db.session.commit()
    flash("Draft written. Read every line out loud before you dial it — it "
          "guessed at your offer and it will have got something wrong.",
          "sticky")
    return redirect(url_for("dialer.playbook_edit", playbook_id=pb.id))


@bp.route("/playbooks/<int:playbook_id>", methods=["GET", "POST"])
@require("playbooks.edit")
def playbook_edit(playbook_id):
    s, ready, prog = ctx()
    pb = Playbook.query.get_or_404(playbook_id)
    if pb.account_id != g.account_id:
        abort(403)
    if request.method == "POST":
        pb.name = (request.form.get("name") or pb.name)[:120]
        pb.description = (request.form.get("description") or "")[:300]
        pb.transfer_criteria = request.form.get("transfer_criteria") or ""
        pb.never_do = request.form.get("never_do") or ""
        pb.steps_json = _rows(request.form, "step",
                              ["title", "say", "goal"])
        pb.questions_json = _rows(request.form, "question",
                                  ["question", "collect_as", "disqualify_if"])
        pb.objections_json = _rows(request.form, "objection",
                                   ["trigger", "response"], split="trigger")
        db.session.commit()
        flash("Playbook saved.")
        return redirect(url_for("dialer.playbook_edit", playbook_id=pb.id))
    return render_template("dialer/playbook_edit.html", s=s, ready=ready,
                           prog=prog, pb=pb)


def _rows(form, prefix, fields, split=None):
    """Collect repeated form rows (step-0-title, step-1-title, ...)."""
    out, i = [], 0
    while True:
        keys = [f"{prefix}-{i}-{f}" for f in fields]
        if not any(k in form for k in keys):
            break
        row = {}
        for f, k in zip(fields, keys):
            v = (form.get(k) or "").strip()
            if split and f == split:
                row["trigger_phrases"] = [x.strip() for x in v.split(",")
                                          if x.strip()]
            else:
                row[f] = v
        if any(v for v in row.values()):
            out.append(row)
        i += 1
    return json.dumps(out)


@bp.route("/playbooks/<int:playbook_id>/delete", methods=["POST"])
@require("playbooks.edit")
def playbook_delete(playbook_id):
    pb = Playbook.query.get_or_404(playbook_id)
    if pb.account_id != g.account_id:
        abort(403)
    db.session.delete(pb)
    db.session.commit()
    flash("Playbook deleted.")
    return redirect(url_for("dialer.playbooks"))


# ----------------------------------------------------------------- agents
@bp.route("/agents")
@require("agents.edit")
def agents():
    s, ready, prog = ctx()
    return render_template(
        "dialer/agents.html", s=s, ready=ready, prog=prog,
        agents=AiAgent.query.filter_by(account_id=g.account_id).all())


@bp.route("/agents/new", methods=["POST"])
@require("agents.edit")
def agent_new():
    s = get_settings(g.account_id)
    pb = Playbook.query.filter_by(account_id=g.account_id).first()
    direction = request.form.get("direction", "outbound")
    a = AiAgent(account_id=g.account_id,
                name=(request.form.get("name")
                      or f"{direction.title()} agent")[:120],
                direction=direction, playbook_id=pb.id if pb else None,
                voice_id=s.elevenlabs_default_voice_id or "",
                company_facts=s.ai_disclosure_name or "")
    db.session.add(a)
    db.session.commit()
    return redirect(url_for("dialer.agent_edit", agent_id=a.id))


@bp.route("/agents/<int:agent_id>", methods=["GET", "POST"])
@require("agents.edit")
def agent_edit(agent_id):
    from dialer.agents import build_prompt, sync_agent
    s, ready, prog = ctx()
    a = AiAgent.query.get_or_404(agent_id)
    if a.account_id != g.account_id:
        abort(403)
    if request.method == "POST":
        for field in ("name", "voice_id", "voice_name", "llm_model",
                      "first_message", "persona", "company_facts",
                      "knowledge_text", "transfer_rules", "voicemail_message",
                      "background_preset"):
            if field in request.form:
                setattr(a, field, request.form.get(field) or "")
        a.playbook_id = request.form.get("playbook_id", type=int) or None
        a.max_duration_seconds = request.form.get("max_duration_seconds",
                                                  type=int) or 420
        a.voicemail_behavior = request.form.get("voicemail_behavior",
                                                "leave_tts")
        a.dtmf_enabled = bool(request.form.get("dtmf_enabled"))
        a.active = bool(request.form.get("active"))
        db.session.commit()
        if request.form.get("sync"):
            res = sync_agent(a, s)
            flash("Agent synced to ElevenLabs." if res.get("ok")
                  else f"Saved here, but ElevenLabs rejected it: "
                       f"{res.get('error')}",
                  None if res.get("ok") else "error")
        else:
            flash("Agent saved.")
        return redirect(url_for("dialer.agent_edit", agent_id=a.id))

    voices = []
    if s.has_elevenlabs or registry.simulating(s):
        r = registry.voice_agent(s).list_voices()
        voices = r.get("voices", []) if r.get("ok") else []
    return render_template(
        "dialer/agent_edit.html", s=s, ready=ready, prog=prog, a=a,
        voices=voices,
        playbooks=Playbook.query.filter_by(account_id=g.account_id).all(),
        prompt_preview=build_prompt(a, s))


@bp.route("/agents/<int:agent_id>/delete", methods=["POST"])
@require("agents.edit")
def agent_delete(agent_id):
    a = AiAgent.query.get_or_404(agent_id)
    if a.account_id != g.account_id:
        abort(403)
    db.session.delete(a)
    db.session.commit()
    flash("Agent deleted.")
    return redirect(url_for("dialer.agents"))


# -------------------------------------------------------------- campaigns
@bp.route("/campaigns")
def campaigns_list():
    s, ready, prog = ctx()
    rows = (Campaign.query.filter_by(account_id=g.account_id)
            .order_by(Campaign.created_at.desc()).all())
    return render_template("dialer/campaigns.html", s=s, ready=ready,
                           prog=prog, campaigns=rows)


@bp.route("/campaigns/new", methods=["GET", "POST"])
@require("campaigns.manage")
def campaign_new():
    from dialer import campaigns as camp_mod
    from app import LEAD_STATUSES, Lead
    s, ready, prog = ctx()
    if request.method == "POST":
        seg = _segment_from_form(request.form)
        mode = request.form.get("mode", "power")
        c = Campaign(
            account_id=g.account_id,
            name=(request.form.get("name") or "New campaign")[:140],
            mode=mode, segment_json=json.dumps(seg),
            ai_agent_id=request.form.get("ai_agent_id", type=int) or None,
            playbook_id=request.form.get("playbook_id", type=int) or None,
            voicemail_drop_id=request.form.get("voicemail_drop_id",
                                               type=int) or None,
            number_pool="ai" if mode == "ai" else "rep",
            max_concurrent=max(1, min(request.form.get("max_concurrent",
                                                       type=int) or 1, 20)),
            amd_enabled=bool(request.form.get("amd_enabled")),
            created_by=getattr(g.member, "id", None), status="draft")
        db.session.add(c)
        db.session.commit()
        res = camp_mod.materialize(c, s)
        flash(f"“{c.name}” built with {res['added']} leads ready to call."
              + (f" {res['skipped']} had no usable phone number."
                 if res["skipped"] else ""))
        return redirect(url_for("dialer.campaign_detail", campaign_id=c.id))

    sources = [r[0] for r in db.session.query(Lead.source)
               .filter(Lead.owner_id == g.account_id).distinct() if r[0]]
    tags = sorted({t for (v,) in db.session.query(Lead.tags)
                   .filter(Lead.owner_id == g.account_id).distinct()
                   for t in (v or "").split(",") if t.strip()})
    return render_template(
        "dialer/campaign_new.html", s=s, ready=ready, prog=prog,
        statuses=LEAD_STATUSES, sources=sources, tags=tags,
        agents=AiAgent.query.filter_by(account_id=g.account_id, active=True).all(),
        playbooks=Playbook.query.filter_by(account_id=g.account_id).all(),
        drops=VoicemailDrop.query.filter_by(account_id=g.account_id).all(),
        preselected=request.args.getlist("lead_id", type=int))


def _segment_from_form(f):
    seg = {
        "statuses": f.getlist("statuses"),
        "sources": f.getlist("sources"),
        "tags": [t.strip() for t in (f.get("tags") or "").split(",") if t.strip()],
        "states": [x.strip().upper() for x in (f.get("states") or "").split(",")
                   if x.strip()],
        "area_codes": [x.strip() for x in (f.get("area_codes") or "").split(",")
                       if x.strip()],
        "business_type": (f.get("business_type") or "").strip(),
        "not_called_in_days": f.get("not_called_in_days", type=int) or None,
        "has_phone": True, "exclude_dnc": True,
    }
    ids = f.getlist("lead_id", type=int)
    if ids:
        seg["lead_ids"] = ids
    return {k: v for k, v in seg.items() if v not in ([], "", None)}


@bp.route("/campaigns/preview", methods=["POST"])
@require("campaigns.manage")
def campaign_preview():
    """Live count behind the segment builder, including how many the gate will
    actually let this mode dial."""
    from dialer import campaigns as camp_mod
    s = get_settings(g.account_id)
    seg = _segment_from_form(request.form)
    mode = {"power": "power", "ai": "ai_outbound",
            "voicemail": "voicemail"}.get(request.form.get("mode", "power"),
                                          "power")
    return jsonify(camp_mod.preview(g.account_id, seg, s, mode))


@bp.route("/campaigns/<int:campaign_id>")
def campaign_detail(campaign_id):
    s, ready, prog = ctx()
    c = Campaign.query.get_or_404(campaign_id)
    if c.account_id != g.account_id:
        abort(403)
    from dialer.models import CampaignLead
    rows = (CampaignLead.query.filter_by(campaign_id=c.id)
            .order_by(CampaignLead.position).limit(500).all())
    from app import Lead
    leads = {l.id: l for l in Lead.query.filter(
        Lead.id.in_([r.lead_id for r in rows]))} if rows else {}
    calls = (Call.query.filter_by(campaign_id=c.id)
             .order_by(Call.started_at.desc()).limit(100).all())
    return render_template("dialer/campaign_detail.html", s=s, ready=ready,
                           prog=prog, c=c, rows=rows, leads=leads, calls=calls,
                           agent=db.session.get(AiAgent, c.ai_agent_id)
                           if c.ai_agent_id else None)


@bp.route("/campaigns/<int:campaign_id>/<action>", methods=["POST"])
@require("campaigns.manage")
def campaign_action(campaign_id, action):
    from dialer import campaigns as camp_mod
    s = get_settings(g.account_id)
    c = Campaign.query.get_or_404(campaign_id)
    if c.account_id != g.account_id:
        abort(403)
    if action == "start":
        blocked = _mode_blocked(c, s)
        if blocked:
            flash(blocked, "error")
            return redirect(url_for("dialer.campaign_detail", campaign_id=c.id))
        c.status = "running"
        c.started_at = c.started_at or _now()
        c.paused_reason = ""
        flash(f"“{c.name}” is running."
              + (" Open the phone to start taking calls."
                 if c.mode == "power" else ""))
    elif action == "pause":
        c.status = "paused"
        flash("Paused. Nothing new will dial.")
    elif action == "stop":
        c.status, c.finished_at = "done", _now()
        from dialer.models import CampaignLead
        CampaignLead.query.filter_by(campaign_id=c.id).filter(
            CampaignLead.state.in_(["queued", "deferred", "claimed"])).update(
                {"state": "skipped", "skip_reason": "campaign stopped"},
                synchronize_session=False)
        flash("Stopped and the queue cleared.")
    elif action == "rebuild":
        res = camp_mod.materialize(c, s)
        flash(f"Added {res['added']} new matching leads.")
    elif action == "tick":
        res = camp_mod.tick(c, s)
        return jsonify(res)
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("dialer.campaign_detail", campaign_id=c.id))


def _mode_blocked(c, s):
    ready = readiness.check(s, g.account_id)
    lane = {"power": "power", "ai": "ai_outbound",
            "voicemail": "voicemail"}[c.mode]
    if ready["lanes"].get(lane):
        return ""
    for b in ready["blockers"]:
        return b["fix"]
    return ("This campaign can't start yet — finish setup first.")


# ------------------------------------------------------- the phone itself
def _presence(user_id=None):
    from dialer.models import RepPresence
    uid = user_id or getattr(g.member, "id", None) or 0
    p = RepPresence.query.filter_by(user_id=uid).first()
    if p is None:
        p = RepPresence(account_id=g.account_id, user_id=uid)
        db.session.add(p)
        db.session.commit()
    today = _now().date()
    if p.stats_date != today:
        p.stats_date = today
        p.dials_today = p.connects_today = p.talk_seconds_today = 0
        db.session.commit()
    return p


@bp.route("/dial")
@require("calls.make")
def dial():
    """The focused session view."""
    s, ready, prog = ctx()
    camp_id = request.args.get("campaign_id", type=int)
    camp = db.session.get(Campaign, camp_id) if camp_id else None
    if camp and camp.account_id != g.account_id:
        abort(403)
    return render_template(
        "dialer/dial.html", s=s, ready=ready, prog=prog, campaign=camp,
        presence=_presence(),
        campaigns=Campaign.query.filter_by(account_id=g.account_id,
                                           status="running", mode="power").all(),
        playbook=_active_playbook(camp))


@bp.route("/phone")
@require("calls.make")
def phone():
    """The pop-out window. Small, and it owns the Twilio Device, so the rest of
    HQ can be navigated -- or closed -- without dropping a live call."""
    s, ready, prog = ctx()
    uid = getattr(g.member, "id", None)
    recent = (Call.query.filter_by(account_id=g.account_id)
              .filter(db.or_(Call.agent_user_id == uid,
                             Call.agent_user_id.is_(None)))
              .order_by(Call.started_at.desc()).limit(10).all())
    return render_template(
        "dialer/phone.html", s=s, ready=ready, prog=prog,
        presence=_presence(), campaign=None, recent=recent,
        campaigns=Campaign.query.filter_by(account_id=g.account_id,
                                           status="running", mode="power").all(),
        playbook=_active_playbook(None))


def _active_playbook(campaign):
    pb_id = campaign.playbook_id if campaign and campaign.playbook_id else None
    if pb_id:
        return db.session.get(Playbook, pb_id)
    return (Playbook.query.filter_by(account_id=g.account_id, is_default=True)
            .first() or Playbook.query.filter_by(account_id=g.account_id).first())


@bp.route("/token")
@require("calls.make")
def token():
    """A short-lived Twilio access token for the browser phone."""
    s = get_settings(g.account_id)
    uid = getattr(g.member, "id", None) or 0
    identity = f"t{g.account_id}_u{uid}"
    if not s.twilio_twiml_app_sid and not registry.simulating(s):
        return jsonify(ok=False,
                       error="Finish the Twilio step in Setup first."), 400
    r = registry.telephony(s).access_token(identity, s.twilio_twiml_app_sid,
                                           ttl=3600)
    if not r.get("ok"):
        return jsonify(r), 400
    return jsonify(ok=True, token=r["token"], identity=identity,
                   simulating=registry.simulating(s))


@bp.route("/presence", methods=["POST"])
@require("calls.make")
def presence_update():
    p = _presence()
    data = request.get_json(silent=True) or request.form
    if "on_shift" in data:
        on = str(data.get("on_shift")).lower() in ("1", "true", "yes", "on")
        p.on_shift = on
        p.shift_started_at = _now() if on else None
        if not on:
            _release_my_claims(p)
    if "available" in data:
        p.available_for_transfers = str(data.get("available")).lower() in (
            "1", "true", "yes", "on")
    if data.get("conference_name"):
        p.conference_name = str(data["conference_name"])[:120]
    if data.get("rep_call_sid"):
        p.rep_call_sid = str(data["rep_call_sid"])[:64]
    p.last_seen_at = _now()
    db.session.commit()
    return jsonify(ok=True, on_shift=bool(p.on_shift),
                   available=bool(p.available_for_transfers))


def _release_my_claims(presence):
    """Leaving mid-queue must not strand leads for the rest of the team."""
    from dialer.models import CampaignLead
    n = (CampaignLead.query
         .filter_by(locked_by=f"user:{presence.user_id}", state="claimed")
         .update({"state": "queued", "locked_by": "", "lease_until": None},
                 synchronize_session=False))
    presence.current_call_id = None
    return n


@bp.route("/next", methods=["POST"])
@require("calls.make")
def next_lead():
    """Pull the next lead from a queue and dial it. The browser calls this."""
    from dialer import campaigns as camp_mod
    s = get_settings(g.account_id)
    p = _presence()
    camp_id = request.form.get("campaign_id", type=int) or (
        request.get_json(silent=True) or {}).get("campaign_id")
    camp = db.session.get(Campaign, int(camp_id)) if camp_id else None
    if camp is None or camp.account_id != g.account_id:
        return jsonify(ok=False, error="Pick a campaign first."), 400
    if camp.status != "running":
        return jsonify(ok=False, error=f"That campaign is {camp.status}."), 400

    worker = f"user:{p.user_id}"
    claimed = camp_mod.claim(camp, n=1, worker=worker)
    if not claimed:
        return jsonify(ok=False, done=True,
                       error="Nothing left in this queue right now.")
    cl = claimed[0]
    from app import Lead
    lead = db.session.get(Lead, cl.lead_id)
    ev = compliance_check(lead, s)
    if not ev["ok"]:
        cl.state, cl.skip_reason = "skipped", ev["reason"]
        db.session.commit()
        return jsonify(ok=False, skipped=True, reason=ev["reason"],
                       message=_explain(ev))
    number = camp_mod.pick_number(g.account_id, "rep", lead,
                                 simulate_ok=registry.simulating(s))
    if number is None:
        camp_mod.release(cl, "no number", defer_minutes=15)
        return jsonify(ok=False, error="Every number has hit its daily cap.")

    from dialer import calls as calls_mod
    call = calls_mod.start_call(g.account_id, lead, "power", s,
                                from_number=number.e164, campaign=camp,
                                campaign_lead=cl,
                                agent_user_id=p.user_id, gate=ev)
    cl.state, cl.last_call_id = "dialing", call.id
    cl.attempts = (cl.attempts or 0) + 1
    camp_mod.bump_number(number)
    p.current_call_id = call.id
    p.dials_today = (p.dials_today or 0) + 1
    db.session.commit()
    return jsonify(ok=True, **_call_payload(call, lead, number))


def compliance_check(lead, s):
    from dialer import compliance
    return compliance.can_dial(lead, "power", s, g.account_id)


def _explain(ev):
    from dialer import compliance
    return compliance.explain(ev)


def _call_payload(call, lead, number=None):
    from app import Note
    notes = (Note.query.filter_by(lead_id=lead.id)
             .order_by(Note.created_at.desc()).limit(4).all())
    tasks = [t for t in lead.tasks if not t.done][:4]
    return {
        "call_id": call.id, "lead_id": lead.id,
        "to": call.to_number, "from": call.from_number,
        "lead": {
            "name": lead.name, "business": lead.business or "",
            "business_type": lead.business_type or "",
            "phone": lead.phone_e164 or lead.phone, "email": lead.email or "",
            "status": lead.status, "state": lead.state_code or "",
            "line_type": lead.line_type or "unchecked",
            "call_count": lead.call_count or 0,
            "tags": lead.tag_list,
            "url": f"/admin/crm/{lead.id}",
            "notes": [{"body": n.body[:400], "kind": n.kind or "note",
                       "when": (n.created_at.isoformat() if n.created_at else "")}
                      for n in notes],
            "tasks": [{"title": t.title, "kind": t.kind,
                       "due": t.due_at.isoformat() if t.due_at else ""}
                      for t in tasks],
        },
    }


@bp.route("/call/manual", methods=["POST"])
@require("calls.make")
def call_manual():
    """Dial anything, with or without a campaign. This is the desk-phone mode."""
    from dialer import calls as calls_mod, campaigns as camp_mod, compliance
    from app import Lead
    s = get_settings(g.account_id)
    p = _presence()
    raw = (request.form.get("to") or
           (request.get_json(silent=True) or {}).get("to") or "").strip()
    lead_id = request.form.get("lead_id", type=int) or (
        request.get_json(silent=True) or {}).get("lead_id")

    lead = db.session.get(Lead, int(lead_id)) if lead_id else None
    if lead is not None and lead.owner_id != g.account_id:
        abort(403)
    if lead is None:
        e164, key, ok = compliance.normalize(raw)
        if not ok:
            return jsonify(ok=False, error="That isn't a dialable number."), 400
        lead = Lead.query.filter_by(owner_id=g.account_id,
                                    phone_key=key).first()
        if lead is None:
            lead = Lead(owner_id=g.account_id, name=f"Unknown {e164[-4:]}",
                        phone=e164, source="Manual dial", status="New")
            db.session.add(lead)
            db.session.flush()
            compliance.enrich_lead(lead)
    compliance.enrich_lead(lead)

    ev = compliance.can_dial(lead, "manual", s, g.account_id)
    if not ev["ok"]:
        return jsonify(ok=False, reason=ev["reason"],
                       error=compliance.explain(ev)), 400
    number = camp_mod.pick_number(g.account_id, "rep", lead,
                                 simulate_ok=registry.simulating(s))
    if number is None and not registry.simulating(s):
        return jsonify(ok=False, error="No number is free to dial from."), 400
    call = calls_mod.start_call(g.account_id, lead, "manual", s,
                                from_number=number.e164 if number else "",
                                agent_user_id=p.user_id, gate=ev)
    if number:
        camp_mod.bump_number(number)
    p.current_call_id = call.id
    p.dials_today = (p.dials_today or 0) + 1
    db.session.commit()
    return jsonify(ok=True, **_call_payload(call, lead, number))


@bp.route("/call/<int:call_id>/connected", methods=["POST"])
@require("calls.make")
def call_connected(call_id):
    """The browser tells us the media actually connected."""
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    sid = (request.get_json(silent=True) or request.form).get("call_sid")
    if sid:
        call.twilio_sid = str(sid)[:64]
    call.status = "in-progress"
    call.answered_at = call.answered_at or _now()
    call.answered_live = True
    p = _presence()
    p.connects_today = (p.connects_today or 0) + 1
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/call/<int:call_id>/notes", methods=["POST"])
@require("calls.make")
def call_notes(call_id):
    """Autosaved while the rep types, so nothing is lost if they hang up."""
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    call.notes_draft = ((request.get_json(silent=True) or request.form)
                        .get("notes") or "")[:8000]
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/call/<int:call_id>/disposition", methods=["POST"])
@require("calls.disposition")
def call_disposition(call_id):
    from dialer import calls as calls_mod, simulate
    s = get_settings(g.account_id)
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    data = request.get_json(silent=True) or request.form
    disp = (data.get("disposition") or "").strip()
    notes = (data.get("notes") or call.notes_draft or "").strip()
    qual = data.get("qualification")
    if qual:
        call.qualification_json = qual if isinstance(qual, str) else json.dumps(qual)
    calls_mod.set_disposition(call, disp, user_id=getattr(g.member, "id", None),
                              settings=s, note=notes)
    p = _presence()
    p.talk_seconds_today = (p.talk_seconds_today or 0) + int(call.duration_s or 0)
    p.current_call_id = None
    if not call.ended_at:
        call.ended_at = _now()
        call.status = "completed"
    db.session.commit()
    if registry.simulating(s):
        simulate.advance(call, s)
    else:
        calls_mod.finalize(call, s)
    return jsonify(ok=True, call_id=call.id,
                   summary=call.summary or "", score=call.score)


@bp.route("/call/<int:call_id>/drop-voicemail", methods=["POST"])
@require("calls.make")
def drop_voicemail(call_id):
    """One click: the recording plays on the prospect's leg, the rep's line is
    free immediately, and the queue moves on."""
    from dialer import urls
    s = get_settings(g.account_id)
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    drop_id = (request.get_json(silent=True) or request.form).get("drop_id")
    drop = (db.session.get(VoicemailDrop, int(drop_id)) if drop_id
            else VoicemailDrop.query.filter_by(account_id=g.account_id,
                                               is_default=True).first()
            or VoicemailDrop.query.filter_by(account_id=g.account_id).first())
    if drop is None:
        return jsonify(ok=False,
                       error="Record a voicemail in Setup first."), 400
    twiml = (f"<Response><Play>{urls.voicemail_media(drop.id)}</Play>"
             f"<Hangup/></Response>")
    if call.twilio_sid:
        r = registry.telephony(s).redirect_call(call.twilio_sid, twiml)
        if not r.get("ok"):
            return jsonify(ok=False, error=r.get("error")), 400
    call.voicemail_dropped = True
    from dialer import calls as calls_mod
    calls_mod.set_disposition(call, "voicemail_left",
                              user_id=getattr(g.member, "id", None), settings=s)
    call.ended_at = call.ended_at or _now()
    call.status = "completed"
    p = _presence()
    p.current_call_id = None
    db.session.commit()
    from dialer import simulate
    if registry.simulating(s):
        simulate.advance(call, s)
    else:
        calls_mod.finalize(call, s)
    return jsonify(ok=True, dropped=drop.name)


@bp.route("/call/<int:call_id>/hangup", methods=["POST"])
@require("calls.make")
def call_hangup(call_id):
    s = get_settings(g.account_id)
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    if call.twilio_sid:
        registry.telephony(s).hangup(call.twilio_sid)
    call.ended_at = call.ended_at or _now()
    call.status = "completed"
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/coach/<int:call_id>")
@require("calls.make")
def coach(call_id):
    """Polled by the rep's rail: new suggestions since `since`."""
    from dialer.models import CoachTick
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    since = request.args.get("since", type=int) or 0
    rows = (CoachTick.query.filter(CoachTick.call_id == call_id,
                                   CoachTick.seq > since)
            .order_by(CoachTick.seq).limit(20).all())
    return jsonify(ok=True, ticks=[{"seq": t.seq, "kind": t.kind,
                                    "step": t.step, "objection": t.objection,
                                    "body": t.body} for t in rows],
                   status=call.status, duration=call.duration_s or 0)


# ------------------------------------------------------------ call history
@bp.route("/calls")
def calls_list():
    s, ready, prog = ctx()
    q = Call.query.filter_by(account_id=g.account_id)
    # an agent only sees their own calls; everyone above sees the floor
    if not perms.can(g.member, "calls.view") or \
            perms.scope_for(getattr(g.member, "role", "owner"),
                            "calls.view") == "own":
        q = q.filter(Call.agent_user_id == getattr(g.member, "id", None))
    disp = request.args.get("disposition", "")
    if disp:
        q = q.filter(Call.disposition == disp)
    camp = request.args.get("campaign_id", type=int)
    if camp:
        q = q.filter(Call.campaign_id == camp)
    term = (request.args.get("q") or "").strip()
    if term:
        q = q.filter(db.or_(Call.to_number.ilike(f"%{term}%"),
                            Call.summary.ilike(f"%{term}%"),
                            Call.transcript.ilike(f"%{term}%")))
    rows = q.order_by(Call.started_at.desc()).limit(300).all()
    from app import Lead
    leads = {l.id: l for l in Lead.query.filter(
        Lead.id.in_([c.lead_id for c in rows if c.lead_id]))} if rows else {}
    from dialer.models import DISPOSITIONS
    return render_template("dialer/calls.html", s=s, ready=ready, prog=prog,
                           calls=rows, leads=leads, dispositions=DISPOSITIONS,
                           q=term, disposition=disp,
                           campaigns=Campaign.query.filter_by(
                               account_id=g.account_id).all())


@bp.route("/calls/<int:call_id>")
def call_detail(call_id):
    s, ready, prog = ctx()
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    if perms.scope_for(getattr(g.member, "role", "owner"),
                       "recordings.listen") == "own" \
            and call.agent_user_id != getattr(g.member, "id", None):
        return render_template("teams/denied.html",
                               perm="recordings.listen"), 403
    from app import Lead
    from dialer.models import CallEvent
    return render_template(
        "dialer/call_detail.html", s=s, ready=ready, prog=prog, call=call,
        lead=db.session.get(Lead, call.lead_id) if call.lead_id else None,
        events=CallEvent.query.filter_by(call_id=call.id)
        .order_by(CallEvent.at).all())


@bp.route("/calls/<int:call_id>/recording")
def call_recording(call_id):
    """Proxied: Twilio media URLs need HTTP Basic auth, so the raw URL must
    never reach a browser."""
    from flask import Response
    s = get_settings(g.account_id)
    call = Call.query.get_or_404(call_id)
    if call.account_id != g.account_id:
        abort(403)
    if perms.scope_for(getattr(g.member, "role", "owner"),
                       "recordings.listen") == "none":
        abort(403)
    if not call.recording_sid:
        abort(404)
    r = registry.telephony(s).fetch_recording(call.recording_sid)
    if not r.get("ok"):
        abort(404)
    return Response(r["content"], mimetype=r.get("mimetype", "audio/mpeg"))


@bp.route("/calls/export.zip")
@require("recordings.download")
def calls_export():
    """Recordings plus a transcript CSV, streamed as one zip."""
    import csv
    import io
    import zipfile
    from flask import Response
    s = get_settings(g.account_id)
    ids = request.args.getlist("call_id", type=int)
    q = Call.query.filter_by(account_id=g.account_id)
    if ids:
        q = q.filter(Call.id.in_(ids))
    rows = q.order_by(Call.started_at.desc()).limit(500).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        csv_buf = io.StringIO()
        w = csv.writer(csv_buf)
        w.writerow(["call_id", "when", "to", "from", "outcome", "disposition",
                    "duration_s", "score", "summary", "transcript"])
        tel = registry.telephony(s)
        for c in rows:
            w.writerow([c.id, c.started_at, c.to_number, c.from_number,
                        c.system_outcome, c.disposition, c.duration_s,
                        c.score or "", (c.summary or "").replace("\n", " "),
                        (c.transcript or "").replace("\n", " ")])
            if c.recording_sid and not c.recording_deleted_at:
                rec = tel.fetch_recording(c.recording_sid)
                if rec.get("ok"):
                    ext = "wav" if "wav" in rec.get("mimetype", "") else "mp3"
                    z.writestr(f"recordings/call-{c.id}.{ext}", rec["content"])
        z.writestr("calls.csv", csv_buf.getvalue())
    buf.seek(0)
    stamp = _now().strftime("%Y-%m-%d")
    return Response(buf.read(), mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="calls-{stamp}.zip"'})


# ----------------------------------------------------------------- reports
@bp.route("/reports")
@require("reports.view")
def reports_page():
    from dialer import reports as rep
    s, ready, prog = ctx()
    days = request.args.get("days", type=int) or 7
    start, end = rep.day_range(days)
    scope_user = None
    if perms.scope_for(getattr(g.member, "role", "owner"),
                       "reports.view") == "own":
        scope_user = getattr(g.member, "id", None)
    return render_template(
        "dialer/reports.html", s=s, ready=ready, prog=prog, days=days,
        summary=rep.summary(g.account_id, start, end, user_id=scope_user),
        dispositions=rep.by_disposition(g.account_id, start, end),
        reps=rep.by_rep(g.account_id, start, end) if not scope_user else [],
        campaigns=rep.by_campaign(g.account_id, start, end),
        numbers=rep.by_number(g.account_id),
        ai_vs_human=rep.ai_vs_human(g.account_id, start, end),
        hourly=rep.hourly(g.account_id),
        abandon=rep.abandon_rate(g.account_id),
        costs=rep.cost_breakdown(g.account_id, start, end))


# -------------------------------------------------------------- test call
@bp.route("/test-call", methods=["POST"])
@require("calls.make")
def test_call():
    from dialer import calls as calls_mod, campaigns as camp_mod, compliance
    from dialer import simulate
    from app import Lead
    s = get_settings(g.account_id)
    to = (request.form.get("to_number") or "").strip()
    agent_id = request.form.get("agent_id", type=int)
    e164, key, ok = compliance.normalize(to)
    if not ok:
        flash("That doesn't look like a phone number.", "error")
        return redirect(url_for("dialer.setup", step=11))

    lead = Lead.query.filter_by(owner_id=g.account_id, phone_key=key).first()
    if lead is None:
        lead = Lead(owner_id=g.account_id, name="Setup test call", phone=e164,
                    source="Setup test", status="New",
                    consent_status="express", consent_source="own number")
        db.session.add(lead)
        db.session.flush()
        compliance.enrich_lead(lead)
    agent = db.session.get(AiAgent, agent_id) if agent_id else None
    mode = "ai_outbound" if agent else "manual"
    ev = compliance.can_dial(lead, mode, s, g.account_id)
    if not ev["ok"] and ev["reason"] not in ("line_type_unknown",):
        flash(compliance.explain(ev), "error")
        return redirect(url_for("dialer.setup", step=11))

    chosen_id = request.form.get("from_number_id", type=int)
    number = None
    if chosen_id:
        number = db.session.get(PhoneNumber, chosen_id)
        if number is not None and number.account_id != g.account_id:
            abort(403)
        if number is not None and number.is_placeholder \
                and not registry.simulating(s):
            flash(f"{number.pretty} is sample data, not a number you own, so "
                  f"Twilio will not place a call from it. Pick another.",
                  "error")
            return redirect(url_for("dialer.setup", step=11))
    if number is None:
        number = camp_mod.pick_number(g.account_id, "ai" if agent else "rep",
                                      lead, simulate_ok=registry.simulating(s))
    if number is None:
        flash("No number on your account can place this call. Buy one on "
              "step 4, or check none of them are parked.", "error")
        return redirect(url_for("dialer.setup", step=11))
    call = calls_mod.start_call(g.account_id, lead, mode, s,
                                from_number=number.e164 if number else "",
                                ai_agent=agent, gate=ev)
    if agent and agent.elevenlabs_agent_id:
        r = registry.voice_agent(s).outbound_call(
            agent.elevenlabs_agent_id,
            number.elevenlabs_phone_id if number else "",
            call.to_number, variables={"lead_name": "there",
                                       "first_name": "there", "business": "",
                                       "business_type": "", "city": "",
                                       "state": "", "prior_calls": "0",
                                       "last_note": "", "lead_status": "New",
                                       "is_known": "false"})
        if r.get("ok"):
            call.elevenlabs_conversation_id = (r.get("conversation_id") or "")[:64]
            call.twilio_sid = (r.get("call_sid") or "")[:64]
    else:
        from dialer import urls
        r = registry.telephony(s).create_call(
            to=call.to_number, from_=number.e164 if number else "",
            url=urls.twilio_outgoing(g.account_id, call.id),
            status_callback=urls.twilio_status(g.account_id),
            record=bool(s.records_calls))
        if r.get("ok"):
            call.twilio_sid = (r.get("sid") or "")[:64]
    db.session.commit()
    if not r.get("ok"):
        flash(f"The call didn't go out: {r.get('error')}", "error")
        return redirect(url_for("dialer.setup", step=11))

    if registry.simulating(s):
        simulate.advance(call, s)
        wizard.mark(s, "test", done=True)
        db.session.commit()
        flash("Practice call complete — no real call was placed. Open the call "
              "record to see the transcript, score and follow-up it produced.")
        return redirect(url_for("dialer.call_detail", call_id=call.id))
    wizard.mark(s, "test", done=True)
    db.session.commit()
    flash("Calling you now. The record will fill in when the call ends.")
    return redirect(url_for("dialer.call_detail", call_id=call.id))


# ----------------------------------------------------- practice mode / demo
@bp.route("/practice", methods=["POST"])
@require("dialer.settings")
def practice_toggle():
    s = get_settings(g.account_id)
    s.simulation = not s.simulation
    log("dialer.practice_mode", detail=f"on={s.simulation}",
        account_id=g.account_id, user=g.member)
    db.session.commit()
    flash("Practice mode is ON — nothing dials for real and nothing is "
          "charged." if s.simulation else
          "Practice mode is OFF. Calls are real from here.")
    return redirect(request.referrer or url_for("dialer.home"))


@bp.route("/demo/build", methods=["POST"])
@require("dialer.settings")
def demo_build():
    from dialer import demo
    s = get_settings(g.account_id)
    made = demo.seed_demo(g.account_id, s)
    flash(f"Demo data built: {made.get('leads', 0)} venues and "
          f"{made.get('calls', 0)} finished calls with transcripts.")
    return redirect(url_for("dialer.home"))


@bp.route("/demo/clear", methods=["POST"])
@require("dialer.settings")
def demo_clear():
    from dialer import demo
    demo.clear_demo(g.account_id)
    flash("Demo data removed.")
    return redirect(url_for("dialer.home"))


@bp.route("/compliance", methods=["GET", "POST"])
@require("dialer.settings")
def compliance_page():
    """Suppression list, consent records, and the gate switch."""
    from dialer.models import ConsentRecord, StateRule, Suppression
    s, ready, prog = ctx()
    if request.method == "POST" and perms.can(g.member, "compliance.override"):
        action = request.form.get("action")
        if action == "gate":
            want_off = request.form.get("gate_ai_line_type") != "on"
            attest = (request.form.get("attestation") or "").strip()
            if want_off and len(attest) < 20:
                flash("To switch the mobile gate off, type the sentence "
                      "confirming you have consent for these numbers.", "error")
                return redirect(url_for("dialer.compliance_page"))
            s.gate_ai_line_type = not want_off
            s.gate_attestation = attest[:2000]
            s.gate_ai_line_type_off_at = _now() if want_off else None
            s.gate_ai_line_type_off_by = (getattr(g.member, "id", None)
                                          if want_off else None)
            log("compliance.gate", detail=f"ai_line_type_gate_on={not want_off}; "
                f"attestation={attest[:300]}", account_id=g.account_id,
                user=g.member)
            flash("Mobile gate is OFF. Your attestation is recorded against "
                  "every call this produces." if want_off
                  else "Mobile gate is back on.")
        elif action == "suppress":
            from dialer import compliance
            raw = request.form.get("phone", "")
            _, key, ok = compliance.normalize(raw)
            if ok:
                compliance.suppress(g.account_id, key,
                                    reason=request.form.get("reason", ""),
                                    source="manual",
                                    user_id=getattr(g.member, "id", None))
                flash(f"{raw} will never be dialed from this account again.")
            else:
                flash("That isn't a valid number.", "error")
        elif action == "unsuppress":
            row = db.session.get(Suppression, request.form.get("id", type=int))
            if row and row.account_id == g.account_id:
                db.session.delete(row)
                flash("Removed from the do-not-call list.")
        db.session.commit()
        return redirect(url_for("dialer.compliance_page"))

    return render_template(
        "dialer/compliance.html", s=s, ready=ready, prog=prog,
        suppressions=Suppression.query.filter_by(account_id=g.account_id)
        .order_by(Suppression.created_at.desc()).limit(200).all(),
        consents=ConsentRecord.query.filter_by(account_id=g.account_id)
        .order_by(ConsentRecord.captured_at.desc()).limit(100).all(),
        states=StateRule.query.order_by(StateRule.state_code).all())
