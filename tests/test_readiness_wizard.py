"""Readiness blockers and wizard progress -- the 'tell me exactly what's
missing' promise."""
import pytest

from app import db
from dialer import readiness, wizard
from dialer.models import AiAgent, PhoneNumber, Playbook, VoicemailDrop
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def bare(ctx, monkeypatch):
    """A real account with nothing configured, and simulation OFF so the
    blockers are the ones a live account would see."""
    monkeypatch.delenv("DIALER_SIMULATION", raising=False)
    owner = make_user(name="Bare", email="b@x.test", dialer=True)
    return owner, get_settings(owner.id)


def test_a_new_account_is_blocked_on_twilio_and_says_so(bare):
    owner, s = bare
    r = readiness.check(s, owner.id)
    assert r["ok"] is False
    fixes = " ".join(b["fix"] for b in r["blockers"])
    assert "Twilio" in fixes
    assert any(b["step"] == 2 for b in r["blockers"])
    assert not any(r["lanes"].values()), "no lane should be live yet"


def test_the_elevenlabs_blocker_names_the_step_and_the_minutes(bare):
    owner, s = bare
    s.twilio_verified_at = __import__("datetime").datetime.utcnow()
    s.set_secret("twilio_account_sid", "ACxxx", "twilio_sid_last4")
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550101",
                               pool="rep", state="active"))
    db.session.commit()
    r = readiness.check(s, owner.id)
    msg = [b["fix"] for b in r["blockers"] if "ElevenLabs" in b["fix"]]
    assert msg, "expected an ElevenLabs blocker"
    assert "will not work until" in msg[0]
    assert "Setup step 6" in msg[0]
    assert "Human dialing works without it" in msg[0]


def test_human_dialing_goes_live_before_the_ai_does(bare):
    owner, s = bare
    s.set_secret("twilio_account_sid", "ACxxx", "twilio_sid_last4")
    s.twilio_verified_at = __import__("datetime").datetime.utcnow()
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655550101",
                               pool="rep", state="active"))
    db.session.commit()
    lanes = readiness.check(s, owner.id)["lanes"]
    assert lanes["manual"] and lanes["power"]
    assert not lanes["ai_outbound"]


def test_an_individual_twilio_profile_is_called_a_dead_end(bare):
    owner, s = bare
    s.twilio_pcp_status = "individual"
    db.session.commit()
    warns = " ".join(w["fix"] for w in readiness.check(s, owner.id)["warnings"])
    assert "dead end" in warns and "3 calls at once" in warns


def test_recording_without_an_announcement_is_warned_about(bare):
    owner, s = bare
    s.recording_enabled = True
    s.recording_announce = False
    db.session.commit()
    warns = " ".join(w["fix"] for w in readiness.check(s, owner.id)["warnings"])
    assert "recording without announcing" in warns


def test_switching_the_gate_off_shows_a_standing_warning(bare):
    owner, s = bare
    s.gate_ai_line_type = False
    db.session.commit()
    warns = " ".join(w["fix"] for w in readiness.check(s, owner.id)["warnings"])
    assert "mobile-number gate is switched OFF" in warns


def test_bursting_is_warned_about_because_it_doubles_the_rate(bare):
    owner, s = bare
    s.elevenlabs_bursting = True
    db.session.commit()
    warns = " ".join(w["fix"] for w in readiness.check(s, owner.id)["warnings"])
    assert "double the per-minute rate" in warns


# ------------------------------------------------------------------ wizard
def test_wizard_progress_starts_empty_and_lists_what_is_required(bare):
    owner, s = bare
    p = wizard.progress(s, owner.id)
    assert p["done"] == 0 and p["total"] == 11
    assert p["complete"] is False
    keys = {step["key"] for step in p["required_left"]}
    assert keys == set(wizard.REQUIRED)
    assert p["next"]["key"] == "intent"


def test_a_step_is_done_because_a_probe_passed_not_because_of_a_click(bare):
    owner, s = bare
    wizard.mark(s, "twilio", done=True)      # a click alone
    db.session.commit()
    assert wizard.status(s, owner.id)["twilio"] == "todo"

    s.set_secret("twilio_account_sid", "ACxxx", "twilio_sid_last4")
    s.twilio_verified_at = __import__("datetime").datetime.utcnow()
    db.session.commit()
    assert wizard.status(s, owner.id)["twilio"] == "done"


def test_a_long_unverified_key_goes_stale_rather_than_staying_green(bare):
    from datetime import datetime, timedelta
    owner, s = bare
    s.set_secret("twilio_account_sid", "ACxxx", "twilio_sid_last4")
    s.twilio_verified_at = datetime.utcnow() - timedelta(days=120)
    db.session.commit()
    assert wizard.status(s, owner.id)["twilio"] == "stale"


def test_skipping_a_step_is_remembered(bare):
    owner, s = bare
    wizard.mark(s, "business", skipped=True)
    db.session.commit()
    assert wizard.status(s, owner.id)["business"] == "skipped"


def test_content_steps_complete_when_the_content_exists(bare):
    owner, s = bare
    assert wizard.status(s, owner.id)["playbook"] == "todo"
    db.session.add(Playbook(account_id=owner.id, name="Script"))
    db.session.add(VoicemailDrop(account_id=owner.id, name="VM"))
    db.session.commit()
    st = wizard.status(s, owner.id)
    assert st["playbook"] == "done" and st["voicemail"] == "done"


