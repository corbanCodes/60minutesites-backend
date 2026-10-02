"""Telling two near-identical playbooks and agents apart.

A real account ended up holding "NapkinAds Official Playbook", "NapkinAds —
venue calling", "NapkinAds Official Playbook agent" and "NapkinAds venue
caller". Nothing on either list screen said which agent read which script,
so the only way to find out was to open all four, and the obvious guess —
that the row marked Default is the one the AI follows — is wrong.

Three things are proved here: each list names the other side of the link,
the default can be moved from the list it is shown on, and moving it does
not change a single word any agent says.
"""
import pytest

from app import db
from dialer.models import AiAgent, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.elevenlabs_default_voice_id = "v1"
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def make_book(owner_id, name, default=False):
    pb = Playbook(account_id=owner_id, name=name, is_default=default,
                  steps_json="[]", questions_json="[]", objections_json="[]")
    db.session.add(pb)
    db.session.commit()
    return pb


def make_agent(owner_id, name, playbook_id=None, active=True):
    a = AiAgent(account_id=owner_id, name=name, direction="outbound",
                playbook_id=playbook_id, active=active)
    db.session.add(a)
    db.session.commit()
    return a


# ------------------------------------------- the agent list names the script
def test_the_agent_list_says_which_script_each_agent_reads(account):
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook", default=True)
    new = make_book(owner.id, "NapkinAds — venue calling")
    make_agent(owner.id, "NapkinAds Official Playbook agent", old.id)
    make_agent(owner.id, "NapkinAds venue caller", new.id)

    body = client.get("/dialer/agents").get_data(as_text=True)

    assert "Script it reads" in body
    assert f'/dialer/playbooks/{new.id}' in body, (
        "the venue caller's script must be reachable from its own row")
    assert f'/dialer/playbooks/{old.id}' in body


def test_an_agent_with_no_script_is_called_out(account):
    """Silent on the old screen, and the agent still dials. It talks, just
    not from anything the customer wrote."""
    owner, client = account
    make_agent(owner.id, "Half-built", None)
    assert "No script" in client.get("/dialer/agents").get_data(as_text=True)


# ---------------------------------------- the script list names its readers
def test_the_playbook_list_says_which_agents_read_it(account):
    owner, client = account
    new = make_book(owner.id, "NapkinAds — venue calling")
    a = make_agent(owner.id, "NapkinAds venue caller", new.id)

    body = client.get("/dialer/playbooks").get_data(as_text=True)

    assert "NapkinAds venue caller" in body
    assert f'/dialer/agents/{a.id}' in body


def test_a_script_nothing_reads_says_so(account):
    owner, client = account
    make_book(owner.id, "Qualify and transfer")
    assert "No agent" in client.get("/dialer/playbooks").get_data(as_text=True)


def test_an_agent_that_is_switched_off_is_marked_as_such(account):
    """Otherwise the list reads as though two agents are both working the
    same script, which is the thing it exists to disambiguate."""
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook")
    make_agent(owner.id, "NapkinAds Official Playbook agent", old.id,
               active=False)
    assert "Off" in client.get("/dialer/playbooks").get_data(as_text=True)


# ------------------------------------------------------- moving the default
def test_the_default_can_be_moved_from_the_playbook_list(account):
    """The route existed but was only ever reachable from one step of the
    wizard, so from this screen the first row ever created held it for good."""
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook", default=True)
    new = make_book(owner.id, "NapkinAds — venue calling")

    r = client.post(f"/dialer/playbooks/{new.id}/default",
                    data={"back": "/dialer/playbooks"}, follow_redirects=True)

    assert r.status_code == 200
    assert db.session.get(Playbook, new.id).is_default is True
    assert db.session.get(Playbook, old.id).is_default is False


def test_pressing_it_comes_back_to_the_list_it_was_pressed_on(account):
    owner, client = account
    make_book(owner.id, "One", default=True)
    two = make_book(owner.id, "Two")
    r = client.post(f"/dialer/playbooks/{two.id}/default",
                    data={"back": "/dialer/playbooks"})
    assert r.headers["Location"].endswith("/dialer/playbooks")


