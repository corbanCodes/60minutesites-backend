"""Who speaks first, and whose words the agent uses.

Two things made a working call feel unusable:

* The agent started talking the instant the line opened, over the "hello".
  The field offered for this is first_message, which ElevenLabs SPEAKS
  VERBATIM -- so instructions typed into it, brackets and all, were read
  aloud to the prospect.
* The assembled instructions were read-only. On your own product that is
  not a safety feature, it is a wall.
"""
import pytest

from app import db
from dialer.agents import build_prompt, sync_agent
from dialer.models import AiAgent, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def agent(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    a = AiAgent(account_id=owner.id, name="Q", direction="outbound")
    db.session.add(a)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, a, s, client


# ------------------------------------------------------- who speaks first
def test_waiting_leaves_the_opening_line_empty(agent):
    """An empty first_message is how ElevenLabs is told to wait. Helpfully
    filling it in is exactly what stopped the agent ever waiting."""
    owner, a, s, client = agent
    a.opening_mode = "wait"
    a.first_message = "Hi, I'm an AI assistant calling from NapkinAds."
    db.session.commit()

    sync_agent(a, s)

    assert db.session.get(AiAgent, a.id).first_message == ""


def test_waiting_tells_the_agent_why_in_the_prompt(agent):
    owner, a, s, client = agent
    a.opening_mode = "wait"
    db.session.commit()
    prompt = build_prompt(a, s)
    assert "Say NOTHING when the call connects" in prompt
    assert "hello" in prompt


def test_speaking_first_still_fills_the_disclosure_in(agent):
    owner, a, s, client = agent
    a.opening_mode = "speak"
    a.first_message = ""
    db.session.commit()
    sync_agent(a, s)
    assert "NapkinAds" in db.session.get(AiAgent, a.id).first_message


def test_the_page_warns_that_the_opening_line_is_read_aloud(agent):
    """He typed instructions in brackets and heard them read out."""
    owner, a, s, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "word for word" in body
    assert "notes in brackets" in body


# ------------------------------------------------------ editing the prompt
def test_an_override_replaces_the_assembled_instructions(agent):
    owner, a, s, client = agent
    a.prompt_override = "You are a pirate. Say arr."
    s.ai_disclosure_enabled = False
    db.session.commit()
    assert build_prompt(a, s) == "You are a pirate. Say arr."


def test_the_disclosure_still_follows_an_override_while_it_is_switched_on(agent):
    owner, a, s, client = agent
    a.prompt_override = "You are a pirate."
    s.ai_disclosure_enabled = True
    db.session.commit()
    prompt = build_prompt(a, s)
    assert prompt.startswith("You are a pirate.")
    assert "Disclosure" in prompt


def test_an_empty_override_means_the_assembled_one(agent):
    owner, a, s, client = agent
    a.prompt_override = "   "
    db.session.commit()
    assert "# Who you are" in build_prompt(a, s)


def test_the_instructions_box_is_on_the_page(agent):
    owner, a, s, client = agent
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert 'name="prompt_override"' in body


def test_saving_instructions_does_not_blank_the_rest_of_the_agent(agent):
    """The instructions form posts on its own, so it must not wipe every
    field it never showed."""
    owner, a, s, client = agent
    a.name = "Keep me"
    a.persona = "Keep this too"
    a.max_duration_seconds = 300
    db.session.commit()

    client.post(f"/dialer/agents/{a.id}", follow_redirects=True,
                data={"keep": "1", "prompt_override": "My own words."})

    a = db.session.get(AiAgent, a.id)
    assert a.prompt_override == "My own words."
    assert a.name == "Keep me"
    assert a.persona == "Keep this too"
    assert a.max_duration_seconds == 300


# ------------------------------------------------------- transfer style
def test_the_transfer_wording_follows_the_chosen_style(agent):
    owner, a, s, client = agent
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer on a yes.")
    db.session.add(pb)
    db.session.flush()
    a.playbook_id = pb.id

    a.transfer_style = "natural"
    db.session.commit()
    assert "one second" in build_prompt(a, s)

    a.transfer_style = "explicit"
    db.session.commit()
    assert "put you through to a colleague" in build_prompt(a, s)


def test_a_custom_transfer_line_is_used_exactly(agent):
    owner, a, s, client = agent
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer on a yes.")
    db.session.add(pb)
    db.session.flush()
    a.playbook_id = pb.id
    a.transfer_style = "custom"
    a.transfer_line = "Great, hang on one sec."
    db.session.commit()
    assert "Great, hang on one sec." in build_prompt(a, s)


def test_a_custom_style_with_no_line_falls_back_rather_than_saying_nothing(agent):
    owner, a, s, client = agent
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer on a yes.")
    db.session.add(pb)
    db.session.flush()
    a.playbook_id = pb.id
    a.transfer_style = "custom"
    a.transfer_line = ""
    db.session.commit()
    assert "one short line" in build_prompt(a, s).lower()
