"""The system half of the NapkinAds guide.

"Schedule callback at 4 PM" has to create a future call, not appear in
a transcript. The manager's name has to be known on the next call. Two
endings the guide names had no disposition. Asked whether it is an AI,
the agent hangs up. Every call ends with a note.
"""
from datetime import datetime

import pytest

from app import Lead, Note, Task, db
from dialer import agents as agents_mod, when
from dialer.agents import build_prompt
from dialer.campaigns import close_queue_row
from dialer.context import lead_vars
from dialer.models import (DEFAULT_STAGE_MAP, DISPOSITION_LABELS, Call,
                           Campaign, CampaignLead)
from dialer.providers import elevenlabs_live
from dialer.tools import TOOL_SPECS, account_token, run_tool
from dialer import calls as calls_mod
from tests.test_owned_handoff import world, placed_call, AI  # noqa: F401

# Thursday 2026-10-08 10:00 in Chicago == 15:00 UTC
NOW = datetime(2026, 10, 8, 15, 0)
CHI = "America/Chicago"


def at(local_h, local_m=0, days=0):
    """Chicago local -> the UTC naive the system stores (CDT, UTC-5)."""
    from datetime import timedelta
    return datetime(2026, 10, 8) + timedelta(days=days, hours=local_h + 5,
                                             minutes=local_m)


# ------------------------------------------------------------ resolve
@pytest.mark.parametrize("said, expect, kind", [
    ("around 4", at(16), "specific"),
    ("at 4pm", at(16), "specific"),
    ("4:30", at(16, 30), "specific"),
    ("after 5", at(17, 15), "specific"),
    ("he's here after 5", at(17, 15), "specific"),
    ("11", at(11), "specific"),
    ("7", at(19), "specific"),
    ("noon", at(12), "specific"),
    ("tomorrow at noon", at(12, days=1), "specific"),
    ("tomorrow morning", at(10, days=1), "window"),
    ("this afternoon", at(15), "window"),
    ("tonight", at(18), "window"),
    ("between 3 and 6", at(16), "window"),
    ("usually between 3 and 6", at(16), "window"),
    ("Monday morning", at(10, days=4), "window"),
    ("thursday", at(11, days=7), "day"),
    ("tomorrow", at(11, days=1), "day"),
    ("in 30 minutes", at(10, 30), "soon"),
    ("try again in 30 minutes", at(10, 30), "soon"),
    ("in an hour", at(11), "soon"),
    ("in a couple of hours", at(12), "soon"),
    ("later", at(12), "soon"),
])
def test_their_words_become_a_time_in_their_zone(said, expect, kind):
    got, k, pretty = when.resolve(said, CHI, now=NOW)
    assert (got, k) == (expect, kind), (said, got, k, pretty)


def test_a_time_already_gone_today_means_tomorrow():
    got, k, _ = when.resolve("around 4", CHI, now=datetime(2026, 10, 8, 22, 30))
    assert got == at(16, days=1) and k == "specific"


def test_nothing_usable_is_vague():
    assert when.resolve("whenever", CHI, now=NOW) == (None, "vague", "")
    assert when.resolve("", CHI, now=NOW) == (None, "vague", "")


def test_the_pretty_form_is_the_venues_clock():
    _, _, pretty = when.resolve("around 4", CHI, now=NOW)
    assert pretty == "today 4:00 PM"
    _, _, pretty = when.resolve("tomorrow at noon", CHI, now=NOW)
    assert pretty == "tomorrow 12:00 PM"


# ------------------------------------------------------------- the tool
def _queued(owner, s, agent):
    call = placed_call(owner, s, agent)
    camp = Campaign(account_id=owner.id, name="Venues", mode="ai",
                    status="running")
    db.session.add(camp)
    db.session.flush()
    cl = CampaignLead(campaign_id=camp.id, lead_id=call.lead_id,
                      account_id=owner.id, state="claimed", attempts=1,
                      lead_tz="America/New_York")
    db.session.add(cl)
    db.session.flush()
    call.campaign_id, call.campaign_lead_id = camp.id, cl.id
    db.session.commit()
    return call, cl


def test_a_callback_books_the_next_call_in_the_venues_zone(world):
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    lead = db.session.get(Lead, call.lead_id)
    lead.timezone = CHI
    db.session.commit()
    r = run_tool("schedule_callback",
                 {"when": "Mike usually comes in around 5", "manager_name": "Mike",
                  "asked_by": "staff", "hq_call_id": str(call.id)},
                 account_token(owner.id))
    assert r["ok"] and r["scheduled"] and "5:00 PM" in r["for"]
    lead = db.session.get(Lead, call.lead_id)
    assert lead.decision_maker == "Mike"
    assert lead.callback_said == "Mike usually comes in around 5"
    assert lead.callback_at.hour == 22, "5 PM Chicago is 22:00 UTC"
    cl = db.session.get(CampaignLead, cl.id)
    assert cl.state == "deferred" and cl.next_attempt_at == lead.callback_at
    assert cl.position < 0, "outranks a plain redial"
    task = Task.query.filter_by(lead_id=lead.id, kind="Call").one()
    assert task.due_at == lead.callback_at and "Mike" in task.title
    note = Note.query.filter_by(lead_id=lead.id, kind="ai_summary").order_by(Note.id.desc()).first()
    assert "Callback booked" in note.body and "Mike" in note.body


def test_a_manager_s_own_request_outranks_a_staff_time(world):
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    run_tool("schedule_callback", {"when": "tomorrow at noon", "asked_by": "manager",
                                   "hq_call_id": str(call.id)}, account_token(owner.id))
    assert db.session.get(CampaignLead, cl.id).position == -30


