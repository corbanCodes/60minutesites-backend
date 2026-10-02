"""Reading a Twilio profile's type without inventing one.

A Trust Hub bundle does not say whether it is a Business or an Individual
profile. There is no type field on it and no endpoint that returns one. The
only thing that encodes it is the policy it was filed under, and the policy's
friendly_name says it in words.

This exists because the first version hard-coded three policy SIDs, two of
them wrong, then fell back to searching the bundle's text for the word
"business" and defaulted to "individual" when it did not find it. A real,
approved, Primary Business profile named "Lead Sprinter / 60 Minute Sites"
therefore came back as an individual, and the setup page told its owner in red
that they had hit a dead end and should start over.

Every test here is a shape Twilio actually returns.
"""
import json

import pytest

from dialer.providers import twilio_live


# Twilio does not publish the Primary Business policy SID, because a primary
# profile can only be created in the console and so is never POSTed. Anything
# that depends on knowing it is already broken; this stand-in is deliberately
# not in any list in the source.
PRIMARY_BUSINESS_POLICY = "RNaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PRIMARY_INDIVIDUAL_POLICY = "RNbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

BUNDLE_SID = "BU3da6682bb109f1910e3ddaaebec82a2b"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def install(monkeypatch, *, profiles, policies=None, entities=None,
            policies_status=200, entities_status=200):
    """Stand in for Trust Hub. Records which URLs were asked for."""
    calls = []

    def fake_get(url, **kw):
        calls.append((url, (kw.get("params") or {})))
        if url.startswith(twilio_live.TRUSTHUB_POLICIES_URL):
            if policies is None or policies_status != 200:
                return FakeResponse({}, policies_status or 500)
            return FakeResponse({"results": policies})
        if url.endswith("/EntityAssignments"):
            if entities is None or entities_status != 200:
                return FakeResponse({}, entities_status or 500)
            return FakeResponse({"results": entities})
        if url.startswith(twilio_live.TRUSTHUB_PROFILES_URL):
            return FakeResponse({"results": profiles})
        raise AssertionError("unexpected URL " + url)

    monkeypatch.setattr(twilio_live.requests, "get", fake_get)
    return calls


@pytest.fixture
def client(monkeypatch):
    cls = twilio_live.TwilioTelephony
    c = cls.__new__(cls)
    monkeypatch.setattr(cls, "_has_credentials", lambda self: True)
    monkeypatch.setattr(cls, "_basic_auth", lambda self: ("AC123", "tok"))
    return c


def approved(policy_sid, friendly_name="Lead Sprinter / 60 Minute Sites"):
    return {"sid": BUNDLE_SID, "policy_sid": policy_sid,
            "friendly_name": friendly_name, "status": "twilio-approved",
            "email": "corban@example.com", "valid_until": None}


# ---------------------------------------------------------------- the bug
def test_approved_primary_business_profile_reads_as_business(client, monkeypatch):
    """The exact production case. An approved primary business profile, a
    policy SID nobody publishes, and a company name with no "business" in it."""
    install(monkeypatch,
            profiles=[approved(PRIMARY_BUSINESS_POLICY)],
            policies=[{"sid": PRIMARY_BUSINESS_POLICY,
                       "friendly_name": "Primary Customer Profile of type "
                                        "Business"}])
    r = client.customer_profiles()
    assert r["ok"] is True
    assert r["status"] == "business", (
        "an approved Business profile must not be reported as anything else")
    assert r["sid"] == BUNDLE_SID


def test_company_name_without_the_word_business_is_not_an_individual(
        client, monkeypatch):
    """The old code searched the bundle's own text. A friendly_name is typed
    by the customer, so that made the answer depend on their company name."""
    install(monkeypatch,
            profiles=[approved(PRIMARY_BUSINESS_POLICY,
                               friendly_name="Northline Fencing")],
            policies=[{"sid": PRIMARY_BUSINESS_POLICY,
                       "friendly_name": "Primary Customer Profile of type "
                                        "Business"}])
    assert client.customer_profiles()["status"] == "business"


def test_a_company_with_individual_in_its_name_is_still_a_business(
        client, monkeypatch):
    """The mirror image, and the reason text sniffing had to go: the old code
    would have called this one an individual on the strength of its name."""
    install(monkeypatch,
            profiles=[approved(PRIMARY_BUSINESS_POLICY,
                               friendly_name="Individual Care Partners LLC")],
            policies=[{"sid": PRIMARY_BUSINESS_POLICY,
                       "friendly_name": "Primary Customer Profile of type "
                                        "Business"}])
    assert client.customer_profiles()["status"] == "business"


