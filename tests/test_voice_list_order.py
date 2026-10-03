"""A voice the customer just cloned must be on the agent page.

ElevenLabs lists stock voices first and the customer's own after. The
page keeps the first forty, so a library with forty stock voices hid
every clone, and "I set my voice in ElevenLabs, is it available?" had
the answer no, silently. Own voices now come first, then stock.
"""
from dialer.providers import elevenlabs_live


class Resp:
    def __init__(self, payload, status_code=200):
        self._p, self.status_code, self.text = payload, status_code, ""
        self.headers = {}

    def json(self):
        return self._p


class Settings:
    def secret(self, name):
        return "k"


def _voices(n_stock, own):
    rows = [{"voice_id": f"stock{i}", "name": f"Stock {i}", "category": "premade",
             "labels": {}} for i in range(n_stock)]
    rows += [{"voice_id": vid, "name": name, "category": cat, "labels": {}}
             for vid, name, cat in own]
    return {"voices": rows}


def test_a_clone_behind_fifty_stock_voices_is_listed_first(monkeypatch):
    monkeypatch.setattr(elevenlabs_live.requests, "request",
                        lambda *a, **k: Resp(_voices(50, [("mine", "Corban", "cloned")])))
    r = elevenlabs_live.ElevenLabsAgent(Settings()).list_voices()
    assert r["ok"]
    assert r["voices"][0]["voice_id"] == "mine"
    assert len(r["voices"]) == 51, "no cap: every voice he owns"


def test_every_own_kind_outranks_stock(monkeypatch):
    own = [("a", "A", "cloned"), ("b", "B", "professional"), ("c", "C", "generated")]
    monkeypatch.setattr(elevenlabs_live.requests, "request",
                        lambda *a, **k: Resp(_voices(5, own)))
    r = elevenlabs_live.ElevenLabsAgent(Settings()).list_voices()
    assert [v["voice_id"] for v in r["voices"][:3]] == ["a", "b", "c"]
    assert all(v["category"] == "premade" for v in r["voices"][3:])


def test_stock_order_is_otherwise_untouched(monkeypatch):
    monkeypatch.setattr(elevenlabs_live.requests, "request",
                        lambda *a, **k: Resp(_voices(3, [])))
    r = elevenlabs_live.ElevenLabsAgent(Settings()).list_voices()
    assert [v["voice_id"] for v in r["voices"]] == ["stock0", "stock1", "stock2"]
