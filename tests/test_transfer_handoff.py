"""The hand-off: how it sounds, and the destination that cannot work.

A live test went: say yes, hear hold music, no second ring, land in a
voicemail. Two separate things produced that, and neither raised an error.

* The hand-off was hard-coded to a conference transfer. ElevenLabs parks the
  prospect in a Twilio conference while it dials the destination, and an
  unconfigured Twilio conference plays its default classical playlist. The
  conference is ElevenLabs', so waitUrl is not ours to set. The only way to
  have no hold music is to not use a conference.
* The destination was the same phone the AI was calling. It is busy by
  definition, so the carrier rolled the hand-off to its voicemail, which is
  why the music ran long and the phone never rang again.
"""
import pytest

from app import db
from dialer import agents as agents_mod
from dialer.models import AiAgent, PhoneNumber, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user

MINE = "+18655550123"
THEIRS = "+18655550987"


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = MINE
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def make_agent(owner_id, **kw):
    a = AiAgent(account_id=owner_id, name="NapkinAds venue caller",
                direction="outbound", active=True, **kw)
    db.session.add(a)
    db.session.commit()
    return a


# ------------------------------------------------------- what gets asked for
def test_the_handoff_is_a_blind_transfer_by_default(account):
    """The whole point. Conference is what played the hold music."""
    owner, _ = account
    s = get_settings(owner.id)
    cfg = agents_mod.transfer_config(make_agent(owner.id), s)
    assert cfg["params"]["transfers"][0]["transfer_type"] == "blind"


def test_conference_is_still_available_for_anyone_who_wants_it(account):
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_handoff="conference")
    assert agents_mod.transfer_config(a, s)[
        "params"]["transfers"][0]["transfer_type"] == "conference"


def test_a_junk_value_falls_back_to_blind_rather_than_being_sent(account):
    """ElevenLabs validates nothing nested in conversation_config and
    answers 200, so an unknown enum would be dropped in silence and the
    agent would quietly keep whatever it had."""
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_handoff="warm-ish")
    assert agents_mod.transfer_config(a, s)[
        "params"]["transfers"][0]["transfer_type"] == "blind"


def test_sip_refer_is_never_requested(account):
    """It needs a SIP trunk permitting REFER. Every number here arrives
    through the native Twilio integration, so asking would fail on every
    account we have."""
    owner, _ = account
    s = get_settings(owner.id)
    for want in ("sip_refer", "", None, "blind", "conference"):
        a = AiAgent(account_id=owner.id, name="x", transfer_handoff=want)
        assert agents_mod.handoff_type(a) in ("blind", "conference")


def test_an_agent_predating_the_column_still_gets_a_transfer(account):
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_handoff=None)
    cfg = agents_mod.transfer_config(a, s)
    assert cfg["params"]["transfers"][0]["transfer_type"] == "blind"


# ------------------------------------------------- the impossible destination
def test_handing_off_to_the_phone_being_called_is_detected(account):
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_to_number=MINE)
    assert agents_mod.transfer_collides(a, s, MINE) is True


def test_it_is_detected_through_the_callback_number_fallback(account):
    """The real shape of it. He never set a destination, so it fell back to
    the callback number, which on a one-person account is his own mobile."""
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id)
    assert not a.transfer_to_number
    assert agents_mod.transfer_collides(a, s, MINE) is True


def test_formatting_differences_do_not_hide_the_collision(account):
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_to_number="(865) 555-0123")
    assert agents_mod.transfer_collides(a, s, "+1 865 555 0123") is True


def test_two_different_phones_are_not_a_collision(account):
    owner, _ = account
    s = get_settings(owner.id)
    a = make_agent(owner.id, transfer_to_number=THEIRS)
    assert agents_mod.transfer_collides(a, s, MINE) is False


def test_no_destination_at_all_is_not_a_collision(account):
    """Nothing to collide with. A different warning already covers it."""
    owner, _ = account
    s = get_settings(owner.id)
    s.ai_callback_number = ""
    db.session.commit()
    a = make_agent(owner.id)
    assert agents_mod.transfer_collides(a, s, MINE) is False


# ------------------------------------------------------- the test call itself
def seed_ai_number(owner_id):
    db.session.add(PhoneNumber(
        account_id=owner_id, e164="+14406642753", twilio_sid="PN" + "a" * 32,
        pool="ai", state="active", friendly_name="AI line",
        elevenlabs_phone_id="pn_1", area_code="440"))
    db.session.commit()


def test_the_test_call_refuses_to_place_a_doomed_handoff(account):
    """Without this the only feedback is forty seconds of hold music and
    your own voicemail, which reads as "transfers are broken"."""
    owner, client = account
    seed_ai_number(owner.id)
    a = make_agent(owner.id, elevenlabs_agent_id="ag_1",
                   transfer_to_number=MINE)

    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": MINE, "agent_id": a.id}
                       ).get_data(as_text=True)

    assert "is the number it is calling" in body
    assert "Use a second phone" in body


def test_the_refusal_names_the_number_it_would_have_dialled(account):
    owner, client = account
    seed_ai_number(owner.id)
    a = make_agent(owner.id, elevenlabs_agent_id="ag_1",
                   transfer_to_number=MINE)
    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": MINE, "agent_id": a.id}
                       ).get_data(as_text=True)
    assert MINE in body


def test_a_test_call_to_a_different_phone_is_not_blocked(account):
    owner, client = account
    seed_ai_number(owner.id)
    a = make_agent(owner.id, elevenlabs_agent_id="ag_1",
                   transfer_to_number=THEIRS)
    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": MINE, "agent_id": a.id}
                       ).get_data(as_text=True)
    assert "is the number it is calling" not in body


def test_ringing_your_own_phone_with_no_ai_is_never_blocked(account):
    """"Just ring my phone" has no hand-off in it at all."""
    owner, client = account
    db.session.add(PhoneNumber(
        account_id=owner.id, e164="+14406642754", twilio_sid="PN" + "b" * 32,
        pool="rep", state="active", friendly_name="Rep line", area_code="440"))
    db.session.commit()
    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": MINE}).get_data(as_text=True)
    assert "is the number it is calling" not in body


# ------------------------------------------------------------- the control
def test_the_choice_is_on_the_agent_page_and_actually_renders(account):
    """HANDOFFS has to reach the template. An undefined name in Jinja is an
    empty loop, not an error, so the select would render with no options at
    all and look like a styling bug."""
    owner, client = account
    a = make_agent(owner.id)
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert 'name="transfer_handoff"' in body
    assert agents_mod.HANDOFFS["blind"]["label"] in body
    assert agents_mod.HANDOFFS["conference"]["label"] in body


def test_the_hint_warns_that_conference_means_hold_music(account):
    owner, client = account
    a = make_agent(owner.id, transfer_handoff="conference")
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "hold music" in body


def test_the_choice_saves(account):
    owner, client = account
    a = make_agent(owner.id)
    client.post(f"/dialer/agents/{a.id}", follow_redirects=True,
                data={"name": a.name, "transfer_handoff": "conference"})
    assert db.session.get(AiAgent, a.id).transfer_handoff == "conference"


def test_the_destination_field_warns_against_the_phone_you_test_on(account):
    owner, client = account
    a = make_agent(owner.id)
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "already on the call" in body
