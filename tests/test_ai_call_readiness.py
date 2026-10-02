"""An AI call needs more than an agent, and the errors never said which part.

"The call didn't go out: Document with id not found." That is ElevenLabs
saying it has no record of the phone number it was asked to call from. The
number is imported into ElevenLabs only when it is bought or moved pools, so
a number that existed before ElevenLabs was connected was never sent over,
and the call failed naming a document nobody has heard of.
"""
import pytest

from app import db
from dialer.models import AiAgent, PhoneNumber, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user

REAL_SID = "PN" + "beef1234" * 4


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18174032179"
    s.enforce_window = False
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def ai_number(owner_id, e164="+14409015866", el_id=""):
    n = PhoneNumber(account_id=owner_id, e164=e164, twilio_sid=REAL_SID,
                    pool="ai", state="active", area_code=e164[2:5],
                    elevenlabs_phone_id=el_id)
    db.session.add(n)
    db.session.commit()
    return n


def synced_agent(owner_id):
    pb = Playbook(account_id=owner_id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]")
    db.session.add(pb)
    db.session.flush()
    a = AiAgent(account_id=owner_id, name="Q", direction="outbound",
                playbook_id=pb.id, elevenlabs_agent_id="agent_abc",
                active=True)
    db.session.add(a)
    db.session.commit()
    return a


# ------------------------------------------------------ the missing link
def test_a_number_elevenlabs_has_never_seen_gets_imported_on_the_way(account):
    """Rather than failing with a message about a document."""
    owner, client = account
    n = ai_number(owner.id, el_id="")
    a = synced_agent(owner.id)

    client.post("/dialer/test-call", follow_redirects=True,
                data={"to_number": "+14235550147", "agent_id": a.id,
                      "from_number_id": n.id})

    assert db.session.get(PhoneNumber, n.id).elevenlabs_phone_id, \
        "the number was never sent to ElevenLabs"


def test_a_number_already_known_is_not_re_imported(account):
    owner, client = account
    n = ai_number(owner.id, el_id="pn_existing")
    a = synced_agent(owner.id)
    client.post("/dialer/test-call", follow_redirects=True,
                data={"to_number": "+14235550147", "agent_id": a.id,
                      "from_number_id": n.id})
    assert db.session.get(PhoneNumber, n.id).elevenlabs_phone_id == "pn_existing"


# --------------------------------------------- saying which part is missing
def test_an_unsynced_agent_says_so_and_says_where_to_fix_it(account):
    owner, client = account
    ai_number(owner.id, el_id="pn_1")
    a = synced_agent(owner.id)
    a.elevenlabs_agent_id = ""
    db.session.commit()

    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": "+14235550147",
                             "agent_id": a.id}).get_data(as_text=True)
    assert "has not synced" in body
    assert "Try the sync again" in body


def test_no_ai_pool_number_explains_the_pools(account):
    """"A number cannot serve both" is the part nobody guesses."""
    owner, client = account
    db.session.add(PhoneNumber(account_id=owner.id, e164="+14406642753",
                               twilio_sid=REAL_SID, pool="rep",
                               state="active", area_code="440"))
    a = synced_agent(owner.id)
    db.session.commit()

    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": "+14235550147",
                             "agent_id": a.id}).get_data(as_text=True)
    assert "AI pool" in body
    assert "cannot serve both" in body


def test_a_plain_ring_test_needs_none_of_this(account):
    """The no-AI path must not inherit the AI lane's requirements."""
    owner, client = account
    db.session.add(PhoneNumber(account_id=owner.id, e164="+14406642753",
                               twilio_sid=REAL_SID, pool="rep",
                               state="active", area_code="440"))
    db.session.commit()
    body = client.post("/dialer/test-call", follow_redirects=True,
                       data={"to_number": "+14235550147"}).get_data(as_text=True)
    for phrase in ("has not synced", "AI pool", "ElevenLabs"):
        assert phrase not in body or "didn't go out" not in body
