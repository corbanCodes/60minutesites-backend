"""Why step 9 would not go green, and the draft button that fixes it.

The page said "Your playbooks 1" and the step stayed grey. Both were right:
the only playbook on the account was the demo one, and the wizard has
deliberately not counted demo content since the day the checklist claimed
8 of 11 steps were done before anyone had touched it. What was missing was
anyone saying so. A number that disagrees with a tick and explains neither
is worse than either one alone.
"""
import json

import pytest

from app import db
from dialer.demo import DEMO_PREFIX
from dialer.models import Playbook
from dialer.playbook_ai import draft
from dialer.settings_store import get_settings
from dialer import wizard
from tests.conftest import make_user


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def add_playbook(owner_id, name, transfer=""):
    pb = Playbook(account_id=owner_id, name=name, steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria=transfer)
    db.session.add(pb)
    db.session.commit()
    return pb


def status(owner_id):
    return wizard.status(get_settings(owner_id), owner_id)


# ------------------------------------------------- the disagreement itself
def test_a_demo_playbook_does_not_complete_the_step(account):
    owner, _ = account
    add_playbook(owner.id, DEMO_PREFIX + "Napkin outreach")
    assert status(owner.id)["playbook"] != "done"


def test_the_page_says_out_loud_that_the_sample_does_not_count(account):
    """The actual fix. The rule was already right; nothing communicated it."""
    owner, client = account
    add_playbook(owner.id, DEMO_PREFIX + "Napkin outreach")
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert "only playbook here is sample data" in body
    assert "Sample" in body


def test_the_count_shown_is_the_count_that_matters(account):
    """Showing 1 beside a step that will not complete is the whole bug."""
    owner, client = account
    add_playbook(owner.id, DEMO_PREFIX + "Napkin outreach")
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert 'count-chip">0<' in body


def test_a_real_playbook_completes_the_step(account):
    owner, _ = account
    add_playbook(owner.id, "Napkin outreach")
    assert status(owner.id)["playbook"] == "done"


def test_no_warning_once_a_real_one_exists(account):
    owner, client = account
    add_playbook(owner.id, DEMO_PREFIX + "Sample")
    add_playbook(owner.id, "Mine")
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert "only playbook here is sample data" not in body


# ----------------------------------------------------- the transfer column
def test_a_playbook_with_no_transfer_rule_is_flagged(account):
    """He picked qualify-then-transfer and could not find where transfer is
    configured, because the list never mentioned it."""
    owner, client = account
    add_playbook(owner.id, "No transfer set")
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert "<th>Hands to a person</th>" in body
    assert "Never" in body


def test_a_playbook_with_a_transfer_rule_reads_as_set(account):
    owner, client = account
    add_playbook(owner.id, "Has one", transfer="Transfer on a yes.")
    body = client.get("/dialer/setup/9").get_data(as_text=True)
    assert ">Yes<" in body


# ------------------------------------------------------------ the drafter
def test_a_draft_is_written_and_completes_the_step(account):
    owner, client = account
    add_playbook(owner.id, DEMO_PREFIX + "Sample")
    assert status(owner.id)["playbook"] != "done"

    client.post("/dialer/playbooks/draft", follow_redirects=True, data={
        "brief": "We give bars free napkins with a QR code on them and pay "
                 "them two hundred dollars plus free drinks."})

    mine = [p for p in Playbook.query.filter_by(account_id=owner.id)
            if not p.name.startswith(DEMO_PREFIX)]
    assert len(mine) == 1
    assert status(owner.id)["playbook"] == "done"


def test_a_draft_arrives_with_every_part_filled_in(account):
    owner, client = account
    client.post("/dialer/playbooks/draft", follow_redirects=True, data={
        "brief": "We sell commercial roof inspections to property managers "
                 "in Tennessee."})
    pb = Playbook.query.filter_by(account_id=owner.id).first()
    assert pb.steps and pb.questions and pb.objections
    assert pb.transfer_criteria, "a draft with no transfer rule repeats the bug"
    assert pb.never_do


def test_too_short_a_brief_is_refused_rather_than_guessed_at(account):
    owner, client = account
    r = client.post("/dialer/playbooks/draft", data={"brief": "napkins"},
                    follow_redirects=True)
    assert Playbook.query.filter_by(account_id=owner.id).count() == 0
    assert "bit more about the offer" in r.get_data(as_text=True)


def test_the_first_draft_becomes_the_default(account):
    owner, client = account
    client.post("/dialer/playbooks/draft", follow_redirects=True,
                data={"brief": "We clean commercial kitchen extraction hoods."})
    assert Playbook.query.filter_by(account_id=owner.id).first().is_default


# --------------------------------------------- nothing from a model is trusted
class Stub:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, user, max_tokens=800, json_mode=False):
        return {"ok": True, "data": self.payload}


def _draft_with(monkeypatch, payload, settings):
    from dialer.providers import registry
    monkeypatch.setattr(registry, "llm", lambda s: Stub(payload))
    return draft(settings, "A brief that is comfortably long enough to pass.")


def test_a_step_with_no_words_is_dropped(account, monkeypatch):
    owner, _ = account
    r = _draft_with(monkeypatch, {
        "name": "x", "steps": [{"title": "Open", "say": "Hello there."},
                               {"title": "Empty", "say": ""}]},
        get_settings(owner.id))
    assert [s["title"] for s in r["playbook"]["steps"]] == ["Open"]


def test_an_objection_nobody_can_trigger_is_dropped(account, monkeypatch):
    """The rep's rail matches on the trigger phrases, so one without any is
    dead weight on screen during a live call."""
    owner, _ = account
    r = _draft_with(monkeypatch, {
        "steps": [{"title": "Open", "say": "Hello."}],
        "objections": [{"trigger_phrases": [], "response": "unreachable"},
                       {"trigger_phrases": ["too expensive"], "response": "ok"}]},
        get_settings(owner.id))
    assert len(r["playbook"]["objections"]) == 1


def test_a_field_name_is_made_storable(account, monkeypatch):
    owner, _ = account
    r = _draft_with(monkeypatch, {
        "steps": [{"title": "Open", "say": "Hello."}],
        "questions": [{"question": "Do you own the building?",
                       "collect_as": "Owns The Building?!"}]},
        get_settings(owner.id))
    assert r["playbook"]["questions"][0]["collect_as"] == "owns_the_building"


def test_a_reply_with_no_steps_is_an_error_not_an_empty_playbook(account, monkeypatch):
    owner, _ = account
    r = _draft_with(monkeypatch, {"name": "Nothing useful"},
                    get_settings(owner.id))
    assert r["ok"] is False
    assert "script steps" in r["error"]


def test_junk_instead_of_an_object_is_handled(account, monkeypatch):
    owner, _ = account
    r = _draft_with(monkeypatch, ["not", "a", "dict"], get_settings(owner.id))
    assert r["ok"] is False
