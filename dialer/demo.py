"""A believable dialer account, built in a couple of seconds.

This exists for the two moments where an empty product loses the sale: a live
demo call, and a screenshot. Every row here goes through the real pipeline --
the gate, the queue, the fake carrier, finalize, the AI pass -- so what a
prospect sees on the screen is the same code path a paying account runs, not a
set of hand-written fixtures that will drift out of date by Friday.

Outcomes are driven by the LAST DIGIT of each phone number (see
dialer/providers/fakes.py), so the demo is reproducible: the same venue
answers, the same one is busy, every single time you rehearse it.

Safety rule, enforced throughout: this module only ever deletes rows it
created. Leads are matched on the `demo-dial` tag; campaigns, agents,
playbooks, voicemail drops and numbers are matched on a "Demo: " name prefix.
Nothing else on the account is touched, ever.
"""
import json
import random
from datetime import datetime, timedelta, timezone

from app import Lead, Note, Task, User, db

from dialer import campaigns as campaigns_mod
from dialer import compliance, simulate
from dialer.models import (AiAgent, Call, CallEvent, Campaign, CampaignLead,
                           ConsentRecord, PhoneNumber, Playbook, Suppression,
                           VoicemailDrop, WebhookInbox)
from dialer.providers import fakes

DEMO_TAG = "demo-dial"
DEMO_PREFIX = "Demo: "

# Share of the seeded list that the demo campaign actually worked through.
# A list that is 100% dialed looks like a fixture; a list with a remainder
# looks like Tuesday.
CAMPAIGN_SHARE = 0.62


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ content
# Area code -> (state, city). Deliberately avoids the states whose seeded rule
# would block or re-window a dial, so the demo behaves the same on a Sunday.
_AREAS = [
    ("865", "TN", "Knoxville"), ("615", "TN", "Nashville"),
    ("212", "NY", "New York"), ("718", "NY", "Brooklyn"),
    ("312", "IL", "Chicago"), ("404", "GA", "Atlanta"),
    ("713", "TX", "Houston"), ("602", "AZ", "Phoenix"),
    ("980", "NC", "Charlotte"), ("503", "OR", "Portland"),
]

_VENUES = [
    ("The Tap Room", "Bar"), ("Brickside Grill", "Restaurant"),
    ("Lantern & Co", "Restaurant"), ("The Copper Still", "Bar"),
    ("Marlowe's Public House", "Pub"), ("Ruby's Diner Co", "Diner"),
    ("The Winding Oak", "Restaurant"), ("Harbor & Vine", "Restaurant"),
    ("Stonecut Tavern", "Tavern"), ("El Portal Cantina", "Restaurant"),
    ("The Gilded Owl", "Bar"), ("Franklin Street Pizza", "Pizzeria"),
    ("Ironwood BBQ", "Restaurant"), ("The Blue Heron Pub", "Pub"),
    ("Casa Mariana", "Restaurant"), ("Northfield Alehouse", "Brewpub"),
    ("Peachtree Smokehouse", "Restaurant"), ("The Rusty Anchor", "Bar"),
    ("Morrow's Steakhouse", "Steakhouse"), ("Saffron Table", "Restaurant"),
    ("The Dockhouse", "Bar"), ("Little Sparrow Cafe", "Cafe"),
    ("Hollis Brothers Grill", "Restaurant"), ("The Mezzanine", "Bar"),
    ("Brass Monkey Bar", "Bar"), ("Verano Taqueria", "Restaurant"),
    ("The Thirsty Scholar", "Pub"), ("Delta Rose Kitchen", "Restaurant"),
    ("Union Yard Brewing", "Brewpub"), ("The Hearth Room", "Restaurant"),
    ("Gino's Trattoria", "Restaurant"), ("Westbrook Oyster Bar", "Bar"),
    ("The Lamplighter", "Tavern"), ("Cedar & Char", "Steakhouse"),
    ("Monroe Street Deli", "Deli"), ("The Pour House", "Bar"),
    ("Sunset Cantina", "Restaurant"), ("Bayou Bend Kitchen", "Restaurant"),
    ("The Tin Roof", "Bar"), ("Granary & Grain", "Cafe"),
]

