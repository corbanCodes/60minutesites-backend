"""Vendor interfaces. Everything the dialer does to the outside world goes
through one of these four, so simulation mode is a swap, not a flag sprinkled
through the code.

Every method returns a plain dict with at least {"ok": bool}. Errors are
returned, never raised, because these are called from request handlers and a
vendor outage must render a readable card rather than a 500.
"""


class ProviderError(Exception):
    pass


def err(message, code=""):
    return {"ok": False, "error": str(message)[:400], "code": code}


def ok(**kw):
    d = {"ok": True}
    d.update(kw)
    return d


class Telephony:
    """Twilio, or the fake."""
    name = "telephony"

    def verify(self):
        """-> {ok, account_name, balance, is_trial, numbers:[...]}"""
        raise NotImplementedError

    def list_numbers(self):
        """-> {ok, numbers: [{e164, sid, friendly_name, region}]}"""
        raise NotImplementedError

    def search_numbers(self, area_code=None, contains=None, limit=10):
        raise NotImplementedError

    def buy_number(self, e164, voice_url, status_callback):
        raise NotImplementedError

    def release_number(self, sid):
        raise NotImplementedError

    def configure_number(self, sid, voice_url, status_callback):
        raise NotImplementedError

    def ensure_twiml_app(self, voice_url, friendly_name):
        """-> {ok, sid}"""
        raise NotImplementedError

    def ensure_api_key(self, friendly_name):
        """-> {ok, sid, secret} (secret is returned once, by Twilio too)"""
        raise NotImplementedError

    def access_token(self, identity, twiml_app_sid, ttl=3600):
        """JWT for the browser softphone. -> {ok, token, identity, expires_in}"""
        raise NotImplementedError

    # --- calls
    def dial_participant(self, conference, to, from_, **kw):
        """Add a prospect leg to a rep's conference. -> {ok, sid}"""
        raise NotImplementedError

    def create_call(self, to, from_, url, status_callback, **kw):
        """Plain outbound leg (click-to-call, voicemail blast). -> {ok, sid}"""
        raise NotImplementedError

    def redirect_call(self, sid, twiml):
        """Used for the one-click voicemail drop. -> {ok}"""
        raise NotImplementedError

    def hangup(self, sid):
        raise NotImplementedError

    def update_participant(self, conference, call_sid, **kw):
        """muted / hold / coaching / callSidToCoach. -> {ok}"""
        raise NotImplementedError

    def fetch_call(self, sid):
        """-> {ok, status, duration, price, answered_by}"""
        raise NotImplementedError

    def fetch_recording(self, sid):
        raise NotImplementedError

    def delete_recording(self, sid):
        raise NotImplementedError

    def lookup(self, e164):
        """Line Type Intelligence. -> {ok, line_type, carrier, raw}"""
        raise NotImplementedError

    def validate_signature(self, signature, url, params):
        raise NotImplementedError

    # --- trust hub
    def customer_profiles(self):
        """-> {ok, status: none|individual|business|pending}"""
        raise NotImplementedError


class VoiceAgent:
    """ElevenLabs Agents, or the fake."""
    name = "voice_agent"

    def verify(self):
        """-> {ok, tier, concurrency, voices:[...]}"""
        raise NotImplementedError

    def list_voices(self, limit=40):
        raise NotImplementedError

    def ensure_webhook(self, url, name):
        """-> {ok, webhook_id, secret}  (secret readable exactly once)"""
        raise NotImplementedError

    def upsert_agent(self, agent, prompt, tools, webhook_id=None,
                     transfer=None, first_message=None):
        """-> {ok, agent_id}"""
        raise NotImplementedError

    def import_number(self, e164, twilio_sid, twilio_token, agent_id=None,
                      label="", account_auth_token=None):
        """-> {ok, phone_number_id}"""
        raise NotImplementedError

    def outbound_call(self, agent_id, phone_number_id, to, variables=None):
        """-> {ok, conversation_id, call_sid}"""
        raise NotImplementedError

    def conversation(self, conversation_id):
        """-> {ok, transcript, analysis, duration, cost}"""
        raise NotImplementedError

    def conversation_audio(self, conversation_id):
        """-> {ok, content, mimetype}"""
        raise NotImplementedError

    def register_call(self, agent_id, from_number, to_number, direction,
                      variables=None):
        """We keep the Twilio webhook; ElevenLabs hands back TwiML. -> {ok, twiml}"""
        raise NotImplementedError

    def verify_signature(self, body, header, secret):
        raise NotImplementedError


class LLM:
    """Post-call summary / scoring / extraction, and live coaching ticks."""
    name = "llm"

    def verify(self):
        raise NotImplementedError

    def complete(self, system, user, max_tokens=800, json_mode=False):
        """-> {ok, text} or {ok, data} when json_mode"""
        raise NotImplementedError


class Transcriber:
    name = "transcriber"

    def verify(self):
        raise NotImplementedError

    def transcribe(self, audio_bytes, mimetype="audio/mpeg", dual_channel=False):
        """-> {ok, text, segments:[{speaker, text, start}]}"""
        raise NotImplementedError
