"""The shape of the webhook request, and the shape of the complaint back.

Step 6 reported the results webhook as Missing and told the owner to get a key
from a workspace admin. Both halves were wrong. The real reply was a 422
naming a field, because the three settings go inside a `settings` object and
we were sending them flat. The field name was being thrown away by the error
reader, so all anyone saw was "Field required", which reads like somebody
else's problem.
"""
import pytest

from dialer.providers import elevenlabs_live
from dialer.providers.elevenlabs_live import _api_message


class Resp:
    def __init__(self, payload, status_code=422, text=""):
        self._p = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p


# -------------------------------------------------------- the error reader
def test_a_validation_error_names_the_field():
    """The whole diagnosis hinged on this. "Field required" alone sent the
    hunt toward key permissions; "(settings)" ends it in one read."""
    msg = _api_message(Resp({"detail": [
        {"loc": ["body", "settings"], "msg": "Field required",
         "type": "missing"}]}))
    assert "Field required" in msg
    assert "settings" in msg


def test_several_validation_errors_are_all_reported():
    msg = _api_message(Resp({"detail": [
        {"loc": ["body", "settings", "name"], "msg": "Field required"},
        {"loc": ["body", "settings", "webhook_url"], "msg": "Field required"}]}))
    assert "settings.name" in msg
    assert "settings.webhook_url" in msg


def test_the_envelope_words_are_left_out_of_the_field_path():
    """"body" appears in every loc and tells the reader nothing."""
    msg = _api_message(Resp({"detail": [
        {"loc": ["body", "settings"], "msg": "Field required"}]}))
    assert "body" not in msg


def test_a_permissions_error_still_reads_as_a_permissions_error():
    msg = _api_message(Resp({"detail": {
        "status": "insufficient_permissions",
        "message": "You do not have the required permissions for this action."}},
        status_code=403))
    assert "permissions" in msg.lower()


def test_an_unparseable_body_still_produces_something_useful():
    msg = _api_message(Resp(None, status_code=500, text="upstream exploded"))
    assert "500" in msg


# ------------------------------------------------------- the request shape
def test_the_webhook_request_nests_its_fields_under_settings(monkeypatch):
    """The bug itself. Sent flat, ElevenLabs 422s and no transcript ever
    arrives from any AI call."""
    sent = {}

    def fake_req(self, method, path, **kw):
        sent["method"] = method
        sent["path"] = path
        sent["json"] = kw.get("json")
        return {"ok": True, "data": {"webhook_id": "wh_1",
                                     "webhook_secret": "shhh"}}

    monkeypatch.setattr(elevenlabs_live.ElevenLabsLive
                        if hasattr(elevenlabs_live, "ElevenLabsLive")
                        else elevenlabs_live.ElevenLabsAgent,
                        "_req", fake_req, raising=False)
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    client = cls.__new__(cls)
    r = client.ensure_webhook("https://hq.example.com/hook", "60MS HQ post-call")

    assert r["ok"] is True
    body = sent["json"]
    assert set(body) == {"settings"}, (
        "the three fields belong inside `settings`, not at the top level")
    assert body["settings"]["auth_type"] == "hmac"
    assert body["settings"]["name"] == "60MS HQ post-call"
    assert body["settings"]["webhook_url"] == "https://hq.example.com/hook"


def test_the_signing_secret_is_read_back(monkeypatch):
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: {
        "ok": True, "data": {"webhook_id": "wh_1", "webhook_secret": "shhh"}})
    r = cls.__new__(cls).ensure_webhook("https://x.test/h", "n")
    assert r["webhook_id"] == "wh_1"
    assert r["secret"] == "shhh"


def test_a_wrapped_response_is_read_too(monkeypatch):
    """Documented flat. The request wraps, so accept either rather than
    failing on a shape that is plainly intended."""
    cls = (getattr(elevenlabs_live, "ElevenLabsLive", None)
           or elevenlabs_live.ElevenLabsAgent)
    monkeypatch.setattr(cls, "_req", lambda self, m, p, **kw: {
        "ok": True,
        "data": {"settings": {"webhook_id": "wh_2", "webhook_secret": "s2"}}})
    r = cls.__new__(cls).ensure_webhook("https://x.test/h", "n")
    assert r["webhook_id"] == "wh_2"
    assert r["secret"] == "s2"
