"""One timeline for a hand-off, server and browser, on one clock.

A night was spent reconstructing hand-offs from an HTTP log of paths and
timestamps. The questions that mattered -- what From the transferred leg
carried, which signal recognised it, where the rep leg went, what the
browser SDK did and when -- were each answerable only by adding a log line
and running another live call. Every step now writes a row, the browser
posts its own, and one page merges them.
"""
import pytest

from app import db
from dialer import bridge, calls as calls_mod, trace
from dialer.models import AiAgent, Call, CallEvent, PhoneNumber, Playbook
from dialer.providers import registry
from dialer.settings_store import get_settings
from tests.conftest import make_lead, make_user

LINE = "+18655550101"
AI = "+18655550102"
PROSPECT = "+18655558888"
HUMAN = "+14235550147"


class FakeTelephony:
    def __init__(self):
        self.created, self.redirected, self.configured, self.hungup = [], [], [], []
        self.current_voice_url = ""

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        self.created.append({"to": to, "from_": from_, **kw})
        return {"ok": True, "sid": "CArep1"}

    def redirect_call(self, sid, twiml):
        self.redirected.append({"sid": sid, "twiml": twiml})
        return {"ok": True}

    def configure_number(self, sid, voice_url, status_callback):
        self.configured.append(sid)
        return {"ok": True}

    def fetch_number(self, sid):
        return {"ok": True, "voice_url": "", "status_callback": ""}

    def hangup(self, sid):
        self.hungup.append(sid)
        return {"ok": True}


@pytest.fixture
def world(ctx, client, monkeypatch):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    s = get_settings(owner.id)
    s.ai_disclosure_name = "NapkinAds"
    s.enforce_window = False
    db.session.add(PhoneNumber(account_id=owner.id, e164=LINE, pool="rep",
                               state="active", twilio_sid="PN" + "a" * 32,
                               friendly_name="Rep line", area_code="865"))
    db.session.add(PhoneNumber(account_id=owner.id, e164=AI, pool="ai",
                               state="active", twilio_sid="PN" + "b" * 32,
                               friendly_name="AI line", area_code="865",
                               elevenlabs_phone_id="pn_1"))
    pb = Playbook(account_id=owner.id, name="P", steps_json="[]",
                  questions_json="[]", objections_json="[]",
                  transfer_criteria="Transfer on a decision maker.")
    db.session.add(pb)
    db.session.flush()
    agent = AiAgent(account_id=owner.id, name="John — venue calls",
                    direction="outbound", active=True, playbook_id=pb.id,
                    transfer_handoff="bridge", transfer_to_number=HUMAN,
                    elevenlabs_agent_id="ag_1")
    db.session.add(agent)
    db.session.commit()
    fake = FakeTelephony()
    monkeypatch.setattr(registry, "telephony", lambda settings: fake)
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, s, agent, fake, client


def live_call(owner, s, agent):
    lead = make_lead(owner_id=owner.id, phone=PROSPECT)
    call = calls_mod.start_call(owner.id, lead, "ai_outbound", s,
                                from_number=AI, ai_agent=agent)
    call.status = "in-progress"
    db.session.commit()
    return call


def handoff(client, owner, sid="CAprospect1", frm=AI):
    return client.post(f"/dialer/hooks/twilio/{owner.id}/voice",
                       data={"From": frm, "To": LINE, "CallSid": sid,
                             "Direction": "outbound-dial",
                             "ParentCallSid": "CAparent"}
                       ).get_data(as_text=True)


def kinds(call_id):
    return [e.kind for e in CallEvent.query.filter_by(call_id=call_id)
            .order_by(CallEvent.at, CallEvent.id)]


# -------------------------------------------------------------- the rows
def test_record_never_raises_and_prefixes_the_kind(world):
    owner, s, agent, fake, client = world
    trace.record(owner.id, "thing", "happened", payload={"a": object()})
    e = CallEvent.query.filter_by(account_id=owner.id).order_by(CallEvent.id.desc()).first()
    assert e.kind == "trace:thing" and e.detail == "happened"
    assert "a" in e.payload


def test_the_transferred_leg_is_recorded_with_everything_twilio_sent(world):
    owner, s, agent, fake, client = world
    live_call(owner, s, agent)
    handoff(client, owner)
    row = (CallEvent.query.filter_by(account_id=owner.id, kind="trace:voice_in")
           .order_by(CallEvent.id.desc()).first())
    assert f"from={AI}" in row.detail and f"to={LINE}" in row.detail
    assert "parent=CAparent" in row.detail
    assert '"Direction": "outbound-dial"' in row.payload


