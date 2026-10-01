"""Live LLM and transcription providers.

One class covers both LLM vendors because the call sites only ever want
"turn this transcript into a dict" -- the provider split is a settings
column, not a different product.

Plain `requests`, no vendor SDKs: two HTTP clients in a two-worker gunicorn
process is cost without benefit. Every method returns a dict and never
raises.
"""
import json

import requests

from dialer.providers.base import LLM, Transcriber, err, ok

OPENAI_BASE = "https://api.openai.com"
ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

TIMEOUT = 25            # control plane and completions
STT_TIMEOUT = 120       # a 10-minute call is a real upload

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"

JSON_NUDGE = ("\n\nReply with a single JSON object and nothing else. No "
              "prose, no explanation, no markdown code fences.")


def _api_message(resp, vendor):
    """Surface the vendor's own wording; both nest it under "error"."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        e = body.get("error")
        if isinstance(e, dict) and e.get("message"):
            return str(e["message"])
        if isinstance(e, str) and e.strip():
            return e
        if body.get("message"):
            return str(body["message"])
    text = (getattr(resp, "text", "") or "").strip()
    if text:
        return f"{vendor} returned {resp.status_code}: {text[:200]}"
    return f"{vendor} returned {resp.status_code}."


def _status_code(status):
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    return "api_error"


def _loads(raw):
    """Forgiving JSON parse: models wrap objects in fences and chatter."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if text.count("```") >= 2 else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


class _Base:
    def __init__(self, settings=None):
        self.settings = settings

    def _provider(self):
        return (getattr(self.settings, "llm_provider", "") or "openai").strip().lower()

    def _key(self):
        try:
            return self.settings.secret("llm_key") or ""
        except Exception:
            return ""

    def _no_key(self):
        vendor = "Anthropic" if self._provider() == "anthropic" else "OpenAI"
        return err(f"Add your {vendor} key in Setup first.", "no_credentials")

    def _post(self, url, vendor, headers, timeout=TIMEOUT, **kw):
        """-> {ok: True, data: <parsed json>} or an err() dict."""
        try:
            resp = requests.post(url, headers=headers, timeout=timeout, **kw)
        except requests.Timeout:
            return err(f"{vendor} did not respond in time.", "timeout")
        except Exception as e:
            return err(f"Could not reach {vendor}: {e}", "network")
        if not (200 <= resp.status_code < 300):
            return err(_api_message(resp, vendor), _status_code(resp.status_code))
        try:
            return ok(data=resp.json())
        except ValueError:
            return err(f"{vendor} returned a response we couldn't read.",
                       "api_error")

    def _get(self, url, vendor, headers, timeout=TIMEOUT):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.Timeout:
            return err(f"{vendor} did not respond in time.", "timeout")
        except Exception as e:
            return err(f"Could not reach {vendor}: {e}", "network")
        if not (200 <= resp.status_code < 300):
            return err(_api_message(resp, vendor), _status_code(resp.status_code))
        return ok(data={})


class LiveLLM(LLM, _Base):
    """Post-call summary / scoring / extraction against OpenAI or Anthropic."""

    # Which vendor is live is a settings column, so the label names the
    # implementation rather than the vendor.
    name = "llm_live"

    def __init__(self, settings=None):
        self.settings = settings

    def _model(self):
        configured = (getattr(self.settings, "llm_model", "") or "").strip()
        if configured:
            return configured
        return (DEFAULT_ANTHROPIC_MODEL if self._provider() == "anthropic"
                else DEFAULT_OPENAI_MODEL)

    def verify(self):
        key = self._key()
        if not key:
            return self._no_key()
        if self._provider() == "anthropic":
            r = self._get(f"{ANTHROPIC_BASE}/v1/models", "Anthropic",
                          {"x-api-key": key,
                           "anthropic-version": ANTHROPIC_VERSION})
        else:
            r = self._get(f"{OPENAI_BASE}/v1/models", "OpenAI",
                          {"Authorization": f"Bearer {key}"})
        if not r["ok"]:
            return r
        return ok(model=self._model())

    def complete(self, system, user, max_tokens=800, json_mode=False):
        key = self._key()
        if not key:
            return self._no_key()
        if self._provider() == "anthropic":
            r = self._anthropic(key, system, user, max_tokens, json_mode)
        else:
            r = self._openai(key, system, user, max_tokens, json_mode)
        if not r["ok"]:
            return r
        text = r["text"]
        if not json_mode:
            return ok(text=text)
        data = _loads(text)
        if data is None:
            bad = err("The AI returned something we couldn't read.", "bad_json")
            bad["text"] = text
            return bad
        return ok(data=data, text=text)

    # ------------------------------------------------------------- vendors
    def _openai(self, key, system, user, max_tokens, json_mode):
        body = {
            "model": self._model(),
            "messages": [{"role": "system", "content": system or ""},
                         {"role": "user", "content": user or ""}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self._post(f"{OPENAI_BASE}/v1/chat/completions", "OpenAI",
                       {"Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"}, json=body)
        if not r["ok"]:
            return r
        choices = (r["data"] or {}).get("choices") or []
        if not choices:
            return err("OpenAI returned no completion.", "api_error")
        text = ((choices[0] or {}).get("message") or {}).get("content") or ""
        return ok(text=text)

    def _anthropic(self, key, system, user, max_tokens, json_mode):
        # Anthropic has no response_format switch, so JSON mode is an
        # instruction appended to the system prompt. _loads() still strips
        # fences, because the instruction is honored but not guaranteed.
        system_text = (system or "") + (JSON_NUDGE if json_mode else "")
        body = {
            "model": self._model(),
            "max_tokens": max_tokens,
            "system": system_text,
            "messages": [{"role": "user", "content": user or ""}],
        }
        r = self._post(f"{ANTHROPIC_BASE}/v1/messages", "Anthropic",
                       {"x-api-key": key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "Content-Type": "application/json"}, json=body)
        if not r["ok"]:
            return r
        blocks = (r["data"] or {}).get("content") or []
        text = "".join(b.get("text", "") for b in blocks
                       if isinstance(b, dict) and b.get("type") == "text")
        if not text:
            return err("Anthropic returned no completion.", "api_error")
        return ok(text=text)


class LiveTranscriber(Transcriber, _Base):
    """Whisper-family transcription. OpenAI only -- see verify()."""

    name = "transcriber_live"

    def __init__(self, settings=None):
        self.settings = settings

    def _model(self):
        return (getattr(self.settings, "stt_model", "") or "").strip() \
            or DEFAULT_STT_MODEL

    def verify(self):
        # A real product constraint, not an oversight: Anthropic ships no
        # speech-to-text API at all. An account on the Anthropic provider
        # gets summaries and scoring but cannot transcribe its own call
        # recordings until an OpenAI key is added alongside it.
        if self._provider() == "anthropic":
            return err("Anthropic has no transcription API — add an OpenAI "
                       "key for call transcripts.", "no_stt")
        key = self._key()
        if not key:
            return self._no_key()
        r = self._get(f"{OPENAI_BASE}/v1/models", "OpenAI",
                      {"Authorization": f"Bearer {key}"})
        if not r["ok"]:
            return r
        return ok(model=self._model())

    def transcribe(self, audio_bytes, mimetype="audio/mpeg", dual_channel=False):
        if self._provider() == "anthropic":
            return err("Anthropic has no transcription API — add an OpenAI "
                       "key for call transcripts.", "no_stt")
        key = self._key()
        if not key:
            return self._no_key()
        if not audio_bytes:
            return err("There is no audio to transcribe.", "no_audio")
        files = {"file": ("call.mp3", audio_bytes, mimetype or "audio/mpeg")}
        data = {"model": self._model(), "response_format": "json"}
        r = self._post(f"{OPENAI_BASE}/v1/audio/transcriptions", "OpenAI",
                       {"Authorization": f"Bearer {key}"},
                       timeout=STT_TIMEOUT, files=files, data=data)
        if not r["ok"]:
            return r
        payload = r["data"] or {}
        text = payload.get("text") or ""
        segments = []
        for s in payload.get("segments") or []:
            if not isinstance(s, dict):
                continue
            # Only a dual-channel upload carries channel info; on a mixed
            # mono recording we leave speaker blank rather than guess.
            channel = s.get("channel", s.get("speaker"))
            if dual_channel and channel in (0, 1, "0", "1"):
                speaker = "rep" if str(channel) == "0" else "prospect"
            elif isinstance(channel, str) and channel in ("rep", "prospect"):
                speaker = channel
            else:
                speaker = ""
            segments.append({"speaker": speaker,
                             "text": (s.get("text") or "").strip(),
                             "start": s.get("start") or 0.0})
        return ok(text=text, segments=segments)
