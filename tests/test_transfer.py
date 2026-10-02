"""The hand-off to a live person, which was never actually wired.

The prompt has told the agent to "use the transfer tool" since it was
written, and no transfer tool was ever sent to ElevenLabs. So a qualified
prospect heard "let me put you straight through to a colleague" followed by
nothing. Worse than never offering, and the single thing the client cares
most about.
"""
import pytest

from app import db
from dialer.agents import transfer_config, transfer_number
from dialer.models import AiAgent, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def setup(ctx):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18174032179"
    db.session.commit()
    return owner, s


def agent_with(owner_id, rules="", criteria=None):
    pb = None
    if criteria is not None:
        pb = Playbook(account_id=owner_id, name="P", steps_json="[]",
                      questions_json="[]", objections_json="[]",
                      transfer_criteria=criteria)
        db.session.add(pb)
        db.session.flush()
    a = AiAgent(account_id=owner_id, name="Q", transfer_rules=rules,
                playbook_id=pb.id if pb else None)
    db.session.add(a)
    db.session.commit()
    return a


# ------------------------------------------------- where the call goes
def test_an_explicit_transfer_number_wins(setup):
    owner, s = setup
    s.transfer_mode, s.transfer_number = "number", "+14235550147"
    db.session.commit()
    assert transfer_number(s) == "+14235550147"


def test_whoever_is_on_shift_falls_back_to_the_callback_number(setup):
    """"Whoever is available" is a browser tab, which has no phone number of
    its own, so a warm hand-off has to land on the human line the AI already
    reads out."""
    owner, s = setup
    s.transfer_mode = "browser"
    db.session.commit()
    assert transfer_number(s) == "+18174032179"


def test_with_no_number_anywhere_there_is_no_tool(setup):
    owner, s = setup
    s.transfer_mode, s.transfer_number, s.ai_callback_number = "browser", "", ""
    db.session.commit()
    assert transfer_config(agent_with(owner.id), s) is None


# ------------------------------------------------------- the tool itself
def test_the_tool_is_built_and_shaped_the_way_elevenlabs_wants(setup):
    owner, s = setup
    cfg = transfer_config(agent_with(owner.id), s)
    assert cfg["type"] == "system"
    assert cfg["name"] == "transfer_to_number"
    assert cfg["params"]["system_tool_type"] == "transfer_to_number"
    dest = cfg["params"]["transfers"][0]["transfer_destination"]
    assert dest == {"type": "phone", "phone_number": "+18174032179"}


def test_the_transfer_is_blind_so_there_is_no_hold_music(setup):
    """This asserted "conference" until a live call showed what conference
    actually sounds like. The reasoning was that a qualified caller cannot
    survive silence and a click, so they should hear a person arrive. What
    they hear instead is a Twilio conference room, and an unconfigured one
    plays the default classical playlist -- so the hand-off sounds like
    being put on hold by a utility company, for as long as the destination
    takes to answer. The conference belongs to ElevenLabs, so waitUrl is not
    ours to set, and there is no option for silence.

    Blind hands the leg over as it is: normal ringing, original caller ID,
    and the agent gone the moment it fires. Conference is still selectable
    per agent for anyone who wants the warm hand-off and will accept the
    music."""
    owner, s = setup
    cfg = transfer_config(agent_with(owner.id), s)
    assert cfg["params"]["transfers"][0]["transfer_type"] == "blind"


def test_the_playbooks_own_wording_becomes_the_condition(setup):
    owner, s = setup
    cfg = transfer_config(
        agent_with(owner.id, criteria="Transfer when they decide on napkins."),
        s)
    assert "decide on napkins" in cfg["params"]["transfers"][0]["condition"]


def test_the_agents_own_rules_beat_the_playbooks(setup):
    owner, s = setup
    cfg = transfer_config(
        agent_with(owner.id, rules="Transfer on any yes.",
                   criteria="Transfer when they decide on napkins."), s)
    assert cfg["params"]["transfers"][0]["condition"] == "Transfer on any yes."


def test_with_no_wording_at_all_there_is_still_a_sane_condition(setup):
    """A tool with an empty condition never fires, which looks exactly like
    the bug this replaces."""
    owner, s = setup
    cond = transfer_config(agent_with(owner.id), s)["params"]["transfers"][0]["condition"]
    assert cond.strip()
    assert "decides" in cond


# ------------------------------------------- and it reaches the vendor
def test_the_tool_is_sent_in_built_in_tools_not_the_webhook_list(setup, monkeypatch):
    """A system tool put in the ordinary tools array is the same as not
    sending it at all."""
    from dialer.providers import elevenlabs_live
    sent = {}
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)

    def fake_req(self, method, path, **kw):
        sent["body"] = kw.get("json")
        return {"ok": True, "data": {"agent_id": "ag_1"}}

    monkeypatch.setattr(cls, "_req", fake_req)
    owner, s = setup
    client = cls.__new__(cls)
    client.upsert_agent(agent_with(owner.id), "prompt", [],
                        transfer=transfer_config(agent_with(owner.id), s))

    prompt_cfg = sent["body"]["conversation_config"]["agent"]["prompt"]
    assert "built_in_tools" in prompt_cfg
    assert prompt_cfg["built_in_tools"]["transfer_to_number"]["name"] \
        == "transfer_to_number"
    assert prompt_cfg["tools"] == []