def test_a_bridged_handoff_leaves_a_full_server_trail_on_the_call(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    k = kinds(call.id)
    assert "trace:detect" in k and "trace:rep_leg" in k and "trace:park" in k
    det = CallEvent.query.filter_by(call_id=call.id, kind="trace:detect").one()
    assert "signal=from_is_ai_number" in det.detail
    leg = CallEvent.query.filter_by(call_id=call.id, kind="trace:rep_leg").one()
    assert f"to={HUMAN}" in leg.detail and "sid=CArep1" in leg.detail
    park = CallEvent.query.filter_by(call_id=call.id, kind="trace:park").one()
    assert "<Conference" in park.payload


def test_the_signal_that_fired_is_named(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner, frm="+12125550000")
    det = CallEvent.query.filter_by(call_id=call.id, kind="trace:detect").one()
    assert "signal=one_live_bridge_call" in det.detail


def test_a_miss_is_recorded_too(world):
    owner, s, agent, fake, client = world
    handoff(client, owner, frm="+12125550000")
    assert CallEvent.query.filter_by(account_id=owner.id,
                                     kind="trace:detect_miss").count() == 1


def test_the_wait_fetch_is_tied_to_the_call_by_room(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    body = handoff(client, owner)
    assert "bridge/wait?room=handoff-CAprospect1" in body
    client.get(f"/dialer/hooks/twilio/{owner.id}/bridge/wait?room=handoff-CAprospect1")
    assert "trace:wait_fetched" in kinds(call.id)


def test_rep_status_and_amd_land_on_the_call(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/rep",
                data={"CallStatus": "ringing", "CallSid": "CArep1", "To": HUMAN})
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/amd",
                data={"AnsweredBy": "human", "CallSid": "CArep1"})
    k = kinds(call.id)
    assert "trace:rep_status" in k and "trace:amd_hook" in k and "trace:amd" in k
    st = CallEvent.query.filter_by(call_id=call.id, kind="trace:rep_status").one()
    assert "CallStatus=ringing" in st.detail


def test_a_freed_prospect_is_recorded(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/rep",
                data={"CallStatus": "no-answer", "CallSid": "CArep1"})
    fr = CallEvent.query.filter_by(call_id=call.id, kind="trace:freed").one()
    assert "no-answer" in fr.detail and "redirect_ok=True" in fr.detail


# ------------------------------------------------------------ the browser
def test_the_browser_posts_its_own_rows_onto_the_current_handoff(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    r = client.post("/dialer/phone/trace", json={"events": [
        {"kind": "incoming", "detail": "from +1865", "t": "2026-10-03T14:00:00.250Z",
         "data": {"available": True}, "perf": 1234},
        {"kind": "call_accept", "detail": "", "t": "2026-10-03T14:00:00.900Z"},
    ]}).get_json()
    assert r["ok"] and r["stored"] == 2
    rows = (CallEvent.query.filter_by(call_id=call.id)
            .filter(CallEvent.kind.like("trace:browser:%"))
            .order_by(CallEvent.at).all())
    assert [x.kind for x in rows] == ["trace:browser:incoming", "trace:browser:call_accept"]
    assert rows[0].at.hour == 14 and rows[0].at.microsecond == 250000, \
        "the browser's own clock is kept"
    assert '"available": true' in rows[0].payload


def test_junk_from_the_browser_is_ignored_not_fatal(world):
    owner, s, agent, fake, client = world
    r = client.post("/dialer/phone/trace", json={"events": ["x", None, {"kind": "ok", "t": "nope"}]}).get_json()
    assert r["ok"] and r["stored"] == 1


# --------------------------------------------------------------- the page
def test_the_trace_page_merges_everything_in_time_order(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    handoff(client, owner)
    client.post(f"/dialer/hooks/twilio/{owner.id}/bridge/handoff-CAprospect1/rep",
                data={"CallStatus": "ringing", "CallSid": "CArep1"})
    client.post("/dialer/phone/trace", json={"events": [
        {"kind": "call_accept", "detail": "", "t": bridge._now().isoformat() + "Z"}]})

    rows = trace.timeline(owner.id, call)
    ks = [r["kind"] for r in rows]
    assert "trace:voice_in" in ks and "trace:park" in ks
    assert "trace:rep_status" in ks and "inbox:bridge_rep" in ks
    assert "trace:browser:call_accept" in ks
    ats = [r["at"] for r in rows if r["at"]]
    assert ats == sorted(ats)
    first = next(r for r in rows if r["kind"] == "trace:voice_in")
    assert first["rel"] == 0.0

    body = client.get("/dialer/handoff/trace").get_data(as_text=True)
    assert "Hand-off trace" in body and "trace:voice_in" in body
    text = client.get("/dialer/handoff/trace?format=text").get_data(as_text=True)
    assert "voice_in" in text and "+0.000s" in text


def test_the_page_is_calm_when_nothing_has_happened(world):
    owner, s, agent, fake, client = world
    body = client.get("/dialer/handoff/trace").get_data(as_text=True)
    assert "Nothing traced yet" in body


def test_the_page_is_linked_from_where_a_test_starts_and_ends(world):
    owner, s, agent, fake, client = world
    call = live_call(owner, s, agent)
    assert "/dialer/handoff/trace" in client.get("/dialer/setup/12").get_data(as_text=True)
    assert "/dialer/handoff/trace?call=" in client.get(f"/dialer/calls/{call.id}").get_data(as_text=True)
    assert "/dialer/handoff/trace" in client.get("/dialer/phone").get_data(as_text=True)


def test_another_account_s_call_cannot_be_traced(world, ctx):
    owner, s, agent, fake, client = world
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = Call(account_id=other.id, mode="ai_outbound", direction="outbound",
                  to_number="+12125550000", status="queued")
    db.session.add(theirs)
    db.session.commit()
    assert client.get(f"/dialer/handoff/trace?call={theirs.id}").status_code == 403