_FIRST = ["Dana", "Ray", "Mel", "Sam", "Kim", "Tony", "Alma", "Hector",
          "Nicole", "Graham", "Pilar", "Owen", "Rosa", "Dev", "Shauna",
          "Marcus", "Trish", "Eli", "Noor", "Casey"]
_LAST = ["Vance", "Okafor", "Brennan", "Ortiz", "Lindqvist", "Hale", "Moreau",
         "Castellanos", "Whitfield", "Nakamura", "Boyle", "Adeyemi", "Fuentes",
         "Pritchard", "Sandoval", "Keane", "Delacroix", "Barros"]

# Last digit -> simulated outcome. Cycled rather than randomised so a rehearsed
# demo plays back identically.
_DIGIT_CYCLE = [1, 1, 4, 2, 1, 6, 3, 1, 4, 2, 7, 1, 5, 1, 4, 6, 1, 2, 3, 1]

_STATUS_CYCLE = ["New", "New", "Contacted", "New", "Qualified", "Contacted",
                 "New", "Dead", "New", "Booked"]

_SOURCES = ["cold-list", "google-maps", "referral", "walk-in", "yelp",
            "chamber-list"]

_PRIOR_NOTES = [
    "Dropped a sample pack at the host stand in the spring. Never followed up.",
    "Owner is only in Tuesday and Thursday mornings — everyone else defers.",
    "GM said to call back after the patio season starts.",
    "They print their own branded napkins. Worth asking what that costs them.",
    "Bar manager liked the idea, said the owner signs off on anything printed.",
    "Called twice last quarter, both times mid-service. Call before 3pm.",
]

_PLAYBOOK = {
    "name": DEMO_PREFIX + "Napkin outreach — bars & restaurants",
    "description": ("Free ad-supported napkins for hospitality. Qualify in "
                    "under three minutes, then transfer."),
    "steps": [
        {"title": "Opening", "say": "Hi, this is {rep} with {company} — is the "
                                    "owner or the manager around?",
         "goal": "Get past the host stand to someone who buys things"},
        {"title": "One line", "say": "We supply bars and restaurants with free "
                                     "napkins. They carry a small local ad, so "
                                     "they cost you nothing.",
         "goal": "Say it once, then stop talking"},
        {"title": "Permission", "say": "Two quick questions to see if there's "
                                       "any fit — if there isn't, I'll let you "
                                       "get back to it.",
         "goal": "Lower the guard before qualifying"},
        {"title": "Qualify", "say": "Work the four questions in order, cheapest "
                                    "disqualifier first.",
         "goal": "Know the volume and who signs"},
        {"title": "Close", "say": "That's a fit. Let me get you over to the "
                                  "person who sets the delivery up.",
         "goal": "Transfer live, or book a time"},
        {"title": "Log it", "say": "Set the disposition and the next step before "
                                   "the next dial.",
         "goal": "Nothing stays in your head between calls"},
    ],
    "questions": [
        {"question": "Who handles your napkin and paper-goods orders?",
         "collect_as": "decision_maker", "disqualify_if": ""},
        {"question": "Roughly how many tables are you running, counting the bar?",
         "collect_as": "tables", "disqualify_if": "under 15 tables"},
        {"question": "How many cases of napkins do you go through in a week?",
         "collect_as": "napkin_volume", "disqualify_if": ""},
        {"question": "What are you paying a case today, and who supplies them?",
         "collect_as": "current_cost", "disqualify_if": ""},
    ],
    "objections": [
        {"trigger_phrases": ["we already have a supplier", "we buy ours"],
         "response": "Most places your size do. We're not replacing your "
                     "supplier — we're replacing one line item on their "
                     "invoice. You keep everything else with them."},
        {"trigger_phrases": ["what's the catch", "nothing is free"],
         "response": "There's an ad printed in the corner of the napkin. "
                     "That's the entire catch. The advertiser pays for the "
                     "print run, you stop paying for napkins."},
        {"trigger_phrases": ["I don't want ads on my napkins",
                             "that looks cheap"],
         "response": "Fair. It's a one-colour block in the corner, not a "
                     "billboard — and we'll show you the proof before anything "
                     "is printed. If you hate it, you keep buying yours."},
        {"trigger_phrases": ["send me an email", "send me information"],
         "response": "Happy to. What's the best address? And so I send "
                     "something useful instead of a brochure — how many cases "
                     "a week are you going through?"},
        {"trigger_phrases": ["we're slammed", "bad time", "in the middle of "
                             "service"],
         "response": "Of course — I'll be quick or I'll go away. Is 3pm today "
                     "better, or tomorrow before you open?"},
    ],
    "transfer_criteria": ("Transfer when you have the person who buys the "
                          "napkins, at least 15 tables, and a weekly case "
                          "volume. Do not transfer a maybe."),
    "never_do": ("Never quote a price or a term. Never promise the venue a "
                 "payment. Never claim to be a human being. If they ask to be "
                 "taken off the list, record it and end the call warmly."),
}