# ------------------------------------------------------- genuine individuals
def test_an_actual_individual_profile_still_reads_as_individual(
        client, monkeypatch):
    install(monkeypatch,
            profiles=[approved(PRIMARY_INDIVIDUAL_POLICY)],
            policies=[{"sid": PRIMARY_INDIVIDUAL_POLICY,
                       "friendly_name": "Primary Customer Profile of type "
                                        "Individual"}])
    assert client.customer_profiles()["status"] == "individual"


def test_a_starter_profile_reads_as_individual_by_its_published_sid(
        client, monkeypatch):
    """Starter is the one individual-ish policy Twilio does publish, so it
    resolves even with the policy catalogue unavailable."""
    starter = next(iter(twilio_live.INDIVIDUAL_POLICY_SIDS))
    install(monkeypatch, profiles=[approved(starter)], policies=None)
    assert client.customer_profiles()["status"] == "individual"


# -------------------------------------------------- the independent fallback
def test_falls_back_to_the_business_entity_when_policies_are_unreadable(
        client, monkeypatch):
    """If the policy catalogue 403s, the business-information EndUser is a
    second proof that does not depend on knowing any SID."""
    calls = install(monkeypatch,
                    profiles=[approved(PRIMARY_BUSINESS_POLICY)],
                    policies=None, policies_status=403,
                    entities=[{"sid": "BV1", "object_sid": "IT1"}])
    assert client.customer_profiles()["status"] == "business"
    assert any(u.endswith("/EntityAssignments") for u, _ in calls)
    kinds = [p.get("ObjectType") for _, p in calls if p.get("ObjectType")]
    assert twilio_live.BUSINESS_END_USER_TYPE in kinds


# ------------------------------------------------- never guess "individual"
def test_an_unresolvable_type_is_unknown_and_never_individual(
        client, monkeypatch):
    """The whole point. When we cannot establish the type, say so. Guessing
    the weaker answer is not caution; it tells someone with a good profile to
    throw it away and start again."""
    install(monkeypatch,
            profiles=[approved(PRIMARY_BUSINESS_POLICY)],
            policies=None, policies_status=500,
            entities=None, entities_status=500)
    r = client.customer_profiles()
    assert r["status"] == "unknown"
    assert r["status"] != "individual"
    assert r["sid"] == BUNDLE_SID


def test_no_business_entity_present_is_still_unknown_not_individual(
        client, monkeypatch):
    """An empty EntityAssignments list is weak evidence, not proof. Twilio
    filters it server-side and we are not certain enough to convict."""
    install(monkeypatch,
            profiles=[approved(PRIMARY_BUSINESS_POLICY)],
            policies=None, policies_status=403,
            entities=[])
    assert client.customer_profiles()["status"] == "unknown"


# ------------------------------------------------------------ other states
def test_a_profile_in_review_reads_as_pending(client, monkeypatch):
    install(monkeypatch,
            profiles=[{"sid": BUNDLE_SID, "policy_sid": PRIMARY_BUSINESS_POLICY,
                       "friendly_name": "Lead Sprinter",
                       "status": "in-review"}],
            policies=[])
    assert client.customer_profiles()["status"] == "pending"


def test_no_profiles_at_all_reads_as_none(client, monkeypatch):
    install(monkeypatch, profiles=[], policies=[])
    assert client.customer_profiles()["status"] == "none"


def test_business_wins_when_an_account_holds_both(client, monkeypatch):
    """Report the strongest approved profile. An old starter bundle sitting
    beside a real business one must not drag the answer down."""
    starter = next(iter(twilio_live.INDIVIDUAL_POLICY_SIDS))
    install(monkeypatch,
            profiles=[approved(starter, "old starter"),
                      approved(PRIMARY_BUSINESS_POLICY, "Lead Sprinter")],
            policies=[{"sid": PRIMARY_BUSINESS_POLICY,
                       "friendly_name": "Primary Customer Profile of type "
                                        "Business"}])
    assert client.customer_profiles()["status"] == "business"


# ----------------------------------------------------- the hard-coded lists
def test_no_trust_product_policy_sid_is_mistaken_for_a_profile_policy():
    """The original list contained RNb0d477..., which is the A2P Standard
    TRUST PRODUCT policy, not a customer profile policy at all. Keeping these
    out matters more than having many."""
    trust_products = {
        "RNb0d4771c2c98518d916a3d4cd70a8f8b",  # A2P Standard / Low-Volume
        "RN670d5d2e282a6130ae063b234b6019c8",  # Sole Proprietor A2P
        "RN7a97559effdf62d00f4298208492a5ea",  # SHAKEN/STIR
        "RN5b3660f9598883b1df4e77f77acefba0",  # Voice Integrity
        "RNf3db3cd1fe25fcfd3c3ded065c8fea53",  # CNAM
    }
    hard_coded = (twilio_live.BUSINESS_POLICY_SIDS
                  | twilio_live.INDIVIDUAL_POLICY_SIDS)
    assert not (hard_coded & trust_products), (
        "a trust product policy is in the customer profile lists")
