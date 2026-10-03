"""The register-call reply is a string of TwiML, not a JSON object.

First owned-mode live test, 2026-10-03 19:10 UTC: the prospect answered,
the connect hook asked ElevenLabs to ride the call, ElevenLabs answered
200 in 115 ms, and the prospect was hung up on. The reader wanted a dict
with a "twiml" key; the API reference says the endpoint "returns a string
containing TwiML". Every successful registration became <Hangup/>.
"""
import pytest

from dialer.providers import elevenlabs_live

TWIML = ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
         '<Stream url="wss://api.elevenlabs.io/x" /></Connect></Response>')


class Resp:
    def __init__(self, payload=None, text="", status_code=200):
        self._p, self.text, self.status_code = payload, text, status_code
        self.headers = {"Content-Type": "text/xml"}

    def json(self):
        if self._p is None:
            raise ValueError("not json")
        return self._p


class Settings:
    def secret(self, name):
        return "k"


def _agent(monkeypatch, resp):
    monkeypatch.setattr(elevenlabs_live.requests, "request",
                        lambda *a, **k: resp)
    return elevenlabs_live.ElevenLabsAgent(Settings())


def test_a_text_xml_body_is_the_twiml(monkeypatch):
    r = _agent(monkeypatch, Resp(None, text=TWIML)).register_call(
        "ag_1", "+1", "+2", "outbound", {"hq_call_id": "7"})
    assert r["ok"] and "<Connect>" in r["twiml"]


def test_a_json_encoded_string_is_the_twiml(monkeypatch):
    r = _agent(monkeypatch, Resp(TWIML, text='"..."')).register_call(
        "ag_1", "+1", "+2", "outbound")
    assert r["ok"] and r["twiml"].startswith("<?xml")


def test_an_object_with_a_twiml_key_still_works(monkeypatch):
    r = _agent(monkeypatch, Resp({"twiml": TWIML})).register_call(
        "ag_1", "+1", "+2", "inbound")
    assert r["ok"] and "<Stream" in r["twiml"]


def test_a_reply_without_twiml_says_what_came_back(monkeypatch):
    r = _agent(monkeypatch, Resp({"status": "ok"})).register_call(
        "ag_1", "+1", "+2", "outbound")
    assert r["ok"] is False
    assert "no TwiML" in r["error"] and "status" in r["error"]


def test_a_non_2xx_is_still_the_api_s_own_message(monkeypatch):
    r = _agent(monkeypatch, Resp({"detail": {"message": "Agent not found"}},
                                 status_code=404)).register_call(
        "ag_1", "+1", "+2", "outbound")
    assert r["ok"] is False and "Agent not found" in r["error"]