_VOICEMAIL_TRANSCRIPT = (
    "Hi, this is {company} — we supply bars and restaurants with free napkins. "
    "They carry a small local ad, so they cost you nothing and you stop buying "
    "them. If that's worth two minutes, call us back at {callback} and ask "
    "about the napkin program. Thanks, and have a good service.")


# -------------------------------------------------------------------- build
def seed_demo(account_id, settings, leads=40):
    """Wipe any previous demo on this account and build a fresh one.

    `settings` is the account's DialerSettings row. It is read, not owned, and
    the one field this touches (`enforce_window`) is restored in a finally
    block -- the demo has to produce the same calls at 11pm as it does at 11am,
    but it must not leave the account's compliance window switched off.
    """
    clear_demo(account_id)
    rng = random.Random(1000 + int(account_id or 0))
    owner = db.session.get(User, account_id) if account_id else None
    count = max(1, min(int(leads or 40), len(_VENUES)))

    numbers = _make_numbers(account_id)
    playbook = _make_playbook(account_id)
    agents = _make_agents(account_id, settings, playbook)
    drop = _make_voicemail(account_id, settings)
    made_leads = _make_leads(account_id, settings, count, rng)
    campaign, ran = _run_campaign(account_id, settings, made_leads, playbook,
                                  owner)
    # A second, AI campaign over the landlines further down the list, so a
    # demo shows BOTH lanes side by side -- and shows the gate skipping the
    # mobile numbers, which is the part worth seeing.
    ai_campaign, ai_ran = _run_ai_campaign(account_id, settings, made_leads,
                                           playbook, agents, owner)

    calls = Call.query.filter(Call.account_id == account_id).count()
    lead_ids = [l.id for l in made_leads]
    notes = Note.query.filter(Note.lead_id.in_(lead_ids)).count()
    tasks = Task.query.filter(Task.lead_id.in_(lead_ids)).count()
    return {
        "leads": len(made_leads),
        "calls": calls,
        "dialed": ran.get("dialed", 0),
        "notes": notes,
        "tasks": tasks,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "ai_campaign_id": getattr(ai_campaign, "id", None),
        "ai_dialed": ai_ran.get("dialed", 0),
        "ai_skipped_by_gate": ai_ran.get("skipped_by_gate", 0),
        "playbook_id": playbook.id,
        "agent_ids": [a.id for a in agents],
        "number_ids": [n.id for n in numbers],
        "voicemail_drop_id": drop.id,
    }


def _make_numbers(account_id):
    """One DID for the reps and one for the AI. They cannot be the same number:
    a number imported into ElevenLabs has its Twilio voice webhook owned by
    ElevenLabs, so it can no longer serve the human dialer's callbacks."""
    rep = PhoneNumber(
        account_id=account_id, e164="+18655550101", twilio_sid="PNdemo0101",
        friendly_name=DEMO_PREFIX + "Knoxville 865 (reps)", pool="rep",
        purpose="both", state="active", area_code="865", region="TN",
        daily_cap=120, notes=DEMO_TAG)
    ai = PhoneNumber(
        account_id=account_id, e164="+16155550102", twilio_sid="PNdemo0102",
        friendly_name=DEMO_PREFIX + "Nashville 615 (AI)", pool="ai",
        purpose="both", state="active", area_code="615", region="TN",
        elevenlabs_phone_id="pn_demo_0102", daily_cap=120, notes=DEMO_TAG)
    db.session.add_all([rep, ai])
    db.session.commit()
    return [rep, ai]