def test_practice_mode_does_not_pretend_your_vendors_are_connected(ctx):
    """Practice mode makes the product USABLE with no accounts. It does not
    make the setup checklist complete -- claiming Twilio is connected when it
    is not is the kind of lie that loses someone's trust in every other number
    on the page.

    'Does this lane work right now' is a different question, and readiness
    answers it: in practice mode the lanes ARE live.
    """
    owner = make_user(name="Sim", email="s@x.test", dialer=True)
    s = get_settings(owner.id)
    st = wizard.status(s, owner.id)          # DIALER_SIMULATION=1 in conftest
    assert st["twilio"] == "todo"
    assert st["elevenlabs"] == "todo"
    assert st["llm"] == "todo"
    assert wizard.progress(s, owner.id)["done"] == 0

    ready = readiness.check(s, owner.id)
    assert ready["simulating"] is True
    assert ready["lanes"]["power"] is True   # usable, just not set up


def test_demo_content_does_not_count_as_your_setup(ctx):
    """The sample playbook and numbers belong to the demo. Remove the demo and
    they go with it, so they must not tick your checklist."""
    from dialer.demo import DEMO_PREFIX, DEMO_TAG
    from dialer.models import PhoneNumber, Playbook, VoicemailDrop
    owner = make_user(name="Demo", email="d@x.test", dialer=True)
    s = get_settings(owner.id)
    db.session.add_all([
        PhoneNumber(account_id=owner.id, e164="+18655550101", pool="rep",
                    state="active", notes=DEMO_TAG),
        Playbook(account_id=owner.id, name=DEMO_PREFIX + "Napkin outreach"),
        VoicemailDrop(account_id=owner.id, name=DEMO_PREFIX + "20-second drop"),
    ])
    db.session.commit()
    st = wizard.status(s, owner.id)
    assert st["numbers"] == "todo"
    assert st["playbook"] == "todo"
    assert st["voicemail"] == "todo"

    # a real one of each DOES count
    db.session.add_all([
        PhoneNumber(account_id=owner.id, e164="+18655550199", pool="rep",
                    state="active", notes=""),
        Playbook(account_id=owner.id, name="My cold call script"),
        VoicemailDrop(account_id=owner.id, name="My voicemail"),
    ])
    db.session.commit()
    st = wizard.status(s, owner.id)
    assert st["numbers"] == "done"
    assert st["playbook"] == "done"
    assert st["voicemail"] == "done"


def test_a_brand_new_account_reports_zero_of_eleven(ctx):
    owner = make_user(name="Fresh", email="f@x.test", dialer=True)
    p = wizard.progress(get_settings(owner.id), owner.id)
    assert p["done"] == 0
    assert p["pct"] == 0
    assert p["complete"] is False


def test_a_practice_mode_probe_does_not_tick_a_vendor_step(ctx):
    """The regression behind "it says 8 of 11 and I did none of it".

    In practice mode the fake providers answer every probe with "ok", and
    _test_vendor writes that answer into the same columns a live connection
    writes to. Reading them back turned a practice session into a green
    checklist for an account with no Twilio, no AI key and no ElevenLabs.
    """
    from datetime import datetime

    owner = make_user(name="Sim2", email="s2@x.test", dialer=True)
    s = get_settings(owner.id)

    # exactly what pressing "Test connection" in practice mode leaves behind
    s.set_secret("twilio_account_sid", "ACfake", "twilio_sid_last4")
    s.twilio_verified_at = datetime.utcnow()
    s.twilio_pcp_status = "business"
    s.set_secret("llm_key", "sk-fake", "llm_last4")
    s.llm_verified_at = datetime.utcnow()
    s.set_secret("elevenlabs_key", "el-fake", "elevenlabs_last4")
    s.elevenlabs_verified_at = datetime.utcnow()
    db.session.commit()

    st = wizard.status(s, owner.id)          # DIALER_SIMULATION=1 in conftest
    assert st["twilio"] == "todo"
    assert st["business"] == "todo"
    assert st["llm"] == "todo"
    assert st["elevenlabs"] == "todo"
    assert wizard.progress(s, owner.id)["done"] == 0


def test_the_same_probes_do_count_once_practice_mode_is_off(ctx, monkeypatch):
    """The keys are not thrown away -- they are just not evidence yet."""
    from datetime import datetime

    owner = make_user(name="Live", email="live@x.test", dialer=True)
    s = get_settings(owner.id)
    s.set_secret("twilio_account_sid", "ACreal", "twilio_sid_last4")
    s.twilio_verified_at = datetime.utcnow()
    s.twilio_pcp_status = "business"
    db.session.commit()

    monkeypatch.delenv("DIALER_SIMULATION", raising=False)
    st = wizard.status(s, owner.id)
    assert st["twilio"] == "done"
    assert st["business"] == "done"


def test_a_profile_status_alone_is_not_a_verified_business(bare):
    """twilio_pcp_status is written by the probe that connects Twilio and is
    never cleared, so on its own it would keep step 3 green after the account
    is disconnected."""
    owner, s = bare
    s.twilio_pcp_status = "business"          # left over, no account behind it
    db.session.commit()
    assert wizard.status(s, owner.id)["business"] == "todo"
    assert wizard.progress(s, owner.id)["done"] == 0
