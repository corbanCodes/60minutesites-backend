"""Hearing a voice before you pick it.

Step 8 listed forty voices by name and a few adjectives and asked you to
choose one, with no way to hear any of them. ElevenLabs hands us a public mp3
per voice and a category saying whether it is stock or one you made; both were
being dropped on the floor by list_voices().
"""
import pytest

from dialer.providers import elevenlabs_live
from dialer.routes_ui import VOICE_KINDS


class Resp:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


ELEVEN_PAYLOAD = {"voices": [
    {"voice_id": "v1", "name": "Charlie",
     "labels": {"age": "young", "accent": "australian"},
     "preview_url": "https://storage.example/charlie.mp3",
     "category": "premade",
     "high_quality_base_model_ids": ["eleven_turbo_v2_5"]},
    {"voice_id": "v2", "name": "My Own Clone",
     "labels": {"age": "middle_aged"},
     "preview_url": "https://storage.example/mine.mp3",
     "category": "cloned"},
    {"voice_id": "v3", "name": "No Preview Here", "labels": {},
     "category": "premade"},
]}


@pytest.fixture
def client(monkeypatch):
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req",
                        lambda self, m, p, **kw: {"ok": True,
                                                  "data": ELEVEN_PAYLOAD})
    return cls.__new__(cls)


# -------------------------------------------------------------- the data
def _by_id(voices):
    return {v["voice_id"]: v for v in voices}


def test_the_preview_url_survives_the_trip(client):
    voices = _by_id(client.list_voices()["voices"])
    assert voices["v1"]["preview_url"] == "https://storage.example/charlie.mp3"


def test_the_category_survives_the_trip(client):
    voices = _by_id(client.list_voices()["voices"])
    assert voices["v1"]["category"] == "premade"
    assert voices["v2"]["category"] == "cloned"


def test_the_customer_s_own_voice_is_listed_first(client):
    assert client.list_voices()["voices"][0]["voice_id"] == "v2"


def test_a_voice_with_no_preview_gets_an_empty_string_not_a_crash(client):
    """The template keys off truthiness to decide between a play button and a
    dead one, so None here would render a button that does nothing."""
    voices = _by_id(client.list_voices()["voices"])
    assert voices["v3"]["preview_url"] == ""


def test_labels_are_still_flattened_for_display(client):
    assert "australian" in _by_id(client.list_voices()["voices"])["v1"]["labels"]


# ------------------------------------------------------------ the wording
def test_every_elevenlabs_category_has_a_plain_english_name():
    """ElevenLabs' own words are premade, professional, high_quality, famous,
    cloned and generated. Showing those raw tells a customer nothing about
    the only thing they care about, which is whether anyone else calling the
    same list could be using the same voice."""
    for category in ("premade", "professional", "high_quality", "famous",
                     "cloned", "generated"):
        assert category in VOICE_KINDS, f"no wording for {category}"
        assert VOICE_KINDS[category]


def test_a_voice_you_made_is_not_described_as_stock():
    assert "Stock" not in VOICE_KINDS["cloned"]
    assert "Stock" not in VOICE_KINDS["generated"]
    assert VOICE_KINDS["premade"].startswith("Stock")


# ------------------------------------------------------------- the pages
def test_the_player_is_loaded_on_both_pages_that_list_voices(ctx, client_app):
    for step in (6, 8):
        body = client_app.get(f"/dialer/setup/{step}").get_data(as_text=True)
        assert "/static-admin/voiceplay.js" in body, f"step {step}"


def test_step_six_sends_you_to_step_eight_to_actually_choose(ctx, client_app):
    body = client_app.get("/dialer/setup/6").get_data(as_text=True)
    assert "/dialer/setup/8" in body
    assert "Do not choose here" in body


@pytest.fixture
def client_app(ctx):
    from app import app as flask_app
    c = flask_app.test_client()
    c.post("/login", data={"email": "", "password": "test-admin-pw"})
    return c
