"""Live Twilio telephony.

The counterpart to `fakes.FakeTelephony`: same methods, same return shapes, so
the dialer UI, the webhook routes and the tests cannot tell them apart. Every
method returns a dict and NEVER raises -- a carrier outage has to render an
error card, not a 500 on a rep mid-session.

Three Twilio behaviours in here are not obvious, and each has cost somebody a
day at some point. They are documented on the methods that handle them:

  * `verify()`    -- a *Standard* API key cannot read /Accounts (error 20003)
                     even though it can place calls perfectly well.
  * `fetch_recording()` -- recording media URLs require HTTP Basic auth; they
                     are not public links you can hand to an <audio> tag.
  * `redirect_call()`   -- the inline `Twiml` parameter is capped at 4000 chars.

The `twilio` package is imported lazily (or guarded at module top) so this file
still imports on a machine without the SDK; `registry.py` only reaches for it
when an account is not simulating.
"""
import inspect

import requests

from dialer.providers.base import Telephony, err, ok

try:  # the SDK is optional at import time -- see the module docstring
    from twilio.base.exceptions import TwilioRestException
except Exception:  # pragma: no cover - only hit when twilio isn't installed
    class TwilioRestException(Exception):
        code = None
        msg = ""
        status = None


NO_CREDENTIALS = "Add your Twilio keys in Setup first."
NO_API_KEY = "A Twilio API key is required for the browser phone."

# Twilio sends these four for every leg; the webhook router keys off them.
CALL_EVENTS = ["initiated", "ringing", "answered", "completed"]

# `<Twiml>` passed inline on a call update is capped by the REST API.
TWIML_MAX_CHARS = 4000

TRUSTHUB_PROFILES_URL = "https://trusthub.twilio.com/v1/CustomerProfiles"
HTTP_TIMEOUT = 30

TRUSTHUB_POLICIES_URL = "https://trusthub.twilio.com/v1/Policies"

# A bundle does not say whether it is a Business or an Individual profile.
# Nothing on it does -- there is no type field and no endpoint that returns
# one. The only thing that encodes it is which POLICY the bundle was filed
# under, and the policy's own friendly_name spells it out in words:
# "Primary Customer Profile of type Business". That string is what the Twilio
# console itself displays, so resolving the policy is the authoritative check
# and `_policy_names` does it.
#
# Hard-coding SIDs here was how this got broken before: Twilio never publishes
# the Primary Business policy SID (primary profiles can only be created in the
# console, so you never POST one), two of the three SIDs that used to live here
# were simply wrong, and one of them was a Starter policy sitting in the
# BUSINESS set. These two are documented and are kept only as an offline
# shortcut; the Primary case is resolved by name, never by guessing.
BUSINESS_POLICY_SIDS = {
    "RNdfbf3fae0e1107f8aded0e7cead80bf5",   # Secondary Customer Profile, Business
}
INDIVIDUAL_POLICY_SIDS = {
    "RN806dd6cd175f314e1f96a9727ee271f4",   # Starter Customer Profile
}
# The EndUser that only a business profile carries. Its presence is a second,
# independent proof, used when the policy catalogue cannot be read.
BUSINESS_END_USER_TYPE = "customer_profile_business_information"
APPROVED_STATUSES = {"twilio-approved"}
PENDING_STATUSES = {"draft", "pending-review", "in-review", "pending"}


# ------------------------------------------------------------------ helpers
def _rest_err(e):
    """A TwilioRestException carries the two things worth showing a human:
    the numeric error code (searchable in Twilio's docs) and the message."""
    code = getattr(e, "code", None)
    msg = getattr(e, "msg", "") or str(e)
    status = getattr(e, "status", None)
    if code:
        return err(f"Twilio {code}: {msg}", str(code))
    return err(msg, str(status or "twilio_error"))


def _code_of(e):
    return str(getattr(e, "code", "") or "")


def _is_not_found(e):
    return _code_of(e) == "20404" or getattr(e, "status", None) == 404


