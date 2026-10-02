"""Live ElevenLabs Agents provider.

Plain `requests` on purpose -- the official SDK pins its own httpx and would
drag a second HTTP stack into a two-worker gunicorn deployment for no gain.

Every method returns a dict and never raises: these run inside request
handlers, and a vendor outage must render a readable card, not a 500.
"""
import hashlib
import hmac
import time

import requests

from dialer.providers.base import VoiceAgent, err, ok

API_BASE = "https://api.elevenlabs.io"
TIMEOUT = 25          # control plane
AUDIO_TIMEOUT = 60    # a 10-minute MP3 over a slow link
SIGNATURE_MAX_AGE = 30 * 60  # seconds; replay window for post-call webhooks

# ElevenLabs' own background-sound preset ids. There is no upload: the field
# accepts a preset and nothing else, so "where do I put my office noise file"
# has the answer "you don't, pick one of these".
BACKGROUND_PRESETS = ("office1", "office2", "restaurant", "city", "typing",
                      "elevator1", "elevator2", "elevator3", "elevator4")

NO_KEY = "Add your ElevenLabs key in Setup first."

# Concurrency is NOT returned anywhere in the API -- it is a property of the
# billing plan only, published at https://elevenlabs.io/pricing . Re-verify
# quarterly; ElevenLabs has changed these numbers before without notice.
TIER_CONCURRENCY = {
    "free": 4,
    "starter": 6,
    "creator": 10,
    "pro": 20,
    "scale": 30,
    "business": 40,
}
DEFAULT_CONCURRENCY = 4


def _status_code(status):
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit"
    return "api_error"


def _api_message(resp):
    """Dig ElevenLabs' own wording out of an error body so the UI can show it.

    They are inconsistent: FastAPI validation errors come back as
    {"detail": [{"msg": ...}]}, business errors as
    {"detail": {"status": ..., "message": ...}}, some as a bare string.
    """
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("detail", body.get("message", body.get("error")))
        if isinstance(detail, dict):
            msg = detail.get("message") or detail.get("msg") or detail.get("status")
            if msg:
                return str(msg)
        elif isinstance(detail, list) and detail:
            # A validation error names the offending field in `loc` and puts
            # only "Field required" in `msg`. Reporting the msg alone is how
            # a wrong request body of ours got read as a permissions problem
            # on the customer's side, so the field comes too.
            parts = []
            for item in detail[:3]:
                if isinstance(item, dict):
                    msg = item.get("msg") or item.get("message") or ""
                    loc = [str(x) for x in (item.get("loc") or [])
                           if str(x) not in ("body", "query", "path")]
                    where = ".".join(loc)
                    parts.append(f"{msg} ({where})" if where and msg
                                 else (msg or where))
                elif item:
                    parts.append(str(item))
            parts = [p for p in parts if p]
            if parts:
                return "; ".join(parts)
        elif isinstance(detail, str) and detail.strip():
            return detail
    text = (getattr(resp, "text", "") or "").strip()
    if text:
        return f"ElevenLabs returned {resp.status_code}: {text[:200]}"
    return f"ElevenLabs returned {resp.status_code}."