def _make_playbook(account_id):
    pb = Playbook(
        account_id=account_id, name=_PLAYBOOK["name"],
        description=_PLAYBOOK["description"],
        steps_json=json.dumps(_PLAYBOOK["steps"]),
        questions_json=json.dumps(_PLAYBOOK["questions"]),
        objections_json=json.dumps(_PLAYBOOK["objections"]),
        transfer_criteria=_PLAYBOOK["transfer_criteria"],
        never_do=_PLAYBOOK["never_do"], is_default=True)
    db.session.add(pb)
    db.session.commit()
    return pb


def _make_agents(account_id, settings, playbook):
    """An outbound screener and an inbound receptionist, both on the one
    playbook, both carrying a fake ElevenLabs id so the simulator will run
    them end to end."""
    company = settings.ai_disclosure_name or "NapkinAds"
    facts = (f"{company} supplies bars and restaurants with free napkins. The "
             "napkins carry one small local advertisement; the advertiser pays "
             "for the print run, so the venue pays nothing and stops buying "
             "napkins. Delivery is monthly. There is no contract and no fee.")
    outbound = AiAgent(
        account_id=account_id, name=DEMO_PREFIX + "Outbound screener",
        direction="outbound", elevenlabs_agent_id="ag_demo_outbound",
        voice_id="sim-rachel", voice_name="Rachel", language="en",
        first_message=("Hi, this is an automated assistant calling on behalf "
                       f"of {company}. Is the owner or manager around?"),
        persona=("Warm, brief and unbothered. Qualifying, not selling. Short "
                 "sentences, and let them talk."),
        company_facts=facts, playbook_id=playbook.id,
        transfer_rules=("Transfer to a person the moment they ask for one, "
                        "without arguing."),
        max_duration_seconds=420, voicemail_behavior="leave_tts",
        voicemail_message=_VOICEMAIL_TRANSCRIPT.format(
            company=company,
            callback=settings.ai_callback_number or "the number on your caller ID"),
        active=True)
    inbound = AiAgent(
        account_id=account_id, name=DEMO_PREFIX + "Inbound receptionist",
        direction="inbound", elevenlabs_agent_id="ag_demo_inbound",
        voice_id="sim-adam", voice_name="Adam", language="en",
        first_message=(f"Thanks for calling {company} — this is an automated "
                       "assistant. How can I help?"),
        persona="Calm and quick. Answer the question, then get them booked.",
        company_facts=facts, playbook_id=playbook.id,
        transfer_rules=("Anyone calling back about an existing delivery goes "
                        "straight to a person."),
        max_duration_seconds=420, active=True)
    db.session.add_all([outbound, inbound])
    db.session.commit()
    return [outbound, inbound]


def _make_voicemail(account_id, settings):
    """No audio file: the transcript alone is what the UI, the AI prompt and
    the compliance record all read, and a demo should never ship a binary."""
    drop = VoicemailDrop(
        account_id=account_id, name=DEMO_PREFIX + "20-second napkin drop",
        # No media_id, because there is no recording -- this exists to show
        # the shape of a good message, not to be played down a phone line.
        # is_default stays False for exactly that reason: a default drop with
        # no audio is a rep pressing the button and sending silence.
        mimetype="audio/wav", duration_s=19.4, is_default=False,
        transcript=_VOICEMAIL_TRANSCRIPT.format(
            company=settings.ai_disclosure_name or "NapkinAds",
            callback=settings.ai_callback_number or "the number on your screen"))
    db.session.add(drop)
    db.session.commit()
    return drop


