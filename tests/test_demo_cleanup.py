"""Getting the sample data back out again.

The seeder had build and clear routes from the start, but nothing in any
template linked to either, so demo content could go into an account and never
come out. That bit: two fake phone numbers with made-up Twilio SIDs sat in a
real setup screen next to a number the owner had actually paid for, and he had
no way to tell which was which or to remove them.

The risk is not cosmetic. A campaign that picks a demo number tries to dial
from a SID Twilio has never heard of.
"""
import pytest

from app import Lead, db
from dialer.demo import DEMO_PREFIX, DEMO_TAG, clear_demo, demo_present
from dialer.models import PhoneNumber
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def seed_two_demo_numbers(owner_id):
    db.session.add(PhoneNumber(
        account_id=owner_id, e164="+18655550101", twilio_sid="PNdemo0101",
        friendly_name=DEMO_PREFIX + "Knoxville 865 (reps)", pool="rep",
        state="active", area_code="865"))
    db.session.add(PhoneNumber(
        account_id=owner_id, e164="+16155550102", twilio_sid="PNdemo0102",
        friendly_name=DEMO_PREFIX + "Nashville 615 (AI)", pool="ai",
        state="active", area_code="615"))
    db.session.commit()


def seed_a_real_number(owner_id):
    """A number the owner actually bought. Shaped like the production row:
    Twilio names a number after itself, so friendly_name is the E.164."""
    db.session.add(PhoneNumber(
        account_id=owner_id, e164="+14406642753",
        twilio_sid="PN" + "a" * 32, friendly_name="+14406642753",
        pool="rep", state="active", area_code="440"))
    db.session.commit()


# ------------------------------------------------------------ the detector
def test_a_clean_account_is_not_told_it_has_sample_data(account):
    owner, _ = account
    assert demo_present(owner.id)["any"] is False


def test_demo_numbers_are_noticed(account):
    owner, _ = account
    seed_two_demo_numbers(owner.id)
    d = demo_present(owner.id)
    assert d["any"] is True
    assert d["numbers"] == 2


def test_a_real_number_alone_never_triggers_the_banner(account):
    """The whole banner is worthless if it cries wolf at somebody's own
    paid-for number."""
    owner, _ = account
    seed_a_real_number(owner.id)
    d = demo_present(owner.id)
    assert d["numbers"] == 0
    assert d["any"] is False


def test_demo_leads_are_noticed_on_their_tag(account):
    owner, _ = account
    make_lead(owner_id=owner.id, name="Demo venue", tags=DEMO_TAG)
    db.session.commit()
    assert demo_present(owner.id)["leads"] == 1


# -------------------------------------------------------------- the banner
def test_the_calling_page_offers_to_remove_sample_data(account):
    owner, client = account
    seed_two_demo_numbers(owner.id)
    body = client.get("/dialer/").get_data(as_text=True)
    assert "Remove sample data" in body
    assert "/dialer/demo/clear" in body


def test_the_calling_page_stays_quiet_with_nothing_to_remove(account):
    owner, client = account
    seed_a_real_number(owner.id)
    body = client.get("/dialer/").get_data(as_text=True)
    assert "Remove sample data" not in body


# --------------------------------------------------------------- the purge
def test_clearing_removes_demo_numbers_and_keeps_the_real_one(account):
    """The one that matters. Two fakes and one real number go in; the real
    one, with the owner's money behind it, comes out untouched."""
    owner, _ = account
    seed_two_demo_numbers(owner.id)
    seed_a_real_number(owner.id)
    assert PhoneNumber.query.filter_by(account_id=owner.id).count() == 3

    clear_demo(owner.id)
    db.session.commit()

    left = PhoneNumber.query.filter_by(account_id=owner.id).all()
    assert [n.e164 for n in left] == ["+14406642753"]
    assert demo_present(owner.id)["any"] is False


def test_clearing_keeps_real_leads(account):
    owner, _ = account
    make_lead(owner_id=owner.id, name="Demo venue", tags=DEMO_TAG)
    make_lead(owner_id=owner.id, name="A real prospect", tags="")
    db.session.commit()

    clear_demo(owner.id)
    db.session.commit()

    names = [l.name for l in Lead.query.filter_by(owner_id=owner.id).all()]
    assert names == ["A real prospect"]


def test_clearing_never_reaches_another_account(account, ctx):
    """Demo rows are matched by tag and name prefix, which are not unique
    across accounts. The account filter is what keeps this safe."""
    owner, _ = account
    other = make_user(name="Someone else", email="x@n.test", dialer=True)
    seed_two_demo_numbers(owner.id)
    seed_two_demo_numbers(other.id)

    clear_demo(owner.id)
    db.session.commit()

    assert PhoneNumber.query.filter_by(account_id=owner.id).count() == 0
    assert PhoneNumber.query.filter_by(account_id=other.id).count() == 2


def test_the_clear_route_works_end_to_end(account):
    owner, client = account
    seed_two_demo_numbers(owner.id)
    seed_a_real_number(owner.id)

    r = client.post("/dialer/demo/clear", follow_redirects=True)
    assert r.status_code == 200

    left = [n.e164 for n in PhoneNumber.query.filter_by(account_id=owner.id)]
    assert left == ["+14406642753"]
