"""Choosing the number a call goes out from.

The test call picked a number on its own and picked the sample one, so Twilio
answered with error 21210, "the source phone number provided is not yet
verified for your account" -- baffling wording when you never chose a number.

The same picker feeds real campaigns, so this was not only a setup-screen
problem: a live campaign could have grabbed the same unusable number.
"""
import pytest

from app import Lead, db
from dialer import campaigns as camp_mod
from dialer.models import PhoneNumber
from dialer.settings_store import get_settings
from tests.conftest import make_user

REAL_SID = "PN" + "0123abcd" * 4


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.enforce_window = False
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def number(owner_id, e164, sid=REAL_SID, pool="rep"):
    n = PhoneNumber(account_id=owner_id, e164=e164, twilio_sid=sid, pool=pool,
                    state="active", area_code=e164[2:5], friendly_name=e164)
    db.session.add(n)
    db.session.commit()
    return n


# ------------------------------------------- what counts as callable
def test_a_sample_number_is_a_placeholder():
    n = PhoneNumber(e164="+18655550101", twilio_sid="PNdemo0101")
    assert n.is_placeholder is True


def test_a_purchased_number_is_not():
    assert PhoneNumber(e164="+14406642753", twilio_sid=REAL_SID).is_placeholder is False


def test_a_row_with_no_sid_is_a_placeholder():
    assert PhoneNumber(e164="+14406642753", twilio_sid="").is_placeholder is True


# ----------------------------------------- the picker that feeds campaigns
def test_the_picker_skips_a_sample_number_for_a_real_call(account):
    """The bug underneath the one he saw. A live campaign would have made
    the same choice."""
    owner, _ = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    real = number(owner.id, "+14406642753")
    picked = camp_mod.pick_number(owner.id, "rep", None, simulate_ok=False)
    assert picked.id == real.id


def test_the_picker_returns_nothing_rather_than_something_broken(account):
    owner, _ = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    assert camp_mod.pick_number(owner.id, "rep", None, simulate_ok=False) is None


def test_practice_mode_may_use_a_sample_number(account):
    """Nothing really dials there, and refusing would make practice mode
    useless on an account that has not bought anything yet."""
    owner, _ = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    assert camp_mod.pick_number(owner.id, "rep", None, simulate_ok=True) is not None


def test_a_local_number_still_wins_when_both_are_real(account):
    owner, _ = account
    number(owner.id, "+14406642753")
    local = number(owner.id, "+18655551234")
    lead = Lead(owner_id=owner.id, name="L", phone="+18655559999",
                phone_e164="+18655559999")
    db.session.add(lead)
    db.session.commit()
    assert camp_mod.pick_number(owner.id, "rep", lead,
                                simulate_ok=False).id == local.id


# ------------------------------------------------------- the setup screen
def test_the_screen_offers_only_numbers_that_can_dial(account):
    owner, client = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    number(owner.id, "+14406642753")
    body = client.get("/dialer/setup/11").get_data(as_text=True)
    picker = body[body.index('name="from_number_id"'):]
    picker = picker[:picker.index("</select>")]
    assert "664-2753" in picker
    assert "555-0101" not in picker, "a sample number must not be offerable"


def test_the_screen_names_the_unusable_ones_rather_than_hiding_them(account):
    """Silently dropping them would leave him wondering where they went."""
    owner, client = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    number(owner.id, "+14406642753")
    body = client.get("/dialer/setup/11").get_data(as_text=True)
    assert "Not usable" in body
    assert "865) 555-0101" in body


def test_choosing_a_sample_number_is_refused_with_a_reason(account, monkeypatch):
    """The suite runs in practice mode, where a sample number is allowed on
    purpose, so this one has to ask what happens on a real call."""
    from dialer.providers import registry
    monkeypatch.setattr(registry, "simulating", lambda s: False)
    owner, client = account
    fake = number(owner.id, "+18655550101", sid="PNdemo0101")
    number(owner.id, "+14406642753")
    r = client.post("/dialer/test-call", follow_redirects=True,
                    data={"to_number": "+14235550147",
                          "from_number_id": fake.id})
    body = r.get_data(as_text=True)
    assert "sample data" in body


def test_another_accounts_number_cannot_be_borrowed(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = number(other.id, "+12165551234")
    r = client.post("/dialer/test-call",
                    data={"to_number": "+14235550147",
                          "from_number_id": theirs.id})
    assert r.status_code == 403


def test_no_callable_number_says_so_instead_of_dialling_nothing(account, monkeypatch):
    from dialer.providers import registry
    monkeypatch.setattr(registry, "simulating", lambda s: False)
    owner, client = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    r = client.post("/dialer/test-call", follow_redirects=True,
                    data={"to_number": "+14235550147"})
    assert "No number on your account" in r.get_data(as_text=True)


# ------------------------------------------- the desk phone's caller ID
def test_the_phone_offers_a_caller_id_to_pin(account):
    """There was no control at all, so the only way to change what shows on
    the far end was to park numbers until the automatic pick ran out of
    choices."""
    owner, client = account
    number(owner.id, "+14406642753")
    body = client.get("/dialer/phone").get_data(as_text=True)
    assert 'id="ph-from"' in body
    assert "664-2753" in body


def test_the_phone_never_offers_a_sample_number(account):
    owner, client = account
    number(owner.id, "+18655550101", sid="PNdemo0101")
    body = client.get("/dialer/phone").get_data(as_text=True)
    picker = body.split('id="ph-from"')[1].split("</select>")[0] \
        if 'id="ph-from"' in body else ""
    assert "555-0101" not in picker


def test_a_manual_dial_uses_the_number_the_rep_pinned(account):
    owner, client = account
    number(owner.id, "+14406642753")
    pinned = number(owner.id, "+18655551212")
    r = client.post("/dialer/call/manual", json={"to": "+14235550147",
                                                 "from_number_id": pinned.id})
    assert r.status_code == 200, r.get_data(as_text=True)
    from dialer.models import Call
    call = Call.query.filter_by(account_id=owner.id).order_by(
        Call.id.desc()).first()
    assert call.from_number == "+18655551212"


def test_a_manual_dial_cannot_borrow_another_accounts_number(account, ctx):
    owner, client = account
    number(owner.id, "+14406642753")
    other = make_user(name="Else", email="z@n.test", dialer=True)
    theirs = number(other.id, "+12165551234")
    r = client.post("/dialer/call/manual", json={"to": "+14235550147",
                                                 "from_number_id": theirs.id})
    assert r.status_code == 403


def test_with_no_pin_it_still_picks_the_closest_area_code(account):
    owner, client = account
    number(owner.id, "+14406642753")
    local = number(owner.id, "+14235559999")
    client.post("/dialer/call/manual", json={"to": "+14235550147"})
    from dialer.models import Call
    call = Call.query.filter_by(account_id=owner.id).order_by(
        Call.id.desc()).first()
    assert call.from_number == local.e164
