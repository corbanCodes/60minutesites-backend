"""The agent editor: what it claims, and what it hides.

Four things made a decent-sounding call rough:

* The disclosure block announced it "cannot be removed". It can -- there is a
  checkbox on step 7 that governs it -- so the note was simply false, and
  being told you may not change your own product when you may is worse than
  the restriction would have been.
* An agent with no playbook attached said nothing about it, so the AI
  introduced itself and improvised while the script sat unused.
* The thinking model was a free-text box pre-filled with a name nobody chose.
* No voice previews, on the page where you choose the voice.
"""
import pytest

from app import db
from dialer.models import AiAgent, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def agent(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    pb = Playbook(account_id=owner.id, name="NapkinAds Official",
                  steps_json="[]", questions_json="[]", objections_json="[]")
    db.session.add(pb)
    db.session.flush()
    a = AiAgent(account_id=owner.id, name="Q", direction="outbound")
    db.session.add(a)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, a, pb, client


# ----------------------------------------------------- the disclosure note
def test_the_page_no_longer_claims_the_disclosure_is_unremovable(agent):
    owner, a, pb, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "cannot be removed" not in body


def test_it_says_where_the_switch_actually_is(agent):
    owner, a, pb, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "/dialer/setup/7" in body
    assert "Untick it there" in body


def test_turning_it_off_really_does_remove_it_from_the_prompt(agent):
    """The claim the page now makes has to be true."""
    from dialer.agents import build_prompt
    owner, a, pb, client = agent
    s = get_settings(owner.id)

    s.ai_disclosure_enabled = True
    db.session.commit()
    assert "Disclosure" in build_prompt(a, s)

    s.ai_disclosure_enabled = False
    db.session.commit()
    assert "Disclosure" not in build_prompt(a, s)


def test_the_checkbox_can_be_switched_off_and_stays_off(agent):
    owner, a, pb, client = agent
    client.post("/dialer/setup/compliance/save", follow_redirects=True,
                data={"ai_disclosure_name": "NapkinAds"})
    assert get_settings(owner.id).disclose_ai is False


# ------------------------------------------------------- an agent with no script
def test_an_agent_with_no_playbook_says_so_loudly(agent):
    owner, a, pb, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "No script attached" in body
    assert "improvise" in body


def test_the_warning_goes_once_a_script_is_attached(agent):
    owner, a, pb, client = agent
    a.playbook_id = pb.id
    db.session.commit()
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "No script attached" not in body


# ------------------------------------------------------------ the model
def test_the_model_is_a_list_with_an_honest_default(agent):
    owner, a, pb, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert 'id="ag-model"' in body
    assert "Let ElevenLabs choose" in body


def test_a_model_elevenlabs_set_is_kept_rather_than_silently_dropped(agent):
    """A select that does not contain the current value would blank it on
    the next save, quietly changing the agent's brain."""
    owner, a, pb, client = agent
    a.llm_model = "some-model-we-have-never-listed"
    db.session.commit()
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "some-model-we-have-never-listed" in body


# ------------------------------------------------------------- previews
def test_voices_can_be_heard_where_they_are_chosen(agent):
    owner, a, pb, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "voiceplay.js" in body


# ---------------------------------------------------------- finding it
def test_the_wizard_links_to_the_agent_editor(agent):
    """It existed only at a URL nobody is given."""
    owner, a, pb, client = agent
    assert f"/dialer/agents/{a.id}" in client.get(
        "/dialer/setup/12").get_data(as_text=True)
    assert "/dialer/agents" in client.get(
        "/dialer/setup/9").get_data(as_text=True)
