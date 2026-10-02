"""Twilio's error wording, translated into something actionable.

Every one of these came up during one setup session and sent the reader
somewhere useless:

* 21215 says "Perhaps you need to enable some international permissions" for
  a call to a Fort Worth number. It is geo-permissions, it hits US numbers on
  a new account, and the fix is two clicks in a place the message does not
  name.
* 21210 reads as though the number is broken. It was simply never bought.
* 21219 looks like both of the above and means a trial account restriction.
"""
import pytest

from dialer.providers.twilio_live import FRIENDLY_CALL_ERRORS, _rest_err


class FakeTwilioError(Exception):
    def __init__(self, code, msg, status=400):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.status = status


GEO = FakeTwilioError(
    21215, "Account not authorized to call +18174032179. Perhaps you need to "
           "enable some international permissions.")


def test_the_geo_error_says_it_affects_us_numbers_too():
    """The raw message says "international", which is why a Texas number
    reads as someone else's problem."""
    out = _rest_err(GEO)["error"]
    assert "US numbers too" in out
    assert "Geo-Permissions" in out


def test_the_geo_error_gives_the_console_path_not_just_a_name():
    out = _rest_err(GEO)["error"]
    for crumb in ("Voice", "Calls", "Geo-Permissions"):
        assert crumb in out


def test_the_code_is_still_findable():
    """Whatever we say, the number has to survive: it is the only thing worth
    pasting into a search."""
    r = _rest_err(GEO)
    assert "21215" in r["error"]
    assert r["code"] == "21215"


def test_an_unowned_source_number_says_so_plainly():
    e = FakeTwilioError(21210, "The source phone number provided, "
                               "+18655550101, is not yet verified.")
    out = _rest_err(e)["error"]
    assert "not one Twilio has sold you" in out
    assert "step 4" in out


def test_a_trial_restriction_offers_both_ways_out():
    e = FakeTwilioError(21219, "The number is unverified.")
    out = _rest_err(e)["error"]
    assert "trial" in out
    assert "Verified Caller IDs" in out
    assert "credit" in out


def test_an_unknown_code_still_shows_twilios_own_words():
    """Inventing friendlier wording for an error nobody has seen would hide
    the only information there is."""
    e = FakeTwilioError(31002, "Something obscure happened.")
    out = _rest_err(e)["error"]
    assert "Something obscure happened." in out
    assert "31002" in out


def test_an_error_with_no_code_still_produces_a_message():
    class Bare(Exception):
        msg = "Connection reset"
        status = 500
    assert "Connection reset" in _rest_err(Bare())["error"]


def test_every_translation_tells_you_where_to_go():
    """A friendlier error that does not say what to do next is just a nicer
    dead end."""
    for code, text in FRIENDLY_CALL_ERRORS.items():
        assert len(text) > 80, code
        assert any(w in text for w in ("Twilio", "step 4", "console")), code