def _digits(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _bool_str(v):
    """Twilio wants the literal strings "true"/"false" for a few parameters
    (AsyncAmd, Beep) -- a Python bool urlencodes to "True" which some of them
    reject. Anything that isn't a bool is passed straight through."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _supported(fn, kwargs):
    """twilio-python generates explicit keyword arguments per resource, and the
    sets differ (a conference participant takes `amd_status_callback`, a call
    takes `async_amd_status_callback`). Dropping anything the installed SDK
    doesn't know about turns a TypeError into a silently ignored option, which
    is the right trade for a dialer."""
    try:
        allowed = set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in allowed}


class TwilioTelephony(Telephony):
    """Live Twilio. Construct with a `DialerSettings` row (or None)."""

    # The base class calls itself "telephony"; the live one names the vendor.
    # Nothing keys off this today -- it's for logs and the setup screen.
    name = "twilio"

    def __init__(self, settings=None):
        self.settings = settings
        self._rest = None
        self._creds_cache = None

    # ------------------------------------------------------------ plumbing
    def _secret(self, field):
        s = self.settings
        if s is None:
            return ""
        try:
            return (s.secret(field) or "").strip()
        except Exception:
            return ""

    def _creds(self):
        if self._creds_cache is None:
            self._creds_cache = {
                "account_sid": self._secret("twilio_account_sid"),
                "auth_token": self._secret("twilio_auth_token"),
                "api_key_sid": self._secret("twilio_api_key_sid"),
                "api_key_secret": self._secret("twilio_api_key_secret"),
            }
        return self._creds_cache

    def _basic_auth(self):
        """HTTP Basic pair for the raw-requests calls (recording media,
        TrustHub). An API key works anywhere the auth token does."""
        c = self._creds()
        if c["api_key_sid"] and c["api_key_secret"]:
            return (c["api_key_sid"], c["api_key_secret"])
        return (c["account_sid"], c["auth_token"])

    def _has_credentials(self):
        c = self._creds()
        return bool(c["account_sid"]) and bool(
            (c["api_key_sid"] and c["api_key_secret"]) or c["auth_token"])

    def _client(self):
        """-> (client, None) on success, (None, err_dict) otherwise.

        Prefers the API key pair, because that's what a customer can rotate or
        revoke without touching their master auth token. The account SID is
        still passed so the client addresses the right account.
        """
        if self._rest is not None:
            return self._rest, None
        if not self._has_credentials():
            return None, err(NO_CREDENTIALS, "no_credentials")
        try:
            from twilio.rest import Client
        except Exception as e:
            return None, err(f"The twilio package is not installed ({e}).",
                             "no_sdk")
        c = self._creds()
        try:
            if c["api_key_sid"] and c["api_key_secret"]:
                self._rest = Client(c["api_key_sid"], c["api_key_secret"],
                                    c["account_sid"])
            else:
                self._rest = Client(c["account_sid"], c["auth_token"])
        except Exception as e:
            return None, err(e, "twilio_error")
        return self._rest, None

    # -------------------------------------------------------------- account
    def verify(self):
        """Account name, balance, trial flag and the numbers we own.

        THE 20003 TRAP: a Standard API key is allowed to place calls, mint
        tokens and manage numbers, but is NOT allowed to read the /Accounts
        resource -- Twilio answers 20003 "Authentication Error". A naive
        verify() therefore tells the customer their perfectly good key is
        broken. So on a 20003 we fall back to listing incoming phone numbers
        (which the key *can* do) and still report success.
        """
        client, bad = self._client()
        if bad:
            return bad
        c = self._creds()
        balance = ""
        try:
            account = client.api.v2010.accounts(c["account_sid"]).fetch()
            try:
                balance = str(getattr(client.balance.fetch(), "balance", "") or "")
            except TwilioRestException as e:
                if _code_of(e) != "20003":
                    raise
            except Exception:
                balance = ""
        except TwilioRestException as e:
            if _code_of(e) == "20003":
                return self._verify_via_numbers(client)
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")

        try:
            numbers = [n.phone_number for n in
                       client.incoming_phone_numbers.list(limit=100)]
        except Exception:
            numbers = []
        return ok(account_name=getattr(account, "friendly_name", "") or "",
                  balance=balance,
                  is_trial=(getattr(account, "type", "") == "Trial"),
                  numbers=numbers)

    def _verify_via_numbers(self, client):
        """The 20003 fallback: proving the key can reach the account at all."""
        try:
            numbers = [n.phone_number for n in
                       client.incoming_phone_numbers.list(limit=100)]
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(account_name="(verified via phone numbers)", balance="",
                  is_trial=False, numbers=numbers)

    # -------------------------------------------------------------- numbers
    def list_numbers(self):
        client, bad = self._client()
        if bad:
            return bad
        try:
            rows = client.incoming_phone_numbers.list(limit=100)
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(numbers=[{"e164": n.phone_number,
                            "sid": n.sid,
                            "friendly_name": n.friendly_name or "",
                            "region": getattr(n, "region", "") or ""}
                           for n in rows])

    def search_numbers(self, area_code=None, contains=None, limit=10):
        """US local numbers available to buy. `monthly` is Twilio's published
        US local price; the search endpoint doesn't return pricing."""
        client, bad = self._client()
        if bad:
            return bad
        kw = {"limit": max(1, int(limit or 10))}
        ac = _digits(area_code)[:3]
        if ac:
            kw["area_code"] = int(ac)
        if contains:
            kw["contains"] = str(contains)
        try:
            rows = client.available_phone_numbers("US").local.list(**kw)
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(numbers=[{"e164": n.phone_number,
                            "friendly_name": n.friendly_name or "",
                            "region": getattr(n, "region", "") or "",
                            "monthly": 1.15}
                           for n in rows])

    def buy_number(self, e164, voice_url, status_callback):
        client, bad = self._client()
        if bad:
            return bad
        try:
            n = client.incoming_phone_numbers.create(
                phone_number=e164, voice_url=voice_url, voice_method="POST",
                status_callback=status_callback, status_callback_method="POST")
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(e164=n.phone_number, sid=n.sid)

    def release_number(self, sid):
        client, bad = self._client()
        if bad:
            return bad
        try:
            client.incoming_phone_numbers(sid).delete()
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok()

    def configure_number(self, sid, voice_url, status_callback):
        """Point an owned number at our webhooks -- called after a domain
        change as well as after a purchase."""
        client, bad = self._client()
        if bad:
            return bad
        try:
            client.incoming_phone_numbers(sid).update(
                voice_url=voice_url, voice_method="POST",
                status_callback=status_callback, status_callback_method="POST")
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok()

    # --------------------------------------------------------- twiml app/key
    def ensure_twiml_app(self, voice_url, friendly_name):
        """Idempotent: reuse the stored app SID, else one with our friendly
        name, else create. The stored SID can point at an app that was deleted
        in the Twilio console, so a 20404 on the fetch falls through to create
        rather than erroring. The voice URL is re-pointed on reuse, because the
        app has to follow us when the backend's hostname changes.
        """
        client, bad = self._client()
        if bad:
            return bad
        stored = (getattr(self.settings, "twilio_twiml_app_sid", "") or "").strip()
        if stored:
            try:
                app = client.applications(stored).fetch()
                return self._point_app(client, app, voice_url)
            except TwilioRestException as e:
                if not _is_not_found(e):
                    return _rest_err(e)
            except Exception as e:
                return err(e, "twilio_error")

        try:
            found = client.applications.list(friendly_name=friendly_name, limit=20)
            if found:
                return self._point_app(client, found[0], voice_url)
            app = client.applications.create(
                friendly_name=friendly_name, voice_url=voice_url,
                voice_method="POST")
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(sid=app.sid)

    def _point_app(self, client, app, voice_url):
        try:
            if voice_url and getattr(app, "voice_url", "") != voice_url:
                client.applications(app.sid).update(
                    voice_url=voice_url, voice_method="POST")
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(sid=app.sid)

    def ensure_api_key(self, friendly_name):
        """Mint a Standard API key.

        THE SECRET IS READABLE EXACTLY ONCE -- Twilio returns it in this
        response body and never again. Store it (encrypted) before returning,
        or the key is dead weight and has to be re-created.
        """
        client, bad = self._client()
        if bad:
            return bad
        try:
            key = client.new_keys.create(friendly_name=friendly_name)
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(sid=key.sid, secret=key.secret)

    def access_token(self, identity, twiml_app_sid, ttl=3600):
        """JWT for the browser softphone (twilio.js Device).

        Signed locally with the API key pair -- no network call -- which is why
        the browser phone needs an API key even though REST calls would work
        off the auth token alone.
        """
        c = self._creds()
        if not c["account_sid"]:
            return err(NO_CREDENTIALS, "no_credentials")
        if not (c["api_key_sid"] and c["api_key_secret"]):
            return err(NO_API_KEY, "no_api_key")
        try:
            from twilio.jwt.access_token import AccessToken
            from twilio.jwt.access_token.grants import VoiceGrant
        except Exception as e:
            return err(f"The twilio package is not installed ({e}).", "no_sdk")
        seconds = int(ttl or 3600)
        try:
            token = AccessToken(c["account_sid"], c["api_key_sid"],
                                c["api_key_secret"], identity=identity,
                                ttl=seconds)
            token.add_grant(VoiceGrant(outgoing_application_sid=twiml_app_sid,
                                       incoming_allow=True))
            jwt = token.to_jwt()
        except Exception as e:
            return err(e, "twilio_error")
        if isinstance(jwt, bytes):
            jwt = jwt.decode("utf-8")
        return ok(token=jwt, identity=identity, expires_in=seconds)

    # ---------------------------------------------------------------- calls
    def dial_participant(self, conference, to, from_, **kw):
        """Add the prospect's leg to the rep's conference.

        `early_media` is the one that matters for a power dialer: without it
        the rep hears nothing until the prospect answers, so ringback, busy
        tones and intercept messages are all invisible. Defaults here are the
        dialer's house style; anything in **kw overrides them.
        """
        client, bad = self._client()
        if bad:
            return bad
        args = {
            "to": to,
            "from_": from_,
            "early_media": True,
            "beep": "false",
            "end_conference_on_exit": False,
            "start_conference_on_enter": True,
            "status_callback_event": list(CALL_EVENTS),
        }
        passthrough = ("early_media", "beep", "muted", "end_conference_on_exit",
                       "start_conference_on_enter", "record", "recording_track",
                       "timeout", "label", "status_callback",
                       "status_callback_event", "machine_detection", "async_amd",
                       "amd_status_callback", "machine_detection_timeout")
        for k in passthrough:
            if kw.get(k) is not None:
                args[k] = kw[k]
        args["beep"] = _bool_str(args.get("beep"))
        if args.get("async_amd") is not None:
            args["async_amd"] = _bool_str(args["async_amd"])
        if args.get("status_callback"):
            args["status_callback_method"] = "POST"
        if args.get("amd_status_callback"):
            args["amd_status_callback_method"] = "POST"
        try:
            participants = client.conferences(conference).participants
            p = participants.create(**_supported(participants.create, args))
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(sid=p.call_sid)

    def create_call(self, to, from_, url=None, status_callback=None, **kw):
        """Plain outbound leg: click-to-call, AI outbound, voicemail blast.

        Pass `twiml=` to inline the instructions instead of making Twilio fetch
        `url` -- used when we already know exactly what the leg should say.
        """
        client, bad = self._client()
        if bad:
            return bad
        args = {"to": to, "from_": from_,
                "status_callback_event": list(CALL_EVENTS)}
        twiml = kw.get("twiml")
        if twiml:
            args["twiml"] = twiml
        else:
            args["url"] = url
            args["method"] = "POST"
        if status_callback:
            args["status_callback"] = status_callback
            args["status_callback_method"] = "POST"
        for k in ("record", "recording_track", "machine_detection",
                  "machine_detection_timeout", "time_limit", "timeout",
                  "caller_id", "call_reason"):
            if kw.get(k) is not None:
                args[k] = kw[k]
        if kw.get("async_amd") is not None:
            args["async_amd"] = _bool_str(kw["async_amd"])
        # Calls name this parameter AsyncAmdStatusCallback; conference
        # participants name the same thing AmdStatusCallback. Callers use one
        # spelling, we translate.
        amd_cb = kw.get("amd_status_callback") or kw.get("async_amd_status_callback")
        if amd_cb:
            args["async_amd_status_callback"] = amd_cb
            args["async_amd_status_callback_method"] = "POST"
        try:
            call = client.calls.create(**_supported(client.calls.create, args))
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(sid=call.sid, queue_time=getattr(call, "queue_time", None))

    def redirect_call(self, sid, twiml):
        """The one-click voicemail drop: yank a live leg out of the conference
        and hand it a <Play> of the pre-recorded message.

        THE 4000-CHARACTER CAP: the inline `Twiml` parameter on a call update
        is limited to 4000 characters. Longer documents must be served from a
        URL instead, so we refuse here rather than let Twilio reject the call
        mid-drop with a confusing 400.
        """
        client, bad = self._client()
        if bad:
            return bad
        body = twiml or ""
        if len(body) > TWIML_MAX_CHARS:
            return err(
                f"TwiML is {len(body)} characters; Twilio caps inline TwiML at "
                f"{TWIML_MAX_CHARS}. Serve it from a URL instead.",
                "twiml_too_long")
        try:
            client.calls(sid).update(twiml=body)
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok()

    def hangup(self, sid):
        client, bad = self._client()
        if bad:
            return bad
        try:
            client.calls(sid).update(status="completed")
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok()

    def update_participant(self, conference, call_sid, **kw):
        """Mute, hold, or drop a supervisor into coaching on a live leg."""
        client, bad = self._client()
        if bad:
            return bad
        args = {}
        for k in ("muted", "hold", "hold_url", "hold_method", "coaching",
                  "call_sid_to_coach", "announce_url", "beep_on_exit",
                  "end_conference_on_exit"):
            if kw.get(k) is not None:
                args[k] = kw[k]
        if not args:
            return ok(applied={})
        try:
            part = client.conferences(conference).participants(call_sid)
            part.update(**_supported(part.update, args))
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok(applied=args)

    def fetch_call(self, sid):
        """Billing truth after the fact. Twilio reports `price` as a negative
        number (it's a debit), so it's normalised to a positive cost here."""
        client, bad = self._client()
        if bad:
            return bad
        try:
            c = client.calls(sid).fetch()
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        try:
            duration = int(getattr(c, "duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0
        try:
            price = abs(float(getattr(c, "price", 0) or 0))
        except (TypeError, ValueError):
            price = 0.0
        return ok(status=getattr(c, "status", "") or "", duration=duration,
                  price=price, answered_by=getattr(c, "answered_by", "") or "")

    # ----------------------------------------------------------- recordings
    def fetch_recording(self, sid):
        """Download the .mp3 bytes for a recording.

        MEDIA URLS REQUIRE AUTH: `https://api.twilio.com/.../RExxx.mp3` is NOT
        a public link. Handing it to a browser <audio> tag yields a 401 (or, if
        the account ever flips to public media, leaks the recording). So we
        fetch it server-side with HTTP Basic auth and stream the bytes through
        our own authenticated route.
        """
        client, bad = self._client()
        if bad:
            return bad
        try:
            rec = client.recordings(sid).fetch()
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")

        uri = getattr(rec, "uri", "") or ""
        if uri:
            media_url = "https://api.twilio.com" + uri.replace(".json", ".mp3")
        else:
            media_url = ("https://api.twilio.com/2010-04-01/Accounts/"
                         f"{rec.account_sid}/Recordings/{rec.sid}.mp3")
        try:
            r = requests.get(media_url, auth=self._basic_auth(),
                             timeout=HTTP_TIMEOUT)
        except Exception as e:
            return err(e, "network_error")
        if r.status_code != 200:
            return err(f"Twilio returned {r.status_code} for the recording media.",
                       f"http_{r.status_code}")
        try:
            duration = int(getattr(rec, "duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0
        return ok(content=r.content, mimetype="audio/mpeg", duration=duration)

    def delete_recording(self, sid):
        client, bad = self._client()
        if bad:
            return bad
        try:
            client.recordings(sid).delete()
        except TwilioRestException as e:
            return _rest_err(e)
        except Exception as e:
            return err(e, "twilio_error")
        return ok()

    # --------------------------------------------------------------- lookup
    def lookup(self, e164):
        """Line Type Intelligence -- the mobile/landline gate for AI dialling.

        DELIBERATELY NEVER RETURNS err(). A failed lookup (outage, rate limit,
        missing keys, an unparseable number) returns line_type="unknown".
        "unknown" sits in RESTRICTED_LINE_TYPES, so a failure makes the gate
        STRICTER, never looser. If this returned err() and a caller treated a
        falsy result as "no restriction found", a Twilio outage would silently
        un-gate mobile dialling -- which is the one failure mode that costs
        real TCPA money.

        Twilio's values pass through untouched: landline, mobile, fixedVoip,
        nonFixedVoip, tollFree, voicemail, unknown.
        """
        client, bad = self._client()
        if bad:
            return ok(line_type="unknown", carrier="",
                      raw={"error": bad.get("error", ""), "code": "no_credentials"})
        try:
            pn = client.lookups.v2.phone_numbers(e164).fetch(
                fields="line_type_intelligence")
            lti = getattr(pn, "line_type_intelligence", None) or {}
            if not isinstance(lti, dict):
                lti = {}
            line_type = (lti.get("type") or "").strip() or "unknown"
            carrier = (lti.get("carrier_name") or "").strip()
            return ok(line_type=line_type, carrier=carrier,
                      raw={"line_type_intelligence": lti,
                           "valid": getattr(pn, "valid", None)})
        except TwilioRestException as e:
            return ok(line_type="unknown", carrier="",
                      raw={"error": getattr(e, "msg", "") or str(e),
                           "code": _code_of(e)})
        except Exception as e:
            return ok(line_type="unknown", carrier="",
                      raw={"error": str(e), "code": "twilio_error"})

    # ------------------------------------------------------------ signatures
    def validate_signature(self, signature, url, params):
        """Webhook authenticity. Always signed with the ACCOUNT AUTH TOKEN --
        an API key secret will not validate, no matter how the client was
        built. Returns a plain bool; a missing token is a hard False."""
        token = self._creds()["auth_token"]
        if not token or not signature:
            return False
        try:
            from twilio.request_validator import RequestValidator
            return bool(RequestValidator(token).validate(
                url, params or {}, signature))
        except Exception:
            return False

    # -------------------------------------------------------------- trusthub
    def customer_profiles(self):
        """Trust Hub profile status -> none|individual|business|unknown|pending.

        Hit with raw requests because the shape of these bundles changes more
        often than the SDK does. Never errors out: an unreadable TrustHub
        returns status="unknown" so the setup screen can say "couldn't check"
        instead of claiming the account has no profile.

        An approved profile whose TYPE cannot be established also comes back
        "unknown" rather than "individual". Guessing the weaker answer sounds
        cautious and is not: it tells someone holding a perfectly good business
        profile that they have hit a dead end and should start over.
        """
        if not self._has_credentials():
            return err(NO_CREDENTIALS, "no_credentials")
        try:
            r = requests.get(TRUSTHUB_PROFILES_URL, auth=self._basic_auth(),
                             params={"PageSize": 50}, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                return ok(status="unknown", sid="",
                          error=f"TrustHub returned {r.status_code}")
            payload = r.json() or {}
        except Exception as e:
            return ok(status="unknown", sid="", error=str(e))

        bundles = payload.get("results")
        if not isinstance(bundles, list):
            bundles = payload.get("customer_profiles") or []
        if not isinstance(bundles, list):
            return ok(status="unknown", sid="")

        approved = [b for b in bundles if isinstance(b, dict)
                    and str(b.get("status") or "").strip().lower()
                    in APPROVED_STATUSES]
        pending = next((str(b.get("sid") or "") for b in bundles
                        if isinstance(b, dict)
                        and str(b.get("status") or "").strip().lower()
                        in PENDING_STATUSES), None)

        if approved:
            # One lookup covers every bundle, so it costs the same whether the
            # account has one profile or ten.
            names = self._policy_names()
            kinds = [(self._profile_kind(b, names), str(b.get("sid") or ""))
                     for b in approved]
            for want in ("business", "individual"):
                hit = next((sid for kind, sid in kinds if kind == want), None)
                if hit:
                    return ok(status=want, sid=hit)
            return ok(status="unknown", sid=kinds[0][1],
                      error="Twilio approved this profile but did not say "
                            "whether it is a business or an individual one.")
        if pending:
            return ok(status="pending", sid=pending)
        return ok(status="none", sid="")

    def _policy_names(self):
        """{policy_sid: friendly_name} for the account's policy catalogue.

        The friendly name is the whole point: Twilio writes "Primary Customer
        Profile of type Business" there, which is the exact string the console
        shows. An empty dict means the catalogue was unreadable, and the
        callers degrade rather than guess.
        """
        try:
            r = requests.get(TRUSTHUB_POLICIES_URL, auth=self._basic_auth(),
                             params={"PageSize": 100}, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                return {}
            results = (r.json() or {}).get("results")
            if not isinstance(results, list):
                return {}
            return {str(p.get("sid") or ""): str(p.get("friendly_name") or "")
                    for p in results if isinstance(p, dict)}
        except Exception:
            return {}

    def _has_business_entity(self, bundle_sid):
        """True when the bundle carries the EndUser only a business profile has.

        Independent of the policy catalogue, so it still answers when that call
        fails. None means the question could not be asked, which is different
        from False and is why this does not return a plain bool.
        """
        if not bundle_sid:
            return None
        try:
            r = requests.get(
                f"{TRUSTHUB_PROFILES_URL}/{bundle_sid}/EntityAssignments",
                auth=self._basic_auth(),
                params={"ObjectType": BUSINESS_END_USER_TYPE, "PageSize": 5},
                timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                return None
            results = (r.json() or {}).get("results")
            if not isinstance(results, list):
                return None
            return bool(results)
        except Exception:
            return None

    def _profile_kind(self, bundle, policy_names=None):
        """business | individual | unknown, in order of how much it is worth.

        1. The policy's friendly_name, which says the answer in English and is
           what the console reads.
        2. The two policy SIDs Twilio actually publishes.
        3. Whether the bundle carries the business-information EndUser.
        4. Give up and say unknown.

        What it deliberately no longer does is sniff the bundle's own text.
        A bundle carries a friendly_name the customer typed, so a company
        called anything without the word "business" in it read as an
        individual, and that is precisely the bug this replaces.
        """
        policy = str(bundle.get("policy_sid") or "")

        name = (policy_names or {}).get(policy, "").lower()
        if name:
            # "Primary Customer Profile of type Business" and its siblings.
            if "individual" in name or "starter" in name or "sole prop" in name:
                return "individual"
            if "business" in name:
                return "business"

        if policy in BUSINESS_POLICY_SIDS:
            return "business"
        if policy in INDIVIDUAL_POLICY_SIDS:
            return "individual"

        has_business = self._has_business_entity(str(bundle.get("sid") or ""))
        if has_business is True:
            return "business"

        return "unknown"
