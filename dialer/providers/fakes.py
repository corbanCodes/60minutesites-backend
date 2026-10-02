"""Simulation providers. Every screen and every flow works with no vendor
account and no money spent -- which is also the safest surface for a live demo.

Outcomes are DETERMINISTIC, keyed off the last digit of the number dialled, so
a demo can be rehearsed and a test can assert:
    ...1 human answers        ...4 no answer
    ...2 answering machine    ...5 wrong number
    ...3 busy                 anything else -> human
Line type is keyed the same way: ...6 mobile, ...7 VoIP, else landline.
"""
import base64
import hashlib
import json
import time
from datetime import datetime, timezone

from dialer.providers.base import LLM, Telephony, Transcriber, VoiceAgent, err, ok

# 0.4s of silence, 8kHz mono WAV -- stands in for a recording.
_WAV = base64.b64decode(
    b"UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAA"
    b"AAAAAAAAAAAAAAAAAAAAAA==")


def _digits(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _sid(prefix, seed):
    h = hashlib.sha1(str(seed).encode()).hexdigest()[:32]
    return f"{prefix}{h}"


def outcome_for(number):
    d = _digits(number)
    return {"1": "answered_human", "2": "answered_machine", "3": "busy",
            "4": "no_answer", "5": "wrong_number"}.get(d[-1:] or "1", "answered_human")


def line_type_for(number):
    d = _digits(number)
    return {"6": "mobile", "7": "nonFixedVoip", "8": "fixedVoip"}.get(
        d[-1:] or "0", "landline")


class FakeTelephony(Telephony):
    def __init__(self, settings=None, fail=None):
        self.settings = settings
        self.fail = fail or ""

    def _maybe_fail(self):
        return err("Simulated Twilio failure (DIALER_SIMULATION_FAIL=twilio)",
                   "sim_fail") if self.fail == "twilio" else None

    def verify(self):
        return self._maybe_fail() or ok(
            account_name="Simulated Twilio Account", balance="42.50",
            is_trial=False, numbers=[n["e164"] for n in self._numbers()])

    def _numbers(self):
        return [
            {"e164": "+18655550101", "sid": _sid("PN", "0101"),
             "friendly_name": "Knoxville 865", "region": "TN"},
            {"e164": "+12125550102", "sid": _sid("PN", "0102"),
             "friendly_name": "New York 212", "region": "NY"},
        ]

    def list_numbers(self):
        return ok(numbers=self._numbers())

    def search_numbers(self, area_code=None, contains=None, limit=10):
        ac = _digits(area_code) or "865"
        out = [{"e164": f"+1{ac}555{1000 + i:04d}",
                "friendly_name": f"({ac}) 555-{1000 + i:04d}",
                "region": "TN", "monthly": 1.15} for i in range(min(limit, 6))]
        return ok(numbers=out)

    def buy_number(self, e164, voice_url, status_callback):
        return ok(e164=e164, sid=_sid("PN", e164))

    def release_number(self, sid):
        return ok()

    def configure_number(self, sid, voice_url, status_callback):
        return ok()

    def ensure_twiml_app(self, voice_url, friendly_name):
        return ok(sid=_sid("AP", voice_url))

    def ensure_api_key(self, friendly_name):
        return ok(sid=_sid("SK", friendly_name), secret="sim-secret-0000")

    def access_token(self, identity, twiml_app_sid, ttl=3600):
        payload = base64.urlsafe_b64encode(
            json.dumps({"identity": identity, "sim": True,
                        "exp": int(time.time()) + ttl}).encode()).decode()
        return ok(token=f"simtoken.{payload}", identity=identity, expires_in=ttl)

    # ---- calls: record the intent, then let the simulator drive the webhooks
    def dial_participant(self, conference, to, from_, **kw):
        f = self._maybe_fail()
        if f:
            return f
        sid = _sid("CA", f"{conference}{to}{time.time()}")
        kw["record"] = bool(kw.get("record"))
        _SIM.schedule(sid, to, conference=conference, **kw)
        return ok(sid=sid, outcome=outcome_for(to))

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        f = self._maybe_fail()
        if f:
            return f
        sid = _sid("CA", f"{to}{time.time()}")
        kw["record"] = bool(kw.get("record"))
        _SIM.schedule(sid, to, **kw)
        return ok(sid=sid, outcome=outcome_for(to))

    def redirect_call(self, sid, twiml):
        _SIM.mark(sid, "redirected")
        return ok()

    def hangup(self, sid):
        _SIM.mark(sid, "completed")
        return ok()

    def update_participant(self, conference, call_sid, **kw):
        return ok(applied=kw)

    def fetch_call(self, sid):
        st = _SIM.state(sid)
        return ok(status=st.get("status", "completed"),
                  duration=st.get("duration", 0), price=st.get("price", 0.0),
                  answered_by=st.get("answered_by", ""))

    def fetch_recording(self, sid):
        return ok(content=_WAV, mimetype="audio/wav", duration=12)

    def delete_recording(self, sid):
        return ok()

    def lookup(self, e164):
        lt = line_type_for(e164)
        return ok(line_type=lt, carrier="Simulated Carrier",
                  raw={"line_type_intelligence": {"type": lt,
                                                  "carrier_name": "Simulated Carrier"},
                       "simulated": True})

    def validate_signature(self, signature, url, params):
        return True  # the fake signs with "sim"; routes_hooks accepts it

    def customer_profiles(self):
        return ok(status="business", sid=_sid("BU", "pcp"))


class FakeVoiceAgent(VoiceAgent):
    def __init__(self, settings=None, fail=None):
        self.settings = settings
        self.fail = fail or ""

    def verify(self):
        if self.fail == "elevenlabs":
            return err("Simulated ElevenLabs failure", "sim_fail")
        return ok(tier="pro", concurrency=20, voices=self.list_voices()["voices"])

    def list_voices(self, limit=40):
        # No preview_url: practice mode has no audio to play, and a dead
        # play button is worse than none, so the template hides it.
        return ok(voices=[
            {"voice_id": "sim-rachel", "name": "Rachel", "labels": "calm, American",
             "preview_url": "", "category": "premade", "hq_models": []},
            {"voice_id": "sim-adam", "name": "Adam", "labels": "deep, American",
             "preview_url": "", "category": "premade", "hq_models": []},
            {"voice_id": "sim-bella", "name": "Bella", "labels": "friendly, American",
             "preview_url": "", "category": "cloned", "hq_models": []},
            {"voice_id": "sim-josh", "name": "Josh", "labels": "warm, American",
             "preview_url": "", "category": "premade", "hq_models": []},
        ][:limit])

    def speak(self, text, voice_id, model_id=""):
        # A real, playable 0.4s WAV tone, so practice mode exercises the whole
        # save-and-play path rather than storing a string that fails later.
        import math
        import struct
        rate, secs = 8000, 0.4
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * secs)))
        header = (b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt "
                  + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
                  + b"data" + struct.pack("<I", len(frames)))
        return ok(audio=header + frames, mimetype="audio/wav")

    def ensure_webhook(self, url, name):
        return ok(webhook_id=_sid("wh", url), secret="wsec_simulated_secret")

    def upsert_agent(self, agent, prompt, tools, webhook_id=None,
                     transfer=None, first_message=None):
        return ok(agent_id=agent.elevenlabs_agent_id or _sid("ag", agent.name))

    def get_agent(self, agent_id):
        return ok(name="Simulated agent", first_message="",
                  voice_id="sim-rachel", llm="", background={},
                  has_transfer=True, tool_count=4, prompt_chars=1200)

    def import_number(self, e164, twilio_sid, twilio_token, agent_id=None,
                      label="", account_auth_token=None):
        return ok(phone_number_id=_sid("pn", e164))

    def outbound_call(self, agent_id, phone_number_id, to, variables=None):
        if self.fail == "elevenlabs":
            return err("Simulated ElevenLabs failure", "sim_fail")
        cid = _sid("cv", f"{to}{time.time()}")
        sid = _sid("CA", f"el{to}{time.time()}")
        _SIM.schedule(sid, to, conversation_id=cid, ai=True,
                      variables=variables or {})
        return ok(conversation_id=cid, call_sid=sid)

    def conversation(self, conversation_id):
        st = _SIM.by_conversation(conversation_id)
        name = (st.get("variables") or {}).get("lead_name", "the manager")
        biz = (st.get("variables") or {}).get("business", "the venue")
        outcome = st.get("outcome", "answered_human")
        if outcome == "answered_machine":
            transcript = ("agent: Hi, this is an automated assistant calling for "
                          f"{biz}. I'll try again later, or you can reach a person "
                          "at the number on your caller ID. Thanks!")
            analysis = {"disposition": "voicemail_left", "qualified": False}
        else:
            transcript = (
                f"agent: Hi, I'm an AI assistant calling from "
                f"NapkinAds. Is the owner or manager around?\n"
                f"user: This is {name}, I'm the manager. What's this about?\n"
                f"agent: We supply bars and restaurants with free napkins -- they carry "
                f"a small ad, so they cost you nothing. Who handles your napkin orders "
                f"at {biz} today?\n"
                f"user: That'd be me. We go through a case or two a week from our "
                f"restaurant supplier.\n"
                f"agent: Perfect. And roughly how many tables are you running?\n"
                f"user: About forty, plus the bar.\n"
                f"agent: That's a great fit. Let me put you through to a specialist "
                f"who can set it up -- one moment.")
            analysis = {"disposition": "qualified", "qualified": True,
                        "data": {"decision_maker": name, "napkin_volume":
                                 "1-2 cases/week", "tables": "40 plus bar",
                                 "current_supplier": "restaurant supplier"}}
        return ok(transcript=transcript, analysis=analysis,
                  duration=st.get("duration", 96), cost=0.13)

    def conversation_audio(self, conversation_id):
        return ok(content=_WAV, mimetype="audio/wav")

    def register_call(self, agent_id, from_number, to_number, direction,
                      variables=None):
        return ok(twiml="<Response><Say>Simulated ElevenLabs agent</Say></Response>")

    def verify_signature(self, body, header, secret):
        return True


