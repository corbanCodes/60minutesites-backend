"""Booking the callback the prospect actually asked for.

"Can you try me Thursday morning" was being turned into a follow-up task due
at 4pm in N days, because the only field the analysis returned was a round
number of days and nothing recorded what they said. A task on the wrong day
gets reshuffled, and then the callback never happens.
"""
from datetime import datetime, timedelta

import pytest

from app import Task, db
from dialer.calls import _callback_time, _follow_up
from dialer.models import Call
from tests.conftest import make_lead, make_user


@pytest.fixture
def pieces(ctx):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True)
    lead = make_lead(owner_id=owner.id, name="Dana", phone="+18655551212")
    call = Call(account_id=owner.id, lead_id=lead.id, to_number="+18655551212")
    db.session.add(call)
    db.session.commit()
    return owner, lead, call


def task_for(lead_id):
    return Task.query.filter_by(lead_id=lead_id).first()


# ----------------------------------------------------- reading the time
def test_a_named_time_is_used():
    when = datetime.utcnow() + timedelta(days=2)
    got = _callback_time(when.strftime("%Y-%m-%d %H:%M"))
    assert got is not None
    assert got.strftime("%Y-%m-%d %H:%M") == when.strftime("%Y-%m-%d %H:%M")


def test_a_bare_date_lands_mid_morning_rather_than_midnight():
    when = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
    assert _callback_time(when).hour == 10


def test_a_time_in_the_past_is_refused():
    past = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    assert _callback_time(past) is None


def test_an_absurd_date_is_refused():
    far = (datetime.utcnow() + timedelta(days=400)).strftime("%Y-%m-%d %H:%M")
    assert _callback_time(far) is None


def test_nonsense_is_refused_rather_than_guessed_at():
    """A follow-up on the wrong day is worse than one the rep schedules."""
    for junk in ("sometime next week", "", None, "Thursday", 42):
        assert _callback_time(junk) is None


# ------------------------------------------------------ the task it books
def test_the_task_is_due_when_they_said(pieces):
    owner, lead, call = pieces
    when = datetime.utcnow() + timedelta(days=2)
    _follow_up(call, lead, {"title": "Call Dana back", "kind": "Call",
                            "in_days": 7,
                            "at": when.strftime("%Y-%m-%d %H:%M")})
    db.session.commit()
    t = task_for(lead.id)
    assert t.due_at.date() == when.date(), "in_days must not override a real time"
    assert t.due_at.hour == when.hour


def test_without_a_named_time_it_falls_back_to_the_day_count(pieces):
    owner, lead, call = pieces
    _follow_up(call, lead, {"title": "Try again", "kind": "Call", "in_days": 3})
    db.session.commit()
    t = task_for(lead.id)
    assert (t.due_at.date() - datetime.utcnow().date()).days == 3


def test_their_own_words_are_kept_on_the_task(pieces):
    """The rep picking this up later needs to know it was promised, and in
    what terms, not just that something is due."""
    owner, lead, call = pieces
    _follow_up(call, lead, {"title": "Call back", "kind": "Call", "in_days": 1,
                            "said": "try me Thursday before 10"})
    db.session.commit()
    assert "Thursday before 10" in task_for(lead.id).title


def test_the_words_are_not_repeated_when_already_in_the_title(pieces):
    owner, lead, call = pieces
    _follow_up(call, lead, {"title": "Call Thursday morning", "kind": "Call",
                            "in_days": 1, "said": "Thursday morning"})
    db.session.commit()
    assert task_for(lead.id).title.count("Thursday morning") == 1


def test_no_follow_up_means_no_task(pieces):
    owner, lead, call = pieces
    _follow_up(call, lead, None)
    db.session.commit()
    assert task_for(lead.id) is None


# ---------------------------------------------- what the AI is told to do
def test_the_agent_is_told_to_ask_for_a_specific_time(ctx):
    from dialer.agents import build_prompt
    from dialer.models import AiAgent
    from dialer.settings_store import get_settings
    owner = make_user(name="N", email="a@n.test", dialer=True)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    agent = AiAgent(account_id=owner.id, name="Q", direction="outbound")
    prompt = build_prompt(agent, s)
    assert "better time" in prompt
    assert "morning or the afternoon" in prompt
    assert "END THE CALL" in prompt


def test_the_agent_is_told_to_stop_selling_the_moment_it_can_transfer(ctx):
    """The client's whole ask: qualify, then hand over immediately."""
    from dialer.agents import build_prompt
    from dialer.models import AiAgent, Playbook
    from dialer.settings_store import get_settings
    owner = make_user(name="N", email="b@n.test", dialer=True)
    s = get_settings(owner.id)
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer when they decide on napkins.")
    db.session.add(pb)
    db.session.flush()
    agent = AiAgent(account_id=owner.id, name="Q", playbook_id=pb.id)
    prompt = build_prompt(agent, s)
    assert "STOP SELLING" in prompt
    assert "call the transfer tool" in prompt
    assert "Do not wait for them to answer" in prompt
