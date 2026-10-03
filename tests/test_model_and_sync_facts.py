"""What the verification against ElevenLabs' own spec turned up.

Every one of these was a way for the hand-off to fail with a 200 and no
error anywhere, or a way for a model to be too weak to make the tool call
the hand-off depends on.

* "claude-3-5-haiku" was in OUR dropdown and is not a member of their LLM
  enum, so an agent that picked it 422'd on every sync from then on.
* "gemini-2.0-flash" was OUR column default, pushed on every sync, and
  their tools docs say verbatim to avoid it because it "can struggle with
  extracting the relevant parameters". The hand-off is a tool call with
  three parameters in one turn.
* The TTS model was never pinned, and their own sources disagree on the
  default, so the delivery setting meant different things on different
  days.
* A create carries the webhook tools in the deprecated `tools` array,
  which ElevenLabs rebuilds the whole tool set from, so a brand-new agent
  could come back with no transfer tool until somebody saved it again.
"""
import pytest

from app import db
from dialer import agents as agents_mod
from dialer.agents import normalise_llm, sync_agent, transfer_config
from dialer.models import AiAgent, Playbook
from dialer.providers import elevenlabs_live, registry
from dialer.routes_ui import ELEVEN_MODELS
from dialer.settings_store import get_settings
from tests.conftest import make_user

DOCUMENTED_TTS_MODELS = {
    "eleven_turbo_v2", "eleven_turbo_v2_5", "eleven_flash_v2",
    "eleven_flash_v2_5", "eleven_multilingual_v2", "eleven_v3_conversational",
    "eleven_v4", "eleven_v4_turbo",
}


@pytest.fixture
def setup(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.ai_callback_number = "+18655550123"
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, client


def make_agent(owner_id, **kw):
    a = AiAgent(account_id=owner_id, name="A", direction="outbound", **kw)
    db.session.add(a)
    db.session.commit()
    return a


def capture(monkeypatch):
    sent = []
    cls = elevenlabs_live.ElevenLabsAgent
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: (
        sent.append(kw.get("json")) or {"ok": True, "data": {"agent_id": "ag_1"}}))
    return cls.__new__(cls), sent


# ------------------------------------------------------------------ ids
def test_the_dropdown_holds_no_id_that_is_not_in_their_enum():
    assert "claude-3-5-haiku" not in ELEVEN_MODELS
    assert "claude-sonnet-4" not in ELEVEN_MODELS


def test_the_first_entry_is_a_model_they_recommend_for_tools():
    assert ELEVEN_MODELS[0] == "gemini-2.5-flash"


def test_a_stale_stored_id_is_mapped_forward_not_sent():
    assert normalise_llm("claude-3-5-haiku") == "claude-haiku-4-5"
    assert normalise_llm("claude-sonnet-4") == "claude-sonnet-4-5"
    assert normalise_llm("gpt-4o") == "gpt-4o"
    assert normalise_llm("") == ""
    assert normalise_llm(None) == ""


def test_the_payload_carries_the_mapped_id(setup, monkeypatch):
    """An agent that chose the invalid id before the dropdown was fixed
    must not keep 422ing forever."""
    owner, s, _ = setup
    client, sent = capture(monkeypatch)
    a = make_agent(owner.id, llm_model="claude-3-5-haiku")
    client.upsert_agent(a, "p", [])
    assert sent[-1]["conversation_config"]["agent"]["prompt"]["llm"] \
        == "claude-haiku-4-5"


def test_the_column_no_longer_defaults_to_the_weak_model(setup):
    owner, s, _ = setup
    a = make_agent(owner.id)
    assert (a.llm_model or "") == ""


def test_an_empty_model_is_still_omitted_from_the_payload(setup, monkeypatch):
    owner, s, _ = setup
    client, sent = capture(monkeypatch)
    client.upsert_agent(make_agent(owner.id), "p", [])
    assert "llm" not in sent[-1]["conversation_config"]["agent"]["prompt"]


# ------------------------------------------------------------- install
def install(client, transfer_to="+14235550147"):
    return client.post("/dialer/playbooks/napkin", follow_redirects=True,
                       data={"transfer_to": transfer_to})


