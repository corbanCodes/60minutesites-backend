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
    assert "{{decision_maker}}" in prompt, "it should reuse a name it already has"
    assert "manager_name" in prompt, "and capture one it hears, structurally"


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
def test_no_placeholder_survives_into_the_prompt(account):
    """A placeholder left in a prompt is a placeholder read out loud.

    This used to check the stored row, because the name was baked in when
    the script was created. That froze it: renaming the AI left every
    existing script saying the old name, and the substitution read the
    COMPANY field, which is how "This is {ai_name} with NapkinAds" came out
    of a real account as "This is NapkinAds with NapkinAds". Filling happens
    when the prompt is assembled now, so this checks the thing that
    actually reaches the vendor."""
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    s.ai_person_name = "John"
    db.session.commit()
    agent = AiAgent.query.filter_by(account_id=owner.id).first()

    prompt = build_prompt(agent, s)

    assert "{ai_name}" not in prompt
    assert "{company}" not in prompt
    assert "This is John." in prompt
    assert "NapkinAds" in prompt


def test_the_speaker_is_never_introduced_as_the_company(account):
    """The exact production sentence: "This is NapkinAds with NapkinAds."."""
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    s.ai_person_name = "John"
    db.session.commit()
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    assert "NapkinAds with NapkinAds" not in build_prompt(agent, s)


def test_an_agent_can_have_its_own_name(account):
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    s.ai_person_name = "John"
    db.session.commit()
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    agent.person_name = "Sam"
    db.session.commit()
    prompt = build_prompt(agent, s)
    assert "This is Sam." in prompt
    assert "This is John." not in prompt


def test_renaming_reaches_a_script_that_already_existed(account):
    """The freeze this change exists to prevent."""
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    s.ai_person_name = "John"
    db.session.commit()
    assert "This is John." in build_prompt(agent, s)
    s.ai_person_name = "Dave"
    db.session.commit()
    assert "This is Dave." in build_prompt(agent, s)


def test_with_no_name_set_it_still_says_something_sayable(account):
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    agent = AiAgent.query.filter_by(account_id=owner.id).first()
    prompt = build_prompt(agent, s)
    assert "{ai_name}" not in prompt
    assert "{company}" not in prompt


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


# ------------------------------------------------- pressing it a second time
def test_installing_twice_does_not_make_two_agents_with_one_name(account):
    """What actually happened. The name was hard-coded, so a second press
    produced "NapkinAds venue caller" sitting next to "NapkinAds venue
    caller" in the test-call dropdown with nothing to tell them apart."""
    owner, client = account
    install(client)
    install(client)

    agents = AiAgent.query.filter_by(account_id=owner.id).all()
    assert len(agents) == 1
    assert len({a.name for a in agents}) == 1


def test_installing_twice_does_not_make_two_playbooks(account):
    owner, client = account
    install(client)
    install(client)
    assert Playbook.query.filter_by(account_id=owner.id).count() == 1


def test_the_second_install_resets_the_script_to_the_official_wording(account):
    owner, client = account
    install(client)
    pb = Playbook.query.filter_by(account_id=owner.id).one()
    pb.never_do = "whatever I felt like"
    db.session.commit()

    install(client)

    assert db.session.get(Playbook, pb.id).never_do == napkin.NEVER_DO


def test_the_agent_is_named_after_whoever_it_says_it_is(account):
    """"NapkinAds venue caller" next to "NapkinAds Official Playbook agent"
    tells you nothing about which one to test."""
    owner, client = account
    s = get_settings(owner.id)
    s.ai_person_name = "John"
    db.session.commit()
    install(client)
    assert AiAgent.query.filter_by(account_id=owner.id).one().name == \
        "John — venue calls"


def test_a_second_install_picks_up_a_renamed_speaker(account):
    owner, client = account
    install(client)
    s = get_settings(owner.id)
    s.ai_person_name = "Dave"
    db.session.commit()
    install(client)
    assert AiAgent.query.filter_by(account_id=owner.id).one().name == \
        "Dave — venue calls"