class FakeLLM(LLM):
    """Deterministic, and shaped exactly like the real thing so the finalize
    pipeline is genuinely exercised."""

    def __init__(self, settings=None, fail=None):
        self.settings = settings
        self.fail = fail or ""

    def verify(self):
        if self.fail == "llm":
            return err("Simulated LLM failure", "sim_fail")
        return ok(model="simulated-mini")

    def complete(self, system, user, max_tokens=800, json_mode=False):
        if self.fail == "llm":
            return err("Simulated LLM failure", "sim_fail")
        if not json_mode:
            return ok(text="Simulated summary: spoke with the manager, interested, "
                           "asked for a callback with pricing.")
        # The playbook writer asks the same complete() in json_mode but wants
        # a completely different shape back. Keyed off the system prompt,
        # because the user half is whatever the customer typed.
        if "playbook" in (system or "").lower():
            return ok(data=_sim_playbook(user or ""))
        # Look only at the transcript, never at the instructions wrapped
        # around it -- the schema itself mentions "voicemail_left".
        body = (user or "")
        marker = "TRANSCRIPT:"
        text = (body.split(marker, 1)[1] if marker in body else body).lower()
        machine = ("answering machine" in text
                   or "leave a message after" in text
                   or "you have reached" in text
                   or "reached an answering machine" in body.lower()
                      and marker not in body)
        revoked = any(p in text for p in ("take me off", "stop calling",
                                          "do not call", "remove me",
                                          "don't call"))
        if machine:
            data = {
                "summary": "Reached voicemail. Left the standard message with a callback number.",
                "disposition": "voicemail_left", "score": None,
                "score_reasons": [], "objections": [],
                "qualification": {}, "revocation_detected": False,
                "follow_up": {"title": "Try again — reached voicemail",
                              "kind": "Call", "in_days": 1},
            }
        elif revoked:
            data = {
                "summary": "Contact asked to be removed from the list. Suppressed.",
                "disposition": "dnc", "score": 6,
                "score_reasons": ["Handled the request politely", "Closed quickly"],
                "objections": ["not interested"], "qualification": {},
                "revocation_detected": True, "follow_up": None,
            }
        else:
            data = {
                "summary": ("Spoke with the manager. They buy napkins weekly from a "
                            "restaurant supplier, ~40 tables. Open to free branded "
                            "napkins; wants to see a sample pack first."),
                "disposition": "qualified", "score": 8,
                "score_reasons": ["Reached the decision maker quickly",
                                  "Asked all four qualifying questions",
                                  "Booked a concrete next step"],
                "objections": ["already have a supplier"],
                "qualification": {"decision_maker": "manager",
                                  "napkin_volume": "1-2 cases/week",
                                  "tables": "40 plus bar", "service_style": "table service"},
                "revocation_detected": False,
                "follow_up": {"title": "Send sample pack and follow up",
                              "kind": "Follow-up", "in_days": 2},
            }
        return ok(data=data, text=json.dumps(data))


