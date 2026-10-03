"""Handing over in one turn, in words you chose, at a human energy level.

Three things went wrong on live calls and all three came from this code,
not from anything the customer typed.

* The hand-off waited for a second reply. The prompt said "say this, THEN
  call the transfer tool", and that cannot be obeyed: speaking ends the
  model's turn, so the tool call lands in the next one -- which only
  arrives when the other person speaks again.
* It announced "I'm going to connect you with one of our team members
  now." client_message is an LLM-supplied runtime parameter, so with a
  vague tool description the model writes its own line, and what it writes
  is call-centre filler.
* It sounded delighted. We sent a voice_id and nothing else, so every
  agent ran on ElevenLabs' defaults, and expressive_mode defaults to true.
"""
import pytest

from app import db
from dialer.agents import (DELIVERIES, TRANSFER_STYLES, build_prompt,
                           delivery_tts, transfer_config, transfer_say)
from dialer.models import AiAgent, Playbook
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def setup(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18655550123"
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, client


def agent_with(owner_id, **kw):
    pb = Playbook(account_id=owner_id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer the instant you have a "
                                    "decision maker.")
    db.session.add(pb)
    db.session.flush()
    a = AiAgent(account_id=owner_id, name="A", direction="outbound",
                playbook_id=pb.id, **kw)
    db.session.add(a)
    db.session.commit()
    return a


# --------------------------------------------------------------- one turn
def test_the_prompt_forbids_speaking_before_the_tool_call(setup):
    owner, s, _ = setup
    prompt = build_prompt(agent_with(owner.id), s)
    assert "Do NOT say anything first" in prompt
    assert "same turn" in prompt


def test_the_prompt_no_longer_says_to_speak_and_then_transfer(setup):
    """The exact instruction that produced the bug. If it ever comes back,
    the agent goes mute again until the prospect says something else."""
    owner, s, _ = setup
    prompt = build_prompt(agent_with(owner.id), s)
    assert "Then call the transfer tool" not in prompt
    assert "Say exactly this, then transfer" not in prompt


def test_the_prompt_explains_why_so_a_later_edit_does_not_undo_it(setup):
    owner, s, _ = setup
    assert "waits for them to talk again" in build_prompt(agent_with(owner.id), s)


# ------------------------------------------------------------- the wording
def test_the_line_is_handed_to_the_tool_not_left_to_the_model(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, transfer_style="custom",
                   transfer_line="Oh, okay. Thanks.")
    desc = transfer_config(a, s)["description"]
    assert "Oh, okay. Thanks." in desc
    assert "client_message" in desc


def test_the_tool_bans_the_sentence_it_kept_inventing(setup):
    owner, s, _ = setup
    desc = transfer_config(agent_with(owner.id), s)["description"]
    assert "let me connect you" in desc
    assert "one of our team members" in desc


def test_the_prompt_carries_the_same_literal_line(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, transfer_style="custom",
                   transfer_line="Oh, okay. Thanks.")
    assert '"Oh, okay. Thanks."' in build_prompt(a, s)


@pytest.mark.parametrize("style", ["brief", "explicit", "natural"])
def test_every_style_is_a_literal_line_not_a_description(setup, style):
    """A style used to be advice to the model ("say one short line"), which
    is an invitation to compose. Each is a sentence now."""
    owner, s, _ = setup
    a = agent_with(owner.id, transfer_style=style)
    assert transfer_say(a) == TRANSFER_STYLES[style]["line"]
    assert transfer_say(a) in transfer_config(a, s)["description"]


def test_a_custom_style_with_an_empty_line_still_has_words(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, transfer_style="custom", transfer_line="")
    assert transfer_say(a) == TRANSFER_STYLES["brief"]["line"]


# ---------------------------------------------------------------- delivery
def test_calm_turns_expressive_mode_off(setup):
    """The default is true at ElevenLabs, and it is what made a flat line
    sound thrilled."""
    owner, s, _ = setup
    assert delivery_tts(agent_with(owner.id))["expressive_mode"] is False


def test_calm_is_the_default_for_a_new_agent(setup):
    owner, s, _ = setup
    a = agent_with(owner.id)
    assert delivery_tts(a) == DELIVERIES["calm"]["tts"]


def test_an_agent_predating_the_column_is_calm_too(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, voice_delivery=None)
    assert delivery_tts(a)["expressive_mode"] is False


def test_lively_is_still_available_for_an_inbound_line(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, voice_delivery="lively")
    assert delivery_tts(a)["expressive_mode"] is True


def test_a_junk_value_falls_back_to_calm(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, voice_delivery="unhinged")
    assert delivery_tts(a) == DELIVERIES["calm"]["tts"]


def test_every_preset_sends_all_three_knobs(setup):
    """Leaving one out means that one silently keeps ElevenLabs' default,
    which is the whole reason this exists."""
    for name, d in DELIVERIES.items():
        assert set(d["tts"]) == {"stability", "speed", "expressive_mode"}, name


def test_the_settings_reach_the_payload_beside_the_voice(setup):
    """conversation_config is a free-form object on PATCH, so a setting in
    the wrong place is accepted with a 200 and discarded. The only cheap
    guard is checking what we build."""
    owner, s, _ = setup
    from dialer.providers import elevenlabs_live
    a = agent_with(owner.id, voice_id="v1")
    tts = {"voice_id": a.voice_id, **elevenlabs_live._delivery(a)}
    assert tts["voice_id"] == "v1"
    assert tts["expressive_mode"] is False
    assert tts["stability"] == 0.75


# ----------------------------------------------------------- the controls
def test_both_controls_render_on_the_agent_page(setup):
    """An undefined name in Jinja is an empty loop, not an error, so a
    select whose dict never reached the template looks like a styling bug."""
    owner, s, client = setup
    a = agent_with(owner.id)
    body = client.get(f"/dialer/agents/{a.id}").get_data(as_text=True)
    assert 'name="voice_delivery"' in body
    assert DELIVERIES["calm"]["label"] in body
    assert DELIVERIES["lively"]["label"] in body


def test_the_delivery_choice_saves(setup):
    owner, s, client = setup
    a = agent_with(owner.id)
    client.post(f"/dialer/agents/{a.id}", follow_redirects=True,
                data={"name": a.name, "voice_delivery": "lively"})
    assert db.session.get(AiAgent, a.id).voice_delivery == "lively"


# ------------------------------------------- overrides must still transfer
def test_an_override_still_gets_the_transfer_mechanics(setup):
    """Overrides are made by copying the generated prompt, editing it, and
    pasting it back -- which freezes whatever the tool instructions said on
    the day of the copy. One such copy carried "say this, THEN call the
    transfer tool", and no later fix could reach that agent."""
    owner, s, _ = setup
    a = agent_with(owner.id, prompt_override="Be brief. Ask for the owner.")
    prompt = build_prompt(a, s)
    assert "Be brief. Ask for the owner." in prompt
    assert "Do NOT say anything first" in prompt
    assert "same turn" in prompt


def test_the_override_itself_is_never_altered(setup):
    owner, s, _ = setup
    mine = "Say only what I wrote. Nothing else."
    a = agent_with(owner.id, prompt_override=mine)
    assert build_prompt(a, s).startswith(mine)


def test_the_mechanics_carry_the_chosen_line_too(setup):
    owner, s, _ = setup
    a = agent_with(owner.id, prompt_override="Mine.",
                   transfer_style="custom", transfer_line="Oh, okay. Thanks.")
    assert '"Oh, okay. Thanks."' in build_prompt(a, s)


def test_nothing_is_appended_when_there_is_nowhere_to_transfer(setup):
    """An agent that cannot hand over should not be told how to."""
    owner, s, _ = setup
    s.ai_callback_number = ""
    s.transfer_mode = ""
    db.session.commit()
    a = agent_with(owner.id, prompt_override="Mine.")
    prompt = build_prompt(a, s)
    assert "mechanics, not wording" not in prompt
    assert "transfer_to_number tool" not in prompt
    assert prompt.startswith("Mine.")     # the disclosure still follows


def test_the_block_is_labelled_as_mechanics_not_wording(setup):
    """So the next person reading it knows which half is theirs."""
    owner, s, _ = setup
    a = agent_with(owner.id, prompt_override="Mine.")
    assert "mechanics, not wording" in build_prompt(a, s)