def test_no_transfer_means_no_empty_key_sent(setup, monkeypatch):
    from dialer.providers import elevenlabs_live
    sent = {}
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: (
        sent.update(body=kw.get("json")) or {"ok": True, "data": {"agent_id": "a"}}))
    owner, s = setup
    cls.__new__(cls).upsert_agent(agent_with(owner.id), "p", [], transfer=None)
    assert "built_in_tools" not in sent["body"]["conversation_config"]["agent"]["prompt"]


# -------------------------------------- the lane, and explaining any of it
def test_the_qualify_lane_changes_what_the_drafter_is_asked_for(ctx, monkeypatch):
    """The client's requirement in one checkbox: find out if it is the
    manager, then hand over, rather than trying to close."""
    from dialer import playbook_ai
    from dialer.providers import registry
    seen = {}

    class Stub:
        def complete(self, system, user, max_tokens=800, json_mode=False):
            seen["user"] = user
            return {"ok": True, "data": {"steps": [{"title": "Open",
                                                    "say": "Hello."}]}}

    monkeypatch.setattr(registry, "llm", lambda s: Stub())
    owner = make_user(name="N", email="lane@n.test", dialer=True)
    s = get_settings(owner.id)

    playbook_ai.draft(s, "We give bars free napkins with a QR code on them.",
                      lane="qualify_transfer")
    assert "QUALIFY AND HAND OVER, NOT TO CLOSE" in seen["user"]

    playbook_ai.draft(s, "We give bars free napkins with a QR code on them.")
    assert "QUALIFY AND HAND OVER" not in seen["user"]


def test_the_lane_is_offered_and_on_by_default(ctx, client):
    owner = make_user(name="N", email="ui@n.test", dialer=True)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "ui@n.test", "password": "pw123456"})
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert 'value="qualify_transfer"' in body
    lane = body.split('value="qualify_transfer"')[1][:60]
    assert "checked" in lane


def test_the_page_explains_what_a_transfer_actually_does(ctx, client):
    """He could not find where transfer was configured or what it did. The
    mechanics now sit on the step where people look for them."""
    owner = make_user(name="N", email="exp@n.test", dialer=True)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "exp@n.test", "password": "pw123456"})
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert "How the hand-off to a person actually works" in body
    assert "conference" in body
    assert "stop selling" in body


# ------------------------------- the thing that was destroying the tool
def test_an_update_does_not_resend_the_deprecated_tools_array(setup, monkeypatch):
    """The whole mystery. ElevenLabs silently migrates a legacy `tools`
    array by rebuilding the agent's entire tool set from it, and ours
    carries only webhook tools, so built_in_tools came back with every slot
    null. 200 OK, prompt intact, background sound intact, and no way to
    hand a call over."""
    from dialer.providers import elevenlabs_live
    sent = {}
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: (
        sent.update(body=kw.get("json")) or {"ok": True, "data": {"agent_id": "a"}}))

    owner, s = setup
    a = agent_with(owner.id)
    a.elevenlabs_agent_id = "agent_existing"
    db.session.commit()

    cls.__new__(cls).upsert_agent(a, "prompt", [{"name": "log_note"}],
                                  transfer=transfer_config(a, s))

    prompt_cfg = sent["body"]["conversation_config"]["agent"]["prompt"]
    assert "tools" not in prompt_cfg, "sending this wipes built_in_tools"
    assert prompt_cfg["built_in_tools"]["transfer_to_number"]


def test_a_brand_new_agent_still_gets_its_webhook_tools(setup, monkeypatch):
    """On create there is no existing tool set to clobber, so the webhook
    tools have to go across or the agent cannot log a note."""
    from dialer.providers import elevenlabs_live
    sent = {}
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: (
        sent.update(body=kw.get("json")) or {"ok": True, "data": {"agent_id": "a"}}))

    owner, s = setup
    a = agent_with(owner.id)
    a.elevenlabs_agent_id = ""
    db.session.commit()

    cls.__new__(cls).upsert_agent(a, "prompt", [{"name": "log_note"}])

    assert sent["body"]["conversation_config"]["agent"]["prompt"]["tools"]


def test_an_empty_model_name_is_omitted_rather_than_sent(setup, monkeypatch):
    """"" is not a member of their model enum, so sending it was relying on
    undefined behaviour. Omitting the key keeps the current model."""
    from dialer.providers import elevenlabs_live
    sent = {}
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: (
        sent.update(body=kw.get("json")) or {"ok": True, "data": {"agent_id": "a"}}))

    owner, s = setup
    a = agent_with(owner.id)
    a.llm_model = ""
    db.session.commit()

    cls.__new__(cls).upsert_agent(a, "prompt", [])

    assert "llm" not in sent["body"]["conversation_config"]["agent"]["prompt"]