class FakeTranscriber(Transcriber):
    def __init__(self, settings=None, fail=None):
        self.settings = settings
        self.fail = fail or ""

    def verify(self):
        return ok(model="simulated-transcribe")

    def transcribe(self, audio_bytes, mimetype="audio/mpeg", dual_channel=False):
        if self.fail == "stt":
            return err("Simulated transcription failure", "sim_fail")
        segments = [
            {"speaker": "rep", "text": "Hi, this is Corban with NapkinAds — is the "
                                       "owner or manager around?", "start": 0.0},
            {"speaker": "prospect", "text": "Speaking. What's this about?", "start": 4.2},
            {"speaker": "rep", "text": "We give bars and restaurants free napkins. "
                                       "They carry a small ad so they cost you nothing.",
             "start": 6.0},
            {"speaker": "prospect", "text": "We already buy ours from a supplier, but "
                                            "free is free. Send me something.", "start": 12.5},
        ]
        text = "\n".join(f"{s['speaker']}: {s['text']}" for s in segments)
        return ok(text=text, segments=segments)


# --------------------------------------------------------------- the simulator
class _Simulator:
    """Holds in-flight fake calls and advances them through the real webhook
    sequence, so routes_hooks and the finalize pipeline are exercised for real."""

    def __init__(self):
        self.calls = {}

    def schedule(self, sid, to, **kw):
        outcome = outcome_for(to)
        kw.setdefault("record", False)
        self.calls[sid] = {
            "sid": sid, "to": to, "outcome": outcome, "status": "queued",
            "created": time.time(), "duration": 0,
            "answered_by": {"answered_machine": "machine_end_beep",
                            "answered_human": "human"}.get(outcome, ""),
            "price": 0.0, "steps": [], **kw}
        return self.calls[sid]

    def state(self, sid):
        return self.calls.get(sid, {})

    def by_conversation(self, conversation_id):
        for c in self.calls.values():
            if c.get("conversation_id") == conversation_id:
                return c
        return {}

    def mark(self, sid, status):
        if sid in self.calls:
            self.calls[sid]["status"] = status

    def sequence(self, sid):
        """The webhook payloads a real carrier would send, in order."""
        c = self.calls.get(sid)
        if not c:
            return []
        outcome = c["outcome"]
        base = {"CallSid": sid, "To": c["to"], "From": c.get("from", "+18655550101"),
                "AccountSid": "ACsimulated"}
        seq = [dict(base, CallStatus="initiated"), dict(base, CallStatus="ringing")]
        if outcome in ("answered_human", "answered_machine", "wrong_number"):
            seq.append(dict(base, CallStatus="in-progress",
                            AnsweredBy=c["answered_by"]))
            dur = {"answered_human": 96, "answered_machine": 24,
                   "wrong_number": 11}[outcome]
            c["duration"] = dur
            c["price"] = round(0.014 * max(1, (dur + 59) // 60), 4)
            done = dict(base, CallStatus="completed", CallDuration=str(dur),
                        AnsweredBy=c["answered_by"])
            if c.get("record"):
                done["RecordingSid"] = _sid("RE", sid)
                done["RecordingUrl"] = f"https://sim.local/Recordings/{_sid('RE', sid)}"
                done["RecordingDuration"] = str(dur)
            seq.append(done)
        elif outcome == "busy":
            seq.append(dict(base, CallStatus="busy"))
        else:
            seq.append(dict(base, CallStatus="no-answer"))
        c["status"] = seq[-1]["CallStatus"]
        return seq

    def reset(self):
        self.calls.clear()


_SIM = _Simulator()


def simulator():
    return _SIM


def _sim_playbook(brief):
    """A believable draft for practice mode, shaped exactly like the real one.

    Deliberately generic: in simulation nothing should look like it knows the
    customer's business, or someone will think the AI read their website.
    """
    first = " ".join((brief or "").split())[:80] or "what you sell"
    return {
        "name": "Draft: cold call",
        "description": f"Practice-mode draft about {first}.",
        "steps": [
            {"title": "Open", "goal": "Say who is calling",
             "say": "Hi, this is a quick call from our team. Have I caught "
                    "you at an alright moment?"},
            {"title": "The offer", "goal": "One sentence, no more",
             "say": f"We help with {first}, and I wanted to see if it is "
                    f"worth a longer conversation."},
            {"title": "Qualify", "goal": "Cheapest disqualifier first",
             "say": "Would that be your call, or is there someone else I "
                    "should be speaking to?"},
            {"title": "Close", "goal": "Book it or leave politely",
             "say": "That is all I needed. Thanks for your time."},
        ],
        "questions": [
            {"question": "Are you the person who would decide on this?",
             "collect_as": "is_decision_maker",
             "disqualify_if": "they have no involvement at all"},
            {"question": "Who else would need to be in that conversation?",
             "collect_as": "other_stakeholders", "disqualify_if": ""},
        ],
        "objections": [
            {"trigger_phrases": ["not interested", "no thanks"],
             "response": "Understood, I will not keep you. Can I ask what "
                         "you have in place at the moment?"},
            {"trigger_phrases": ["send me an email", "email me"],
             "response": "Happy to. So it is not just another email in the "
                         "pile, what is the one thing worth putting in it?"},
            {"trigger_phrases": ["how much", "what does it cost", "price"],
             "response": "It depends on size, and I would rather not guess "
                         "at you. That is exactly what the next conversation "
                         "is for."},
        ],
        "transfer_criteria": "Transfer as soon as they confirm they are the "
                             "decision maker, or ask anything about price or "
                             "timing. Stop selling at that point.",
        "never_do": "Never claim to be a person. Never promise a price on "
                    "this call. Never say the word solution.",
    }