def test_a_vague_answer_books_nothing_and_says_so(world):
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    r = run_tool("schedule_callback", {"when": "whenever", "hq_call_id": str(call.id)},
                 account_token(owner.id))
    assert r["ok"] and r["scheduled"] is False and "ask once" in r["message"]
    assert Task.query.filter_by(lead_id=call.lead_id).count() == 0
    assert db.session.get(CampaignLead, cl.id).state == "claimed"


def test_the_booked_time_survives_the_call_closing(world):
    """close_queue_row used to overwrite next_attempt_at with the retry
    policy's fixed minutes, which would have thrown the time away."""
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    run_tool("schedule_callback", {"when": "around 4", "hq_call_id": str(call.id)},
             account_token(owner.id))
    run_tool("set_disposition", {"disposition": "callback", "hq_call_id": str(call.id)},
             account_token(owner.id))
    client.post(f"/dialer/hooks/twilio/{owner.id}/status",
                data={"CallSid": call.twilio_sid, "CallStatus": "completed",
                      "CallDuration": "40"})
    c = db.session.get(Call, call.id)
    cl = db.session.get(CampaignLead, cl.id)
    assert c.finalized_at and c.callback_at
    assert cl.state == "deferred" and cl.next_attempt_at == c.callback_at


def test_manager_busy_retries_in_half_an_hour(world):
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    run_tool("set_disposition", {"disposition": "manager_busy", "hq_call_id": str(call.id)},
             account_token(owner.id))
    call = db.session.get(Call, call.id)
    call.status = "completed"
    db.session.commit()
    close_queue_row(call)
    cl = db.session.get(CampaignLead, cl.id)
    assert cl.state == "deferred"
    assert 25 * 60 <= (cl.next_attempt_at - datetime.utcnow()).total_seconds() <= 31 * 60


def test_business_closed_ends_the_calling(world):
    owner, s, agent, tel, va, client = world
    call, cl = _queued(owner, s, agent)
    run_tool("set_disposition", {"disposition": "business_closed", "hq_call_id": str(call.id)},
             account_token(owner.id))
    call = db.session.get(Call, call.id)
    assert call.disposition == "business_closed"
    close_queue_row(call)
    assert db.session.get(CampaignLead, cl.id).state == "done"
    assert DEFAULT_STAGE_MAP["business_closed"] == "Dead"
    assert "Business closed" in DISPOSITION_LABELS.values()


# ----------------------------------------------------- the next call knows
def test_the_next_call_is_told_the_managers_name_and_the_last_note(world):
    owner, s, agent, tel, va, client = world
    call = placed_call(owner, s, agent)
    run_tool("schedule_callback", {"when": "around 4", "manager_name": "Dana",
                                   "hq_call_id": str(call.id)}, account_token(owner.id))
    lead = db.session.get(Lead, call.lead_id)
    v = lead_vars(lead)
    assert v["decision_maker"] == "Dana" and "Callback booked" in v["last_note"]
    assert set(lead_vars(None)) == set(v), "always the whole dict"
    # and the connect hook hands exactly that to the vendor on the NEXT call
    second = calls_mod.start_call(owner.id, lead, "ai_outbound", s,
                                  from_number=AI, ai_agent=agent)
    second.twilio_sid = "CAowned2"
    db.session.commit()
    client.post(f"/dialer/hooks/twilio/ai/{second.id}/connect",
                data={"CallSid": "CAowned2"})
    sent = va.registered[-1]["variables"]
    assert sent["decision_maker"] == "Dana" and sent["hq_call_id"] == str(second.id)


def test_the_prompt_carries_the_owners_rules(world):
    owner, s, agent, tel, va, client = world
    from dialer import napkin
    r = client.post("/dialer/playbooks/napkin", follow_redirects=True, data={})
    from dialer.models import AiAgent, Playbook
    pb = Playbook.query.filter_by(account_id=owner.id, name=napkin.NAME).one()
    a = AiAgent.query.filter_by(playbook_id=pb.id).one()
    p = build_prompt(a, s)
    assert "schedule_callback" in p
    assert "asks whether you are an AI" in p and "end_call" in p
    assert "at most\ntwice" in p or "at most twice" in p
    assert "A call without a note is a failed call" in p
    assert "{{decision_maker}}" in p
    assert "business_closed" in p and "manager_busy" in p


def test_every_agent_gets_the_end_call_tool(monkeypatch):
    sent = {}

    class S:
        def secret(self, name):
            return "k"
    va = elevenlabs_live.ElevenLabsAgent(S())
    monkeypatch.setattr(va, "_req", lambda m, p, **kw: sent.update(kw) or
                        {"ok": True, "data": {"agent_id": "ag_1"}})

    class A:
        elevenlabs_agent_id = "ag_1"
        name = "x"; first_message = ""; voice_id = "v"; llm_model = ""
        voice_delivery = "calm"; background_preset = ""; max_duration_seconds = 240
        voicemail_behavior = "leave_tts"; dtmf_enabled = False
    va.upsert_agent(A(), "prompt", [], transfer=None)
    bit = sent["json"]["conversation_config"]["agent"]["prompt"]["built_in_tools"]
    assert bit["end_call"]["params"]["system_tool_type"] == "end_call"
    assert "transfer_to_number" not in bit


def test_the_schedule_tool_is_in_the_vendors_tool_set(world):
    names = [t["name"] for t in TOOL_SPECS]
    assert "schedule_callback" in names
    spec = next(t for t in TOOL_SPECS if t["name"] == "schedule_callback")
    assert spec["parameters"]["required"] == ["when"]
    assert "hq_call_id" in spec["parameters"]["properties"]
    disp = next(t for t in TOOL_SPECS if t["name"] == "set_disposition")
    enum = disp["parameters"]["properties"]["disposition"]["enum"]
    assert "manager_busy" in enum and "business_closed" in enum