def _make_leads(account_id, settings, count, rng):
    """Venues across several area codes, with the line-type split that decides
    which of them the AI lane is allowed to touch."""
    tel = fakes.FakeTelephony(settings)
    now = _now()
    out = []
    for i in range(count):
        venue, kind = _VENUES[i]
        area, state, city = _AREAS[i % len(_AREAS)]
        digit = _DIGIT_CYCLE[i % len(_DIGIT_CYCLE)]
        local = 1000 + (i * 10) + digit
        person = f"{_FIRST[i % len(_FIRST)]} {_LAST[i % len(_LAST)]}"
        created = now - timedelta(days=rng.randint(3, 240),
                                  hours=rng.randint(0, 23))
        lead = Lead(
            owner_id=account_id, name=person, business=venue,
            business_type=kind, phone=f"({area}) 555-{local:04d}",
            email="", source=_SOURCES[i % len(_SOURCES)],
            status=_STATUS_CYCLE[i % len(_STATUS_CYCLE)],
            tags=f"{DEMO_TAG},{kind.lower()},{city.lower().replace(' ', '-')}",
            created_at=created)
        db.session.add(lead)
        out.append(lead)
    db.session.commit()

    for i, lead in enumerate(out):
        compliance.enrich_lead(lead)
        r = tel.lookup(lead.phone_e164)
        if r.get("ok"):
            lead.line_type = r.get("line_type", "")
            lead.carrier = r.get("carrier", "")[:120]
            lead.line_type_raw = json.dumps(r.get("raw") or {})
            lead.line_type_checked_at = _now() - timedelta(days=i % 9)
        if i % 3 == 0:
            db.session.add(Note(
                lead_id=lead.id, kind="note",
                body=_PRIOR_NOTES[i % len(_PRIOR_NOTES)],
                created_at=lead.created_at + timedelta(days=1)))
    db.session.commit()

    # Two mobiles with written consent on file: the one path that legitimately
    # unlocks the AI lane for a cell, and the thing a buyer asks to see.
    for lead in [l for l in out if l.line_type == "mobile"][:2]:
        compliance.record_consent(
            account_id, lead, kind="written",
            source="Trade-show card, signed",
            text="Signed card at the state restaurant show: agreed to calls "
                 "about the napkin program, including automated ones.")
    db.session.commit()
    return out


def _run_ai_campaign(account_id, settings, made_leads, playbook, agents, owner):
    """The AI lane. Deliberately pointed at a slice of the list that contains
    BOTH landlines and mobiles, so the demo shows the compliance gate doing its
    job: the landlines get called, the mobiles are skipped with a reason."""
    from dialer.models import CampaignLead
    agent = next((a for a in agents if a.direction == "outbound"), None)
    if agent is None:
        return None, {}
    # The WHOLE list on purpose. The gate then does the filtering in front of
    # the viewer, which is the point: the AI dials the landlines and skips the
    # mobiles with a reason you can read.
    lead_ids = [l.id for l in made_leads]
    campaign = Campaign(
        account_id=account_id,
        name=DEMO_PREFIX + "AI screener — the whole list, gate on",
        mode="ai", playbook_id=playbook.id, ai_agent_id=agent.id,
        number_pool="ai",
        segment_json=json.dumps({"lead_ids": lead_ids, "has_phone": True}),
        status="running", max_concurrent=2,
        created_by=getattr(owner, "id", None),
        started_at=_now() - timedelta(hours=1))
    db.session.add(campaign)
    db.session.commit()
    campaigns_mod.materialize(campaign, settings)

    was_enforcing = settings.enforce_window
    try:
        settings.enforce_window = False
        db.session.commit()
        ran = simulate.run_campaign(campaign, settings)
    finally:
        settings.enforce_window = was_enforcing
        db.session.commit()

    ran["skipped_by_gate"] = CampaignLead.query.filter(
        CampaignLead.campaign_id == campaign.id,
        CampaignLead.state == "skipped").count()
    db.session.refresh(campaign)
    if campaign.status == "running":
        campaign.status = "done"
        campaign.finished_at = _now()
        db.session.commit()
    return campaign, ran