def test_installing_clears_a_stale_hand_written_prompt(account):
    """An override is a frozen copy of an older prompt, so it would keep
    every fix out of the agent for good."""
    owner, client = account
    install(client)
    a = AiAgent.query.filter_by(account_id=owner.id).one()
    a.prompt_override = "an old pasted copy with the broken transfer line"
    db.session.commit()

    install(client)

    assert db.session.get(AiAgent, a.id).prompt_override == ""


def test_a_second_install_keeps_the_transfer_destination(account):
    """Re-installing to refresh the script must not quietly unset where it
    hands off to, because that is the setting that makes it work at all."""
    owner, client = account
    install(client, transfer_to="+14235550147")
    install(client)
    assert AiAgent.query.filter_by(
        account_id=owner.id).one().transfer_to_number == "+14235550147"


def test_someone_else_s_identically_named_playbook_is_untouched(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = Playbook(account_id=other.id, name=napkin.NAME,
                      steps_json="[]", questions_json="[]",
                      objections_json="[]", never_do="theirs")
    db.session.add(theirs)
    db.session.commit()

    install(client)

    assert db.session.get(Playbook, theirs.id).never_do == "theirs"


def test_the_pair_carrying_his_work_is_the_one_kept(account):
    """His actual account: two installs from the old code, two playbooks
    with this name, two agents both called "NapkinAds venue caller". He
    typed the hand-off number into one of them. Re-installing must update
    THAT one and quiet the other, not pick whichever row is first."""
    owner, client = account
    stale = Playbook(account_id=owner.id, name=napkin.NAME, steps_json="[]",
                     questions_json="[]", objections_json="[]")
    worked = Playbook(account_id=owner.id, name=napkin.NAME, steps_json="[]",
                      questions_json="[]", objections_json="[]")
    db.session.add_all([stale, worked])
    db.session.flush()
    a_stale = AiAgent(account_id=owner.id, name="NapkinAds venue caller",
                      direction="outbound", playbook_id=stale.id, active=True)
    a_worked = AiAgent(account_id=owner.id, name="NapkinAds venue caller",
                       direction="outbound", playbook_id=worked.id,
                       active=True, transfer_to_number="+14235550147")
    db.session.add_all([a_stale, a_worked])
    db.session.commit()

    install(client)

    kept = db.session.get(AiAgent, a_worked.id)
    assert kept.active is True
    assert kept.transfer_to_number == "+14235550147"
    assert kept.name != "NapkinAds venue caller"
    assert db.session.get(AiAgent, a_stale.id).active is False, \
        "the duplicate is switched off, never deleted"
    assert AiAgent.query.filter_by(account_id=owner.id).count() == 2
    assert db.session.get(Playbook, worked.id).never_do == napkin.NEVER_DO


def test_quieting_duplicates_is_reported(account):
    owner, client = account
    for _ in range(2):
        pb = Playbook(account_id=owner.id, name=napkin.NAME, steps_json="[]",
                      questions_json="[]", objections_json="[]")
        db.session.add(pb)
        db.session.flush()
        db.session.add(AiAgent(account_id=owner.id, name="NapkinAds venue caller",
                               direction="outbound", playbook_id=pb.id,
                               active=True))
    db.session.commit()
    body = install(client).get_data(as_text=True)
    assert "1 older duplicate agent" in body


def test_the_tool_s_spoken_line_is_not_the_fetching_line(account):
    """"Great, thank you" is what step 2 says while staff fetch the
    manager. If the tool says it too, the prospect hears it twice in a row
    -- the "x2" from a live test."""
    owner, client = account
    install(client)
    pb = Playbook.query.filter_by(account_id=owner.id).one()
    fetching = [s for s in pb.steps if s["title"] == "If they are coming"][0]
    assert napkin.TRANSFER_LINE != fetching["say"]
    assert napkin.TRANSFER_LINE == "Oh, okay. Thanks."
