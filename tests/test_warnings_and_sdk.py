"""Advice you can put away, and links that go where they say.

Three things turned a setup into a loop:

* "AI calling needs an AI agent -- Open step 9" linked to the playbook step.
  Agents are built at /dialer/agents, so following the link landed somewhere
  that could not fix it and the warning stayed up. That is the circle.
* Warnings and blockers looked identical, so advice read as a locked door.
  Nothing in the warnings list stops a call going out.
* "Recording needs a recording announcement" could not be waved away, so a
  decision already made kept being re-asked.
"""
import re

import pytest

from app import db
from dialer import readiness
from dialer.models import PhoneNumber
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.simulation = True
    db.session.add(PhoneNumber(account_id=owner.id, e164="+18655551212",
                               pool="rep", state="active",
                               twilio_sid="PN" + "f" * 32))
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def check(owner_id):
    return readiness.check(get_settings(owner_id), owner_id)


# ----------------------------------------------------------- the circle
def test_the_agent_warning_points_at_where_agents_are_built(account):
    owner, _ = account
    s = get_settings(owner.id)
    s.set_secret("elevenlabs_key", "sk_x", "elevenlabs_last4")
    from datetime import datetime
    s.elevenlabs_verified_at = datetime.utcnow()
    db.session.commit()

    w = next((w for w in check(owner.id)["warnings"]
              if w["key"] == "ai_agent_missing"), None)
    assert w is not None
    assert w["url"] == "/dialer/agents"
    assert "setup/9" not in w["url"], "step 9 is playbooks and cannot build an agent"


def test_every_warning_carries_somewhere_to_go(account):
    for w in check(account[0].id)["warnings"]:
        assert w["url"].startswith("/"), w


def test_every_warning_has_a_stable_key(account):
    keys = [w["key"] for w in check(account[0].id)["warnings"]]
    assert all(keys), "a warning with no key cannot be dismissed"
    assert len(keys) == len(set(keys)), "two warnings sharing a key hide together"


# --------------------------------------------------------- putting it away
def test_a_warning_can_be_dismissed(account):
    owner, client = account
    before = check(owner.id)["warnings"]
    assert before, "this test needs at least one warning to hide"
    key = before[0]["key"]

    client.post("/dialer/warnings/dismiss", data={"key": key},
                follow_redirects=True)

    after = check(owner.id)
    assert key not in [w["key"] for w in after["warnings"]]
    assert after["hidden_count"] == 1


def test_dismissing_one_leaves_the_others(account):
    owner, client = account
    before = check(owner.id)["warnings"]
    if len(before) < 2:
        pytest.skip("needs two warnings")
    client.post("/dialer/warnings/dismiss", data={"key": before[0]["key"]},
                follow_redirects=True)
    assert before[1]["key"] in [w["key"] for w in check(owner.id)["warnings"]]


def test_hidden_advice_can_be_brought_back(account):
    owner, client = account
    key = check(owner.id)["warnings"][0]["key"]
    client.post("/dialer/warnings/dismiss", data={"key": key},
                follow_redirects=True)
    client.post("/dialer/warnings/restore", follow_redirects=True)
    assert key in [w["key"] for w in check(owner.id)["warnings"]]


def test_a_blocker_can_never_be_dismissed(account):
    """A blocker is the reason nothing will dial. Hiding one would only move
    the confusion to the moment a call silently fails."""
    owner, client = account
    s = get_settings(owner.id)
    s.simulation = False
    db.session.commit()
    blockers = check(owner.id)["blockers"]
    assert blockers, "no Twilio connected, so there should be one"
    for b in blockers:
        client.post("/dialer/warnings/dismiss", data={"key": b["key"]},
                    follow_redirects=True)
    assert len(check(owner.id)["blockers"]) == len(blockers)


def test_the_page_offers_a_way_out_of_each_warning(account):
    owner, client = account
    body = client.get("/dialer/").get_data(as_text=True)
    assert "/dialer/warnings/dismiss" in body
    assert "Not now" in body


# ------------------------------------------------ the voice library itself
def test_the_softphone_does_not_rely_on_one_host():
    """Twilio's own CDN began answering 403 to every version of this file,
    which read as "Could not load the Twilio voice library" and no phone."""
    js = open("static/softphone.js").read()
    urls = re.findall(r"'(https://[^']+twilio[^']*\.js)'", js)
    assert len(urls) >= 2, "one source is a single point of failure"
    hosts = {u.split("/")[2] for u in urls}
    assert len(hosts) >= 2, f"all mirrors share a host: {hosts}"


def test_the_failure_message_says_what_to_suspect():
    js = open("static/softphone.js").read()
    assert "ad blocker" in js or "network block" in js
