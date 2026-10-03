"""Building the agent, which nothing ever offered to do.

A voice picked on step 8, a playbook written on step 9, ElevenLabs connected
on step 6, a results webhook created: everything an AI agent is made of was
on the account, and no screen in the setup assembled them. So the test call's
"what should happen when you answer?" only ever said "Just ring my phone, no
AI", on a product whose whole point is the AI.
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
    s.ai_callback_number = "+18174032179"
    s.elevenlabs_default_voice_id = "voice_charlie"
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def playbook(owner_id, name="NapkinAds Official", default=True, transfer="Transfer on a yes."):
    pb = Playbook(account_id=owner_id, name=name, is_default=default,
                  steps_json='[{"title":"Open","say":"Hi."}]',
                  questions_json="[]", objections_json="[]",
                  transfer_criteria=transfer)
    db.session.add(pb)
    db.session.commit()
    return pb


# ---------------------------------------------------------- building one
def test_one_press_produces_a_working_agent(account):
    owner, client = account
    pb = playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    agents = AiAgent.query.filter_by(account_id=owner.id).all()
    assert len(agents) == 1
    a = agents[0]
    assert a.playbook_id == pb.id
    assert a.voice_id == "voice_charlie"
    assert a.active is True


def test_it_is_synced_so_it_can_actually_be_dialled(account):
    """An agent that exists only in our database cannot answer a phone."""
    owner, client = account
    playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    a = AiAgent.query.filter_by(account_id=owner.id).first()
    assert a.elevenlabs_agent_id, "never reached ElevenLabs"
    assert not a.last_sync_error


def test_it_takes_the_default_playbook_not_just_the_first(account):
    owner, client = account
    playbook(owner.id, name="Old one", default=False)
    chosen = playbook(owner.id, name="The one reps read", default=True)
    client.post("/dialer/agents/quick", follow_redirects=True)
    assert AiAgent.query.filter_by(
        account_id=owner.id).first().playbook_id == chosen.id


def test_a_sample_playbook_is_never_what_it_builds_from(account):
    """A live agent reading demo wording is discovered out loud."""
    owner, client = account
    from dialer.demo import DEMO_PREFIX
    playbook(owner.id, name=DEMO_PREFIX + "Sample", default=True)
    mine = playbook(owner.id, name="Mine", default=False)
    client.post("/dialer/agents/quick", follow_redirects=True)
    assert AiAgent.query.filter_by(
        account_id=owner.id).first().playbook_id == mine.id


def test_the_message_says_where_a_qualified_call_will_land(account):
    owner, client = account
    playbook(owner.id)
    body = client.post("/dialer/agents/quick",
                       follow_redirects=True).get_data(as_text=True)
    assert "8174032179" in body


def test_with_no_transfer_number_it_says_so_rather_than_implying_one(account):
    owner, client = account
    s = get_settings(owner.id)
    s.ai_callback_number, s.transfer_number = "", ""
    s.transfer_mode = "browser"
    db.session.commit()
    playbook(owner.id)
    body = client.post("/dialer/agents/quick",
                       follow_redirects=True).get_data(as_text=True)
    assert "not hand over" in body


# ---------------------------------------------------------- refusing early
def test_no_playbook_means_a_clear_refusal(account):
    owner, client = account
    body = client.post("/dialer/agents/quick",
                       follow_redirects=True).get_data(as_text=True)
    assert "playbook on step 9" in body
    assert AiAgent.query.filter_by(account_id=owner.id).count() == 0


# ------------------------------------------------------------- the button
def test_the_button_is_offered_when_there_is_no_agent(account):
    owner, client = account
    playbook(owner.id)
    body = client.get("/dialer/setup/12").get_data(as_text=True)
    assert "Build an AI agent from my script" in body
    assert "/dialer/agents/quick" in body


def test_the_button_goes_away_once_an_agent_exists(account):
    owner, client = account
    playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    body = client.get("/dialer/setup/12").get_data(as_text=True)
    assert "Build an AI agent from my script" not in body


def test_the_new_agent_is_selectable_on_the_test_call(account):
    """The entire point: it has to appear in that dropdown."""
    owner, client = account
    playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    body = client.get("/dialer/setup/12").get_data(as_text=True)
    picker = body.split('id="agent_id"')[1].split("</select>")[0]
    assert "NapkinAds Official agent" in picker


# ------------------------------------------- the schema ElevenLabs demands
def test_every_tool_field_satisfies_elevenlabs_validation():
    """ElevenLabs rejects the WHOLE agent unless each property in a tool's
    request body sets one of description, dynamic_variable,
    is_system_provided, constant_value or is_omitted. A bare
    {"type": "string"} failed the sync with a wall of schema paths and no
    agent, which is exactly how the build button fell over the first time."""
    from dialer.tools import TOOL_SPECS
    allowed = ("description", "dynamic_variable", "is_system_provided",
               "constant_value", "is_omitted")
    missing = []
    for tool in TOOL_SPECS:
        props = tool["parameters"].get("properties") or {}
        assert props, f"{tool['name']} has no properties"
        for field, spec in props.items():
            if not any(k in spec for k in allowed):
                missing.append(f"{tool['name']}.{field}")
    assert not missing, (
        "ElevenLabs will refuse the agent over these fields: " + str(missing))


def test_a_description_is_a_sentence_not_a_placeholder():
    """The model reads these, so "the phone" helps nobody."""
    from dialer.tools import TOOL_SPECS
    for tool in TOOL_SPECS:
        for field, spec in (tool["parameters"].get("properties") or {}).items():
            if "dynamic_variable" in spec:
                # The platform fills these, and the vendor forbids a
                # description beside a dynamic_variable ("can only set one").
                continue
            text = spec.get("description", "")
            assert len(text) > 25, f"{tool['name']}.{field}: {text!r}"


def test_the_tools_still_carry_their_required_fields():
    from dialer.tools import TOOL_SPECS
    by_name = {t["name"]: t for t in TOOL_SPECS}
    assert by_name["log_note"]["parameters"]["required"] == ["note"]
    assert by_name["set_disposition"]["parameters"]["required"] == ["disposition"]
    assert "dnc" in by_name["set_disposition"]["parameters"]["properties"][
        "disposition"]["enum"]


def test_a_failed_sync_can_be_retried_on_its_own(account):
    """The edit form could only sync as part of saving every field, so
    retrying meant resubmitting the whole agent and risking blanking
    something. A sync that failed for a reason outside the agent should be
    retryable once that reason is fixed."""
    owner, client = account
    playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    a = AiAgent.query.filter_by(account_id=owner.id).first()
    a.last_sync_error = "ElevenLabs said no"
    a.elevenlabs_agent_id = ""
    a.name = "Keep this name"
    db.session.commit()

    client.post(f"/dialer/agents/{a.id}/sync", follow_redirects=True)

    a = db.session.get(AiAgent, a.id)
    assert a.elevenlabs_agent_id, "the retry did not reach ElevenLabs"
    assert not a.last_sync_error
    assert a.name == "Keep this name", "a sync must not touch anything else"


def test_the_retry_is_offered_where_the_error_is_shown(account):
    owner, client = account
    playbook(owner.id)
    client.post("/dialer/agents/quick", follow_redirects=True)
    a = AiAgent.query.filter_by(account_id=owner.id).first()
    a.last_sync_error = "Value error, Must set one of: description…"
    db.session.commit()
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert "Try the sync again" in body


def test_the_retry_cannot_touch_another_accounts_agent(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="q@n.test", dialer=True)
    theirs = AiAgent(account_id=other.id, name="Theirs")
    db.session.add(theirs)
    db.session.commit()
    assert client.post(f"/dialer/agents/{theirs.id}/sync").status_code == 403