def test_without_a_back_field_it_still_returns_to_the_wizard(account):
    """Step 9 posts no `back`, and that path must keep working."""
    owner, client = account
    make_book(owner.id, "One", default=True)
    two = make_book(owner.id, "Two")
    r = client.post(f"/dialer/playbooks/{two.id}/default")
    assert "/dialer/setup" in r.headers["Location"]


def test_the_button_is_offered_on_every_script_except_the_current_one(account):
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook", default=True)
    new = make_book(owner.id, "NapkinAds — venue calling")

    body = client.get("/dialer/playbooks").get_data(as_text=True)

    assert f'/dialer/playbooks/{new.id}/default' in body
    assert f'/dialer/playbooks/{old.id}/default' not in body, (
        "offering to re-pick the one already picked is a dead control")


def test_moving_the_default_changes_nothing_any_agent_says(account):
    """The trap. The mark looks like it selects the live script, and it does
    not -- an agent reads whichever playbook its own page points at. If this
    ever starts repointing agents, the screen has quietly become a loaded gun.
    """
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook", default=True)
    new = make_book(owner.id, "NapkinAds — venue calling")
    stays = make_agent(owner.id, "NapkinAds Official Playbook agent", old.id)

    client.post(f"/dialer/playbooks/{new.id}/default",
                data={"back": "/dialer/playbooks"}, follow_redirects=True)

    assert db.session.get(AiAgent, stays.id).playbook_id == old.id


def test_the_list_says_in_words_that_the_mark_does_not_steer_agents(account):
    owner, client = account
    make_book(owner.id, "One", default=True)
    body = client.get("/dialer/playbooks").get_data(as_text=True)
    assert "does not change what an agent says" in body


# ------------------------------------------------- getting back to the guide
@pytest.mark.parametrize("url", ["/dialer/playbooks", "/dialer/agents"])
def test_the_setup_guide_is_reachable_from_the_list_screens(account, url):
    """Only the Calling home page linked to the wizard, so anyone who walked
    into a sub-page had no way back to it."""
    owner, client = account
    assert "/dialer/setup" in client.get(url).get_data(as_text=True)


def test_the_setup_guide_is_reachable_from_an_agent_s_own_page(account):
    owner, client = account
    a = make_agent(owner.id, "NapkinAds venue caller")
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "/dialer/setup" in body


def test_the_setup_guide_is_reachable_from_a_script_s_own_page(account):
    owner, client = account
    pb = make_book(owner.id, "NapkinAds — venue calling")
    body = client.get(f"/dialer/playbooks/{pb.id}").get_data(as_text=True)
    assert "/dialer/setup" in body


# ------------------------------------------------- the installed guide itself
def test_the_installed_guide_and_its_agent_point_at_each_other(account):
    """His actual question: did the install wire itself up, or is there a
    dropdown he still has to go and change? Nothing to change."""
    owner, client = account
    client.post("/dialer/playbooks/napkin", data={"transfer_to": ""},
                follow_redirects=True)

    pb = Playbook.query.filter_by(account_id=owner.id,
                                  name="NapkinAds — venue calling").one()
    agent = AiAgent.query.filter_by(account_id=owner.id,
                                    name="NapkinAds venue caller").one()
    assert agent.playbook_id == pb.id
    assert agent.active is True


def test_the_agent_list_distinguishes_the_installed_pair_from_an_older_one(
        account):
    """Both are called NapkinAds something. The script column is the only
    thing on the screen that separates them."""
    owner, client = account
    old = make_book(owner.id, "NapkinAds Official Playbook", default=True)
    make_agent(owner.id, "NapkinAds Official Playbook agent", old.id,
               active=False)
    client.post("/dialer/playbooks/napkin", data={"transfer_to": ""},
                follow_redirects=True)

    body = client.get("/dialer/agents").get_data(as_text=True)

    assert "NapkinAds Official Playbook" in body
    assert "NapkinAds — venue calling" in body
