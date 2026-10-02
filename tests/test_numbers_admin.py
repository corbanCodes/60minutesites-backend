"""Naming a number, and getting rid of one that was never real.

Three things broke at once on a real account holding four numbers:

* Two sample numbers could not be removed. Release asks Twilio to give the
  number back, the seeder's SIDs are invented, and Twilio rejects a SID it
  never issued. The error read like a billing problem, so the rows looked
  permanent.
* Two real numbers in the same area code were indistinguishable. Twilio names
  a number after itself, the label was not editable, and the subtitle fell
  back to a bare area code.
* That bare area code was "440" because the state table only covered the
  states someone had written a calling rule for. Ohio was not in it.

The last one is the one with teeth, and the reason the guard test at the
bottom exists.
"""
import pytest

from app import db
from dialer import tz
from dialer.compliance import SEED_STATES
from dialer.demo import DEMO_PREFIX
from dialer.models import PhoneNumber
from dialer.routes_ui import _is_local_only
from dialer.settings_store import get_settings
from tests.conftest import make_user

REAL_SID = "PN" + "a1b2c3d4" * 4          # PN + 32 hex, the shape Twilio issues


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def add_number(owner_id, e164, sid=REAL_SID, name=None, pool="rep"):
    n = PhoneNumber(account_id=owner_id, e164=e164, twilio_sid=sid,
                    pool=pool, state="active",
                    friendly_name=e164 if name is None else name,
                    area_code=tz.area_code(e164), region=tz.state_for(e164))
    db.session.add(n)
    db.session.commit()
    return n


# -------------------------------------------------- what counts as not real
def test_a_seeded_number_is_local_only(account):
    owner, _ = account
    n = add_number(owner.id, "+18655550101", sid="PNdemo0101",
                   name=DEMO_PREFIX + "Knoxville 865 (reps)")
    assert _is_local_only(n) is True


def test_a_renamed_sample_number_is_still_local_only(account):
    """Matching on the "Demo: " prefix alone would let a rename strand the
    row permanently, which is the trap this whole fix exists to avoid."""
    owner, _ = account
    n = add_number(owner.id, "+18655550101", sid="PNdemo0101",
                   name="My main line")
    assert _is_local_only(n) is True


def test_a_row_with_no_sid_at_all_is_local_only(account):
    owner, _ = account
    assert _is_local_only(add_number(owner.id, "+18655550101", sid="")) is True


def test_a_genuinely_purchased_number_is_not_local_only(account):
    owner, _ = account
    assert _is_local_only(add_number(owner.id, "+14406642753")) is False


# ----------------------------------------------------------- removing them
def test_releasing_a_sample_number_deletes_it_without_calling_twilio(account):
    """The bug. The provider is replaced with one that fails loudly, so if
    this test passes, Twilio was genuinely never asked."""
    owner, client = account
    n = add_number(owner.id, "+18655550101", sid="PNdemo0101",
                   name=DEMO_PREFIX + "Knoxville 865 (reps)")
    from dialer.providers import registry

    def explode(settings):
        raise AssertionError("Twilio must not be called for a sample number")

    original = registry.telephony
    registry.telephony = explode
    try:
        r = client.post(f"/dialer/numbers/{n.id}/release",
                        follow_redirects=True)
        assert r.status_code == 200
    finally:
        registry.telephony = original

    assert PhoneNumber.query.filter_by(account_id=owner.id).count() == 0


def test_releasing_a_sample_number_says_nothing_was_charged(account):
    owner, client = account
    n = add_number(owner.id, "+16155550102", sid="PNdemo0102",
                   name=DEMO_PREFIX + "Nashville 615 (AI)")
    body = client.post(f"/dialer/numbers/{n.id}/release",
                       follow_redirects=True).get_data(as_text=True)
    assert "sample data" in body


def test_a_real_number_still_goes_through_twilio_to_be_released(account):
    """The safety the fix must not cost: a number someone pays for is only
    marked released after Twilio confirms it."""
    owner, client = account
    n = add_number(owner.id, "+14406642753")
    seen = {}
    from dialer.providers import registry
    original = registry.telephony

    class Stub:
        def release_number(self, sid):
            seen["sid"] = sid
            return {"ok": True}

    registry.telephony = lambda settings: Stub()
    try:
        client.post(f"/dialer/numbers/{n.id}/release", follow_redirects=True)
    finally:
        registry.telephony = original

    assert seen.get("sid") == REAL_SID
    assert db.session.get(PhoneNumber, n.id).state == "released"


def test_a_real_number_survives_twilio_refusing(account):
    owner, client = account
    n = add_number(owner.id, "+14406642753")
    from dialer.providers import registry
    original = registry.telephony

    class Stub:
        def release_number(self, sid):
            return {"ok": False, "error": "not found"}

    registry.telephony = lambda settings: Stub()
    try:
        client.post(f"/dialer/numbers/{n.id}/release", follow_redirects=True)
    finally:
        registry.telephony = original

    assert db.session.get(PhoneNumber, n.id).state == "active"


# ----------------------------------------------------------------- naming
def test_a_number_can_be_given_a_label(account):
    owner, client = account
    n = add_number(owner.id, "+14407455761")
    client.post(f"/dialer/numbers/{n.id}/name",
                data={"friendly_name": "AI calls out"}, follow_redirects=True)
    assert db.session.get(PhoneNumber, n.id).friendly_name == "AI calls out"


def test_the_label_input_is_on_the_page(account):
    owner, client = account
    add_number(owner.id, "+14407455761", name="AI calls out")
    body = client.get("/dialer/numbers").get_data(as_text=True)
    assert 'name="friendly_name"' in body
    assert "AI calls out" in body


def test_a_label_cannot_be_set_on_another_account_s_number(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = add_number(other.id, "+12165551234", name="theirs")
    r = client.post(f"/dialer/numbers/{theirs.id}/name",
                    data={"friendly_name": "mine now"})
    assert r.status_code == 403
    assert db.session.get(PhoneNumber, theirs.id).friendly_name == "theirs"


# ------------------------------------------------------------- area codes
def test_ohio_resolves_instead_of_showing_a_bare_area_code(account):
    assert tz.state_for("+14406642753") == "OH"
    assert tz.state_for("+14407455761") == "OH"


def test_every_state_with_a_calling_rule_has_its_area_codes_mapped():
    """The guard. _state_rule() returns None when a lead's area code is not in
    the table, so a rule for an unmapped state silently never fires. Adding a
    rule without the area codes would be a compliance hole that looks like
    nothing at all, and this is the only thing that would catch it."""
    ruled = {row[0] for row in SEED_STATES}
    mapped = set(tz.AREA_STATE.values())
    missing = sorted(ruled - mapped)
    assert not missing, (
        f"these states have a calling rule but no area codes, so the rule can "
        f"never fire: {missing}")


def test_the_area_code_table_covers_every_state():
    """Not strictly required today, but an unmapped state is a rule waiting to
    be written and silently ignored."""
    assert len(set(tz.AREA_STATE.values())) >= 51


def test_no_area_code_is_claimed_by_two_states():
    seen = {}
    for code, state in tz.AREA_STATE.items():
        assert code not in seen or seen[code] == state
        seen[code] = state
    assert all(len(c) == 3 and c.isdigit() for c in tz.AREA_STATE)
