"""THE SHRINE.

On 2026-10-03, after two nights of rings, hold music and "let me connect
you", the hand-off worked: the AI said its line, the owner's browser phone
answered by itself, and the prospect heard nothing that marked the moment.
These are the invariants that made it work. If one of them fails, the
prospect hears a ring, music, or a robot announcing a transfer. Do not
"fix" a failing test here; fix the code.
"""
from app import db
from dialer import agents as agents_mod, bridge
from dialer.agents import build_prompt, transfer_config
from dialer.models import AiAgent
from dialer.tools import account_token, run_tool
from tests.test_owned_handoff import world, placed_call, PROSPECT, LINE, AI, HUMAN  # noqa: F401


def handoff(owner, call):
    return run_tool("set_disposition",
                    {"disposition": "handoff", "hq_call_id": str(call.id)},
                    account_token(owner.id))


def test_1_the_vendor_is_given_no_way_to_dial_anything(world):
    """Whatever ElevenLabs dials, the prospect hears ring. So it dials nothing."""
    owner, s, agent, tel, va, client = world
    assert transfer_config(agent, s) is None
    assert agents_mod.transfer_number(s, agent) == ""


def test_2_nothing_is_dialled_on_the_prospects_side(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    r = handoff(owner, call)
    assert r["ok"]
    assert [x["sid"] for x in tel.redirected] == [call.twilio_sid], "the prospect is MOVED"
    assert len(tel.created) == 1, "exactly one leg: the person's"
    leg = tel.created[0]
    assert leg["to"] not in (PROSPECT, LINE, AI)
    assert leg["from_"] == LINE, "the person sees the rep line"


def test_3_the_prospect_is_moved_into_a_silent_room(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    handoff(owner, call)
    twiml = tel.redirected[0]["twiml"]
    assert "<Conference" in twiml
    assert 'beep="false"' in twiml and 'startConferenceOnEnter="false"' in twiml
    assert "<Number>" not in twiml and "<Say" not in twiml, "no dial, no robot voice"


def test_4_the_wait_is_office_ambience_that_loops_not_hold_music(world):
    owner, s, agent, tel, va, client = world
    w = bridge.wait_twiml()
    assert "handoff-office.mp3" in w and "<Redirect/>" in w
    call = placed_call(owner, s, agent)
    handoff(owner, call)
    assert "/bridge/wait" in tel.redirected[0]["twiml"]


def test_5_the_line_is_spoken_in_the_agents_own_voice_before_the_room(world):
    owner, s, agent, tel, va, client = world
    agents_mod.sync_agent(agent, s)
    assert va.spoken and va.spoken[0]["voice_id"] == agent.voice_id
    call = placed_call(owner, s, agent)
    handoff(owner, call)
    twiml = tel.redirected[0]["twiml"]
    assert twiml.index("<Play>") < twiml.index("<Dial>")
    assert "/handoff-line/" in twiml, "our own copy, in the agent's voice"


def test_6_the_agent_is_told_to_say_nothing_more(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    r = handoff(owner, call)
    assert "Say nothing more" in r["message"]
    p = build_prompt(agent, s)
    assert "say nothing more" in p
    assert "set_disposition" in p and '"handoff"' in p
    assert "transfer_to_number tool" not in p, "no vendor transfer, ever"


def test_7_a_second_fire_does_not_ring_the_person_twice(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    handoff(owner, call)
    handoff(owner, call)
    assert len(tel.created) == 1


def test_8_the_browser_phone_is_rung_as_the_rep_line_when_it_is_open(world):
    from tests.test_bridge import present
    owner, s, agent, tel, va, client = world
    present(owner.id, owner.id)
    call = placed_call(owner, s, agent)
    handoff(owner, call)
    leg = tel.created[0]
    assert leg["to"].startswith("client:") and leg["from_"] == LINE