def _run_campaign(account_id, settings, made_leads, playbook, owner):
    """A power campaign over part of the list, driven all the way through the
    real pipeline by the simulator."""
    take = max(1, int(len(made_leads) * CAMPAIGN_SHARE))
    lead_ids = [l.id for l in made_leads[:take]]
    campaign = Campaign(
        account_id=account_id,
        name=DEMO_PREFIX + "Bars & restaurants — Tuesday power block",
        mode="power", playbook_id=playbook.id, number_pool="rep",
        segment_json=json.dumps({"lead_ids": lead_ids, "has_phone": True}),
        status="running", max_concurrent=2, created_by=getattr(owner, "id", None),
        started_at=_now() - timedelta(hours=3))
    db.session.add(campaign)
    db.session.commit()
    campaigns_mod.materialize(campaign, settings)

    # A demo must produce the same calls at 11pm as at 11am. Restored below.
    was_enforcing = settings.enforce_window
    try:
        settings.enforce_window = False
        db.session.commit()
        ran = simulate.run_campaign(campaign, settings)
    finally:
        settings.enforce_window = was_enforcing
        db.session.commit()

    _attribute(campaign, owner)
    _vary_dispositions(campaign, settings, owner)
    db.session.refresh(campaign)
    if campaign.status == "running":
        # Busy and no-answer rows sit in `deferred` waiting on the retry clock,
        # so the campaign never auto-finishes. The demo shows a block that is
        # over; the retry queue behind it stays honest.
        campaign.status = "done"
        campaign.finished_at = _now()
        db.session.commit()
    return campaign, ran


def _attribute(campaign, owner):
    """campaigns.tick() dials without a user id -- in production the rep's
    browser stamps it. Backfill it here so the per-rep leaderboard has
    something in it, and mark the connects as answered inside two seconds so
    the abandon gauge reads the way a compliant power dialer should."""
    for call in Call.query.filter_by(campaign_id=campaign.id).all():
        if owner is not None and call.agent_user_id is None:
            call.agent_user_id = owner.id
        if call.answered_live and call.connected_within_2s is None:
            call.connected_within_2s = True
    db.session.commit()


# What a real connected hour looks like: one booking, a couple of partials,
# a no, and one person who wants off the list. The simulated LLM scores every
# human conversation identically as "qualified", which makes a perfectly
# honest pipeline and a terrible-looking chart.
_VARIED = ["meeting_set", "dm_reached", "callback", "not_interested", "dnc"]


def _vary_dispositions(campaign, settings, owner):
    """Spread the connected calls across the dispositions a real block
    produces, so the outcome chart and the compliance trail both have
    something in them. Includes one do-not-call on purpose: the suppression it
    writes is the thing an enterprise buyer asks to see."""
    from dialer import calls as calls_mod
    connected = [c for c in Call.query.filter_by(campaign_id=campaign.id)
                 .order_by(Call.id).all()
                 if c.answered_live and c.disposition == "qualified"]
    user_id = getattr(owner, "id", None)
    for call, disposition in zip(connected, _VARIED):
        calls_mod.set_disposition(call, disposition, user_id=user_id,
                                  settings=settings)
        _restamp_note(call)
    db.session.commit()


def _restamp_note(call):
    """finalize() wrote the lead's call note before we changed the outcome, so
    the note would read "Qualified" under a meeting. Rebuild it from the same
    helper finalize uses rather than leaving a demo that contradicts itself."""
    from dialer import calls as calls_mod
    note = (Note.query
            .filter(Note.lead_id == call.lead_id, Note.kind == "call",
                    Note.body.like(f"%[call:{call.id}]%")).first())
    if note is not None:
        note.body = calls_mod._call_note(call)


# -------------------------------------------------------------------- clear
def demo_present(account_id):
    """What demo rows this account is carrying, for the banner that offers to
    remove them. Counts the two things a person actually notices sitting in
    their real setup: seeded leads and the two fake phone numbers.

    Deliberately cheap. This runs on every load of the Calling page, so it
    counts rather than fetching, and it asks only the two tables worth asking
    about rather than all nine that clear_demo touches.
    """
    from dialer.models import PhoneNumber
    leads = Lead.query.filter(
        Lead.owner_id == account_id,
        Lead.tags.ilike(f"%{DEMO_TAG}%")).count()
    numbers = PhoneNumber.query.filter(
        PhoneNumber.account_id == account_id,
        PhoneNumber.friendly_name.like(DEMO_PREFIX + "%")).count()
    return {"leads": leads, "numbers": numbers, "any": bool(leads or numbers)}


