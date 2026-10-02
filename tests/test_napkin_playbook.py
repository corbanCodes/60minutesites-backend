"""NapkinAds' own guide, installed as something this product can run.

Their document is a specification: it mixes what the AI says with what the
system must do afterwards. The saying becomes a playbook, the doing is
machinery that already exists, and the prompt only has to make the agent
report outcomes in a shape that machinery reads.
"""
import pytest

from app import db
from dialer import napkin
from dialer.agents import build_prompt
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


def install(client, transfer_to=""):
    return client.post("/dialer/playbooks/napkin", follow_redirects=True,
                       data={"transfer_to": transfer_to})


# ------------------------------------------------------- what it installs
def test_it_installs_a_playbook_and_a_working_agent(account):
    owner, client = account
    install(client)
    pb = Playbook.query.filter_by(account_id=owner.id).first()
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    assert pb and agent
    assert agent.playbook_id == pb.id
    assert agent.elevenlabs_agent_id, "an agent that never synced cannot call"


def test_it_waits_for_hello_like_every_other_new_agent(account):
    owner, client = account
    install(client)
    assert AiAgent.query.filter_by(account_id=owner.id).first().opening_mode == "wait"


def test_the_transfer_destination_is_taken_from_the_form(account):
    owner, client = account
    install(client, transfer_to="+14235550147")
    assert AiAgent.query.filter_by(
        account_id=owner.id).first().transfer_to_number == "+14235550147"


def test_it_adds_rather_than_replaces(account):
    """He has real work on this account. Installing a template must not
    touch it."""
    owner, client = account
    mine = Playbook(account_id=owner.id, name="My own", is_default=True,
                    steps_json="[]", questions_json="[]", objections_json="[]")
    db.session.add(mine)
    db.session.commit()

    install(client)

    names = {p.name for p in Playbook.query.filter_by(account_id=owner.id)}
    assert "My own" in names
    assert db.session.get(Playbook, mine.id).is_default is True, \
        "an existing default must not be taken over"


# ------------------------------------------- the rules that matter to them
def test_the_agent_is_told_to_transfer_on_reaching_anyone_who_decides(account):
    owner, client = account
    install(client)
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    prompt = build_prompt(agent, get_settings(owner.id))
    assert "INSTANT a decision maker is on the line" in prompt
    assert "Do NOT ask whether they are interested first" in prompt


def test_the_agent_is_told_not_to_re_introduce_itself_to_the_manager(account):
    """Their single loudest requirement: the next voice the manager hears
    is a salesperson, not more AI."""
    owner, client = account
    install(client)
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    prompt = build_prompt(agent, get_settings(owner.id))
    assert "should be a salesperson, not more of you" in prompt


def test_it_stays_silent_while_the_manager_is_fetched(account):
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "stay silent until a new voice speaks" in prompt


def test_it_is_told_to_pin_down_a_clock_time(account):
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "Would around 4 be a good time to try?" in prompt
    assert "Accept the second answer" in prompt


def test_it_captures_the_managers_name_for_next_time(account):
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "{name}" in prompt, "it should reuse a name it already has"
    assert "decision maker's name" in prompt


def test_staff_saying_no_is_not_the_venue_saying_no(account):
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "Only the decision maker can decline" in prompt


def test_it_is_forbidden_from_pitching(account):
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "Never give a sales pitch" in prompt


# ---------------------------------------------------------- the wording
def test_the_company_name_is_substituted_not_left_as_a_placeholder(account):
    """A placeholder left in a prompt is a placeholder read out loud."""
    owner, client = account
    install(client)
    pb = Playbook.query.filter_by(account_id=owner.id).first()
    blob = pb.steps_json + pb.objections_json
    assert "{ai_name}" not in blob
    assert "NapkinAds" in blob


def test_the_opening_asks_for_the_manager_and_nothing_else(account):
    owner, client = account
    install(client)
    pb = Playbook.query.filter_by(account_id=owner.id).first()
    assert pb.steps[0]["say"] == "Hi, can I speak with the manager or owner?"


def test_the_button_is_on_the_script_step(account):
    owner, client = account
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert "/dialer/playbooks/napkin" in body
    assert "Install the NapkinAds guide" in body


def test_the_company_placeholder_never_survives_into_the_prompt(account):
    """A placeholder left in a prompt is a placeholder read out loud, and
    the behaviour rules were not being substituted at all."""
    owner, client = account
    install(client)
    prompt = build_prompt(AiAgent.query.filter_by(account_id=owner.id).first(),
                          get_settings(owner.id))
    assert "{ai_name}" not in prompt
    assert "NapkinAds" in prompt