def _first(d, *keys, default=""):
    """Tolerate camelCase / snake_case drift in ElevenLabs responses."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _merge(base, extra):
    """Recursive dict merge that does not clobber sibling keys."""
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


class ElevenLabsAgent(VoiceAgent):
    # Identifies this implementation in logs and error cards; the
    # registry keys the slot itself, so this is free to name the vendor.
    name = "elevenlabs"

    def __init__(self, settings=None):
        self.settings = settings

    # ------------------------------------------------------------- plumbing
    def _key(self):
        try:
            return self.settings.secret("elevenlabs_key") or ""
        except Exception:
            return ""

    def _req(self, method, path, **kw):
        """-> {ok: True, data: <parsed json | bytes>} or an err() dict.

        Pass raw=True for binary endpoints. Any transport exception or
        non-2xx status becomes err(), carrying the API's own message when
        one is present.
        """
        key = self._key()
        if not key:
            return err(NO_KEY, "no_credentials")
        raw = bool(kw.pop("raw", False))
        headers = {"xi-api-key": key}
        headers.update(kw.pop("headers", None) or {})
        kw.setdefault("timeout", TIMEOUT)
        try:
            resp = requests.request(method, API_BASE + path, headers=headers, **kw)
        except requests.Timeout:
            return err("ElevenLabs did not respond in time.", "timeout")
        except Exception as e:  # connection reset, DNS, bad TLS, anything
            return err(f"Could not reach ElevenLabs: {e}", "network")
        if not (200 <= resp.status_code < 300):
            return err(_api_message(resp), _status_code(resp.status_code))
        if raw:
            return ok(data=resp.content,
                      mimetype=resp.headers.get("Content-Type", ""))
        try:
            return ok(data=resp.json())
        except ValueError:
            return ok(data={}, text=resp.text)

    # ----------------------------------------------------------- account
    def verify(self):
        r = self._req("GET", "/v1/user")
        if not r["ok"]:
            return r
        data = r["data"] or {}
        sub = data.get("subscription") or {}
        tier = str(sub.get("tier") or "").strip().lower()
        concurrency = TIER_CONCURRENCY.get(tier, DEFAULT_CONCURRENCY)
        voices = self.list_voices()
        return ok(tier=tier, concurrency=concurrency,
                  voices=voices.get("voices", []) if voices.get("ok") else [])

    def list_voices(self, limit=40):
        r = self._req("GET", "/v1/voices")
        if not r["ok"]:
            return r
        out = []
        for v in (r["data"] or {}).get("voices", []) or []:
            labels = v.get("labels") or {}
            if isinstance(labels, dict):
                label_str = ", ".join(str(x) for x in labels.values() if x)
            else:
                label_str = str(labels or "")
            # preview_url is a plain public mp3, so the browser can play it
            # with no key and nothing proxied through us. category is how a
            # stock voice is told apart from one the customer cloned, which
            # is the only thing distinguishing forty near-identical rows.
            out.append({"voice_id": v.get("voice_id", ""),
                        "name": v.get("name", ""),
                        "labels": label_str[:120],
                        "preview_url": v.get("preview_url") or "",
                        "category": str(v.get("category") or "").strip(),
                        "hq_models": [str(m) for m in
                                      (v.get("high_quality_base_model_ids")
                                       or [])]})
            if len(out) >= limit:
                break
        return ok(voices=out)

    def speak(self, text, voice_id, model_id="eleven_turbo_v2_5"):
        """Text to speech -> mp3 bytes.

        Used to turn the sample voicemail wording into something you can
        actually listen to, in the voice the AI will use, rather than asking
        someone to imagine it.
        """
        text = (text or "").strip()
        if not text:
            return err("Nothing to say.", "bad_request")
        if not voice_id:
            return err("Pick a voice on step 8 first.", "bad_request")
        r = self._req("POST", f"/v1/text-to-speech/{voice_id}", raw=True,
                      headers={"Accept": "audio/mpeg",
                               "Content-Type": "application/json"},
                      json={"text": text[:2500], "model_id": model_id})
        if not r["ok"]:
            return r
        audio = r.get("data") or b""
        if not audio:
            return err("ElevenLabs returned no audio.", "api_error")
        return ok(audio=audio, mimetype=r.get("mimetype") or "audio/mpeg")

    # ----------------------------------------------------------- webhooks
    def ensure_webhook(self, url, name):
        """Create a workspace webhook and hand back its signing secret.

        CRITICAL: `webhook_secret` is returned by this call and by NO other
        call. The list endpoint never returns it again, and there is no
        "reveal" endpoint. The caller MUST persist it in the same database
        transaction that stores `webhook_id` -- if the commit is lost, the
        only recovery is to delete the webhook and create a new one.

        Also note `webhook_url` is IMMUTABLE: PATCH silently refuses to move
        it. Changing the URL (new domain, new path) means delete + recreate,
        which mints a brand-new secret, so the stored secret must be replaced
        at the same time or every inbound post-call webhook fails signature
        verification.
        """
        # The three fields go INSIDE a `settings` object. Sent flat, the API
        # replies 422 "Field required" naming `settings`, and before the
        # error carried that name it read like a vague permissions failure.
        r = self._req("POST", "/v1/workspace/webhooks",
                      json={"settings": {"name": name, "webhook_url": url,
                                         "auth_type": "hmac"}})
        if not r["ok"]:
            return r
        data = r["data"] or {}
        # Documented flat, but the request wraps in `settings`, so accept
        # either rather than failing on a shape that is clearly intended.
        inner = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        secret = _first(data, "webhook_secret", "secret") or \
            _first(inner, "webhook_secret", "secret")
        webhook_id = _first(data, "webhook_id", "id") or \
            _first(inner, "webhook_id", "id")
        if not webhook_id:
            return err("ElevenLabs created the webhook but returned no id.",
                       "api_error")
        return ok(webhook_id=webhook_id, secret=secret)

    # -------------------------------------------------------------- agents
    def upsert_agent(self, agent, prompt, tools, webhook_id=None,
                     transfer=None):
        """Create (POST) or update (PATCH) the ElevenLabs-side agent."""
        conversation_config = {
            "agent": {
                "prompt": {
                    "prompt": prompt,
                    "llm": getattr(agent, "llm_model", "") or "",
                    "tools": tools or [],
                    # transfer_to_number is a SYSTEM tool and lives in
                    # built_in_tools, not in the webhook tools list. Putting
                    # it in the wrong place is the same as not sending it.
                    **({"built_in_tools": {"transfer_to_number": transfer}}
                       if transfer else {}),
                },
                "first_message": getattr(agent, "first_message", "") or "",
                "language": getattr(agent, "language", "") or "en",
            },
            "tts": {"voice_id": getattr(agent, "voice_id", "") or ""},
            "turn": {"turn_timeout": 10},
        }
        platform_settings = {
            "call_limits": {
                "agent_concurrency_limit": -1,
                # Deliberate. The API default is bursting_enabled: True, and
                # bursting silently lets calls spill past the plan ceiling at
                # DOUBLE the per-minute rate ($0.16/min instead of $0.08) with
                # degraded STT/TTS priority. We would rather queue than hand a
                # customer a surprise invoice, so we pin it off on every sync.
                "bursting_enabled": False,
            },
        }
        if webhook_id:
            # `events` is named explicitly rather than left to default.
            # ElevenLabs requires at least one and the transcript is the
            # whole reason this webhook exists, so an inherited default
            # quietly going the other way would mean silent calls again.
            platform_settings["workspace_overrides"] = {
                "webhooks": {"post_call_webhook_id": webhook_id,
                             "events": ["transcript"]}
            }

        body = {
            "name": getattr(agent, "name", "") or "",
            "conversation_config": conversation_config,
            "platform_settings": platform_settings,
        }

        preset = getattr(agent, "background_preset", "") or ""
        if preset in BACKGROUND_PRESETS:
            # The field is conversation.background_sound, carrying
            # source_type and source_id. This used to go as
            # conversation_config.background_audio with a "preset" key.
            # ElevenLabs accepts unknown keys on an agent config rather than
            # rejecting them, so every sync reported success and no ambience
            # was ever mixed in. Merged, never assigned, because
            # conversation_config already carries agent/tts/turn.
            _merge(body, {"conversation_config": {
                "agent": {}, "tts": {},
                "conversation": {"background_sound": {
                    "source_type": "preset", "source_id": preset,
                    "volume": 0.3, "crossfade_loop": True}}}})

        existing = (getattr(agent, "elevenlabs_agent_id", "") or "").strip()
        if existing:
            r = self._req("PATCH", f"/v1/convai/agents/{existing}", json=body)
        else:
            r = self._req("POST", "/v1/convai/agents/create", json=body)
        if not r["ok"]:
            return r
        agent_id = _first(r["data"], "agent_id", "agentId", "id",
                          default=existing)
        if not agent_id:
            return err("ElevenLabs saved the agent but returned no agent id.",
                       "api_error")
        return ok(agent_id=agent_id)

    # ------------------------------------------------------------- numbers
    def get_agent(self, agent_id):
        """Read an agent back from ElevenLabs.

        Worth having permanently. Several settings today looked correct in
        our database and were wrong at the vendor, because ElevenLabs drops
        unknown keys silently instead of rejecting them. The only way to
        know what it holds is to ask it.
        """
        if not agent_id:
            return err("No agent id.", "bad_request")
        r = self._req("GET", f"/v1/convai/agents/{agent_id}")
        if not r["ok"]:
            return r
        data = r.get("data") or {}
        conv = (data.get("conversation_config") or {})
        agent_cfg = conv.get("agent") or {}
        prompt_cfg = agent_cfg.get("prompt") or {}
        sound = ((conv.get("conversation") or {}).get("background_sound")
                 or {})
        # The transfer tool is hunted for rather than read from one path.
        # We send it exactly as ElevenLabs documents and it is not coming
        # back where the create shape says it should, so the read model and
        # the write model evidently differ. Looking in several places and
        # reporting WHERE it was found is the only way to settle that
        # without another round of guessing.
        found_at = ""
        for label, holder in (("prompt.built_in_tools",
                               prompt_cfg.get("built_in_tools")),
                              ("agent.built_in_tools",
                               agent_cfg.get("built_in_tools")),
                              ("conversation_config.built_in_tools",
                               conv.get("built_in_tools")),
                              ("platform_settings.built_in_tools",
                               (data.get("platform_settings") or {})
                               .get("built_in_tools"))):
            if isinstance(holder, dict) and holder.get("transfer_to_number"):
                found_at = label
                break
        if not found_at:
            for t in (prompt_cfg.get("tools") or []):
                if isinstance(t, dict) and t.get("name") == "transfer_to_number":
                    found_at = "prompt.tools"
                    break
        return ok(
            name=data.get("name", ""),
            first_message=agent_cfg.get("first_message", ""),
            voice_id=((conv.get("tts") or {}).get("voice_id") or ""),
            llm=prompt_cfg.get("llm", ""),
            background=sound,
            has_transfer=bool(found_at),
            transfer_at=found_at,
            prompt_keys=sorted(prompt_cfg.keys()),
            agent_keys=sorted(agent_cfg.keys()),
            tool_count=len(prompt_cfg.get("tools") or []),
            prompt_chars=len(prompt_cfg.get("prompt") or ""))

    def import_number(self, e164, twilio_sid, twilio_token, agent_id=None,
                      label="", account_auth_token=None):
        """Attach one of the customer's Twilio numbers to their workspace.

        `twilio_sid` accepts EITHER an Account SID (AC...) with the account
        auth token, OR an API Key SID (SK...) with its own secret as `token`.
        The API Key pair is the one to prefer -- it is revocable per
        integration.

        `account_auth_token` is additionally required for any number that
        must RECEIVE calls: Twilio signs inbound webhooks with the ACCOUNT
        auth token, never with an API key secret, so ElevenLabs cannot
        validate inbound requests without it. Outbound-only numbers do not
        need it.
        """
        body = {"provider": "twilio", "phone_number": e164,
                "label": label or e164, "sid": twilio_sid, "token": twilio_token}
        if agent_id:
            body["agent_id"] = agent_id
        if account_auth_token:
            body["account_auth_token"] = account_auth_token
        r = self._req("POST", "/v1/convai/phone-numbers", json=body)
        if not r["ok"]:
            return r
        pid = _first(r["data"], "phone_number_id", "phoneNumberId", "id")
        if not pid:
            return err("ElevenLabs imported the number but returned no id.",
                       "api_error")
        return ok(phone_number_id=pid)

    # --------------------------------------------------------------- calls
    def outbound_call(self, agent_id, phone_number_id, to, variables=None):
        body = {
            "agent_id": agent_id,
            "agent_phone_number_id": phone_number_id,
            "to_number": to,
            "conversation_initiation_client_data": {
                "dynamic_variables": variables or {}
            },
        }
        r = self._req("POST", "/v1/convai/twilio/outbound-call", json=body)
        if not r["ok"]:
            return r
        data = r["data"] or {}
        if data.get("success") is False:
            return err(data.get("message") or "ElevenLabs refused the call.",
                       "api_error")
        return ok(conversation_id=_first(data, "conversation_id",
                                         "conversationId"),
                  call_sid=_first(data, "callSid", "call_sid"))

    def conversation(self, conversation_id):
        r = self._req("GET", f"/v1/convai/conversations/{conversation_id}")
        if not r["ok"]:
            return r
        data = r["data"] or {}
        lines = []
        for turn in data.get("transcript") or []:
            if not isinstance(turn, dict):
                continue
            message = (turn.get("message") or "").strip()
            if not message:
                continue  # tool calls and interruptions carry no text
            lines.append(f"{turn.get('role') or 'agent'}: {message}")
        meta = data.get("metadata") or {}
        return ok(transcript="\n".join(lines),
                  analysis=data.get("analysis") or {},
                  duration=meta.get("call_duration_secs") or 0,
                  cost=meta.get("cost") or 0)

    def conversation_audio(self, conversation_id):
        """Pull the recording on demand.

        We do this lazily instead of enabling the `post_call_audio` webhook
        on purpose: that webhook streams a base64-encoded MP3 with
        `transfer-encoding: chunked`, which would occupy one of our two
        gunicorn sync workers for the length of the transfer. Here the fetch
        only happens when a rep actually clicks play.
        """
        r = self._req("GET", f"/v1/convai/conversations/{conversation_id}/audio",
                      raw=True, timeout=AUDIO_TIMEOUT)
        if not r["ok"]:
            return r
        return ok(content=r["data"], mimetype="audio/mpeg")

    def register_call(self, agent_id, from_number, to_number, direction,
                      variables=None):
        """Get TwiML that hands an already-live Twilio call to the agent.

        This path keeps the Twilio voice webhook pointed at our own Flask
        app, which is what lets us run after-hours routing and human-first
        routing before the AI ever picks up. The cost is call transfer:
        numbers driven this way are not natively imported, so the agent's
        `transfer_to_number` tool is unavailable and any hand-off has to be
        done by us on the Twilio side.
        """
        body = {"agent_id": agent_id, "from_number": from_number,
                "to_number": to_number, "direction": direction,
                "conversation_initiation_client_data": {
                    "dynamic_variables": variables or {}}}
        r = self._req("POST", "/v1/convai/twilio/register-call", json=body)
        if not r["ok"]:
            return r
        data = r["data"] or {}
        twiml = _first(data, "twiml", "twilio_response", "response")
        if not twiml:
            return err("ElevenLabs returned no TwiML for this call.",
                       "api_error")
        return ok(twiml=twiml)

    # ----------------------------------------------------------- webhooks in
    def verify_signature(self, body, header, secret):
        """Validate `elevenlabs-signature: t=<unix>,v0=<hex>`.

        The signed payload is "<timestamp>.<raw request body>" -- the RAW
        body, so the caller must pass request.get_data(), never a re-encoded
        dict. Stale timestamps are rejected to blunt replay. Returns a plain
        bool and never raises; a malformed header is simply False.
        """
        try:
            if not header or not secret:
                return False
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
            if isinstance(secret, bytes):
                secret = secret.decode("utf-8", "replace")
            ts, sig = "", ""
            for part in str(header).split(","):
                part = part.strip()
                if part.startswith("t="):
                    ts = part[2:]
                elif part.startswith("v0="):
                    sig = part[3:]
            if not ts or not sig:
                return False
            if abs(time.time() - int(ts)) > SIGNATURE_MAX_AGE:
                return False
            expected = hmac.new(secret.encode("utf-8"),
                                f"{ts}.{body}".encode("utf-8"),
                                hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, sig.strip().lower())
        except Exception:
            return False