def test_the_guide_install_moves_off_the_weak_model(setup):
    owner, s, client = setup
    install(client)
    a = AiAgent.query.filter_by(account_id=owner.id).one()
    assert a.llm_model == ELEVEN_MODELS[0]


def test_a_second_install_replaces_only_the_weak_default(setup):
    """His agent has gemini-2.0-flash stored from the old default. A model
    somebody actually chose is left alone."""
    owner, s, client = setup
    install(client)
    a = AiAgent.query.filter_by(account_id=owner.id).one()
    a.llm_model = "gemini-2.0-flash"
    db.session.commit()
    install(client)
    assert db.session.get(AiAgent, a.id).llm_model == ELEVEN_MODELS[0]

    a.llm_model = "gpt-4.1"
    db.session.commit()
    install(client)
    assert db.session.get(AiAgent, a.id).llm_model == "gpt-4.1"


# ----------------------------------------------------------------- tts
def test_the_tts_model_is_pinned_to_a_documented_id(setup, monkeypatch):
    owner, s, _ = setup
    client, sent = capture(monkeypatch)
    client.upsert_agent(make_agent(owner.id, voice_id="v1"), "p", [])
    tts = sent[-1]["conversation_config"]["tts"]
    assert tts["model_id"] == elevenlabs_live.TTS_MODEL
    assert elevenlabs_live.TTS_MODEL in DOCUMENTED_TTS_MODELS
    assert tts["voice_id"] == "v1"
    assert tts["stability"] == 0.75          # calm is still the default


def test_the_voicemail_preview_no_longer_uses_a_deprecated_model():
    import inspect
    sig = inspect.signature(elevenlabs_live.ElevenLabsAgent.speak)
    assert sig.parameters["model_id"].default == "eleven_flash_v2_5"


# ------------------------------------------------------- client message
def test_the_wait_message_is_switched_on_explicitly(setup):
    owner, s, _ = setup
    cfg = transfer_config(make_agent(owner.id), s)
    assert cfg["params"]["enable_client_message"] is True


# --------------------------------------------- create, then one update
class FakeVendor:
    """Records each upsert and whether the agent already had an id."""

    def __init__(self):
        self.calls = []

    def upsert_agent(self, agent, prompt, tools, **kw):
        self.calls.append({
            "had_id": bool((agent.elevenlabs_agent_id or "").strip()),
            "transfer": kw.get("transfer"),
        })
        return {"ok": True, "agent_id": "ag_new"}


def test_a_brand_new_agent_is_created_then_updated_once(setup, monkeypatch):
    """The create carries `tools`, which rebuilds the whole tool set, so
    the transfer tool may not survive it. The follow-up update sends no
    `tools` and lands it."""
    owner, s, _ = setup
    fake = FakeVendor()
    monkeypatch.setattr(registry, "voice_agent", lambda settings: fake)
    a = make_agent(owner.id)

    r = sync_agent(a, s)

    assert r["ok"]
    assert [c["had_id"] for c in fake.calls] == [False, True]
    assert all(c["transfer"] for c in fake.calls)
    assert db.session.get(AiAgent, a.id).elevenlabs_agent_id == "ag_new"


def test_an_existing_agent_is_updated_exactly_once(setup, monkeypatch):
    owner, s, _ = setup
    fake = FakeVendor()
    monkeypatch.setattr(registry, "voice_agent", lambda settings: fake)
    a = make_agent(owner.id, elevenlabs_agent_id="ag_old")

    sync_agent(a, s)

    assert [c["had_id"] for c in fake.calls] == [True]


def test_a_failed_follow_up_is_reported_not_swallowed(setup, monkeypatch):
    owner, s, _ = setup

    class Flaky(FakeVendor):
        def upsert_agent(self, agent, prompt, tools, **kw):
            r = super().upsert_agent(agent, prompt, tools, **kw)
            if len(self.calls) == 2:
                return {"ok": False, "error": "second call refused"}
            return r

    fake = Flaky()
    monkeypatch.setattr(registry, "voice_agent", lambda settings: fake)
    a = make_agent(owner.id)

    r = sync_agent(a, s)

    assert r["ok"] is False
    assert "second call refused" in db.session.get(AiAgent, a.id).last_sync_error