def clear_demo(account_id):
    """Remove every demo row on this account and nothing else.

    Matching is by the `demo-dial` tag on leads and the "Demo: " prefix on the
    objects the seeder names. A row that fails both tests is somebody's real
    data and is left exactly where it is.
    """
    lead_ids = [r.id for r in Lead.query.filter(
        Lead.owner_id == account_id,
        Lead.tags.ilike(f"%{DEMO_TAG}%")).all()]
    camp_ids = [r.id for r in Campaign.query.filter(
        Campaign.account_id == account_id,
        Campaign.name.like(DEMO_PREFIX + "%")).all()]

    deleted = {"leads": len(lead_ids), "campaigns": len(camp_ids), "calls": 0,
               "notes": 0, "tasks": 0, "agents": 0, "playbooks": 0,
               "numbers": 0, "voicemail_drops": 0}

    conds = []
    if lead_ids:
        conds.append(Call.lead_id.in_(lead_ids))
    if camp_ids:
        conds.append(Call.campaign_id.in_(camp_ids))
    calls = (Call.query.filter(Call.account_id == account_id)
             .filter(db.or_(*conds)).all()) if conds else []
    call_ids = [c.id for c in calls]
    deleted["calls"] = len(call_ids)

    _drop_webhooks(account_id, calls)
    if call_ids:
        CallEvent.query.filter(CallEvent.call_id.in_(call_ids)).delete(
            synchronize_session=False)
        Call.query.filter(Call.id.in_(call_ids)).delete(
            synchronize_session=False)

    q_conds = []
    if camp_ids:
        q_conds.append(CampaignLead.campaign_id.in_(camp_ids))
    if lead_ids:
        q_conds.append(CampaignLead.lead_id.in_(lead_ids))
    if q_conds:
        (CampaignLead.query.filter(CampaignLead.account_id == account_id)
         .filter(db.or_(*q_conds)).delete(synchronize_session=False))
    if camp_ids:
        Campaign.query.filter(Campaign.id.in_(camp_ids)).delete(
            synchronize_session=False)

    if lead_ids:
        deleted["notes"] = Note.query.filter(
            Note.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        deleted["tasks"] = Task.query.filter(
            Task.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        (Suppression.query
         .filter(Suppression.account_id == account_id,
                 Suppression.lead_id.in_(lead_ids))
         .delete(synchronize_session=False))
        (ConsentRecord.query
         .filter(ConsentRecord.account_id == account_id,
                 ConsentRecord.lead_id.in_(lead_ids))
         .delete(synchronize_session=False))
        Lead.query.filter(Lead.id.in_(lead_ids)).delete(
            synchronize_session=False)

    deleted["agents"] = (AiAgent.query.filter(
        AiAgent.account_id == account_id,
        AiAgent.name.like(DEMO_PREFIX + "%")).delete(synchronize_session=False))
    deleted["playbooks"] = (Playbook.query.filter(
        Playbook.account_id == account_id,
        Playbook.name.like(DEMO_PREFIX + "%")).delete(synchronize_session=False))
    deleted["voicemail_drops"] = (VoicemailDrop.query.filter(
        VoicemailDrop.account_id == account_id,
        VoicemailDrop.name.like(DEMO_PREFIX + "%"))
        .delete(synchronize_session=False))
    deleted["numbers"] = (PhoneNumber.query.filter(
        PhoneNumber.account_id == account_id,
        PhoneNumber.friendly_name.like(DEMO_PREFIX + "%"))
        .delete(synchronize_session=False))

    db.session.commit()
    return deleted


def _drop_webhooks(account_id, calls):
    """The simulator's inbox rows are keyed off the call's carrier sid, so they
    can be removed precisely instead of by clearing the account's inbox -- which
    would throw away a real pending webhook sitting beside them."""
    keys = []
    for c in calls:
        if c.twilio_sid:
            keys.append(WebhookInbox.dedupe_key.like(f"{c.twilio_sid}:%"))
        if c.elevenlabs_conversation_id:
            keys.append(WebhookInbox.dedupe_key.like(
                f"el:{c.elevenlabs_conversation_id}:%"))
    if not keys:
        return 0
    return (WebhookInbox.query
            .filter(WebhookInbox.account_id == account_id)
            .filter(db.or_(*keys)).delete(synchronize_session=False))
