"""Recording a voicemail drop, and the several ways it used to go quiet.

Everything here is a real failure from one sitting on step 10:

* A take was recorded and saved and did not appear. The name field was
  `required` and empty, so the browser blocked the submit behind a native
  tooltip and the recording was lost.
* The play button on the listed message did nothing. That row is the sample,
  which has never had audio behind it -- only wording to copy.
* There was no way to choose which message a rep actually drops.
* A microphone recording was stored as video/webm, which an <audio> element
  refuses to play.

And one nobody had hit yet, which is the worst of them: a drop with no audio
still marked the call as "voicemail dropped", so a rep would move on believing
they had left a message that was never played.
"""
import io

import pytest

from app import Media, db
from dialer.models import Call, Campaign, VoicemailDrop
from dialer.settings_store import get_settings
from tests.conftest import make_user


@pytest.fixture
def account(ctx, client):
    owner = make_user(name="Napkin", email="o@n.test", dialer=True, seats=5)
    get_settings(owner.id)
    db.session.commit()
    client.post("/login", data={"email": "o@n.test", "password": "pw123456"})
    return owner, client


def upload(client, name="", filename="rec.webm", mimetype="video/webm"):
    return client.post("/dialer/voicemail/new", follow_redirects=True,
                       content_type="multipart/form-data",
                       data={"name": name,
                             "audio": (io.BytesIO(b"RIFFfake-audio"), filename,
                                       mimetype)})


def script_only(owner_id, name="Demo: 20-second napkin drop", default=False):
    """The sample row: wording, no recording."""
    d = VoicemailDrop(account_id=owner_id, name=name, media_id=None,
                      mimetype="audio/wav", duration_s=19.4,
                      is_default=default, transcript="Hi, this is...")
    db.session.add(d)
    db.session.commit()
    return d


# --------------------------------------------------------------- saving
def test_a_recording_saves_with_no_name_at_all(account):
    """The one that lost his take. The name was required and nothing said so."""
    owner, client = account
    upload(client, name="")
    drops = VoicemailDrop.query.filter_by(account_id=owner.id).all()
    assert len(drops) == 1
    assert drops[0].name
    assert drops[0].media_id


def test_unnamed_recordings_stay_tellable_apart(account):
    owner, client = account
    upload(client, name="")
    upload(client, name="")
    names = [d.name for d in VoicemailDrop.query.filter_by(account_id=owner.id)]
    assert len(set(names)) == 2


def test_a_microphone_recording_is_stored_as_audio(account):
    """Browsers hand back video/webm for a mic capture and an <audio> element
    will not play a video type, so it saved and would not play back."""
    owner, client = account
    upload(client, mimetype="video/webm")
    media = Media.query.first()
    assert media.mimetype.startswith("audio/")


def test_the_save_button_starts_disabled(account):
    """It used to be enabled, with a required name field as the only thing
    standing between a user and an empty submit."""
    owner, client = account
    body = client.get("/dialer/setup/10").get_data(as_text=True)
    assert 'id="vm-save"' in body
    assert "disabled" in body.split('id="vm-save"')[1][:120]


def test_the_name_is_advertised_as_optional(account):
    owner, client = account
    assert "(optional)" in client.get("/dialer/setup/10").get_data(as_text=True)


# ------------------------------------------------- the sample with no audio
def test_a_script_only_row_offers_no_dead_player(account):
    owner, client = account
    script_only(owner.id)
    body = client.get("/dialer/setup/10").get_data(as_text=True)
    assert "Script only, no audio" in body
    assert "Nothing to play" in body
    assert "/dialer/vm/" not in body, "a player that cannot play is worse than none"


def test_a_real_recording_does_get_a_player(account):
    owner, client = account
    upload(client, name="Mine")
    body = client.get("/dialer/setup/10").get_data(as_text=True)
    assert "/dialer/vm/" in body


def test_a_script_only_row_never_becomes_the_default(account):
    """It cannot be played, so a rep pressing drop would send silence."""
    owner, client = account
    script_only(owner.id)
    upload(client, name="Mine")
    mine = VoicemailDrop.query.filter_by(account_id=owner.id).filter(
        VoicemailDrop.media_id.isnot(None)).first()
    assert mine.is_default is True


# ------------------------------------------------------- choosing which one
def test_you_can_choose_which_message_reps_drop(account):
    owner, client = account
    upload(client, name="First")
    upload(client, name="Second")
    second = VoicemailDrop.query.filter_by(account_id=owner.id,
                                           name="Second").first()
    client.post(f"/dialer/voicemail/{second.id}/default", follow_redirects=True)
    rows = {d.name: d.is_default
            for d in VoicemailDrop.query.filter_by(account_id=owner.id)}
    assert rows == {"First": False, "Second": True}


def test_a_silent_message_cannot_be_made_the_default(account):
    owner, client = account
    upload(client, name="Real")
    sample = script_only(owner.id)
    r = client.post(f"/dialer/voicemail/{sample.id}/default",
                    follow_redirects=True)
    assert "cannot be the default" in r.get_data(as_text=True)
    assert db.session.get(VoicemailDrop, sample.id).is_default is False


def test_choosing_a_default_cannot_reach_another_account(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="x@n.test", dialer=True)
    theirs = VoicemailDrop(account_id=other.id, name="Theirs", media_id=1)
    db.session.add(theirs)
    db.session.commit()
    assert client.post(f"/dialer/voicemail/{theirs.id}/default").status_code == 403


# -------------------------------------- never claim a drop that never played
def test_a_call_is_not_marked_dropped_when_there_is_no_audio(account):
    """The dangerous one. The rep moves on believing a message was left, the
    lead never hears one, and the follow-up is booked against a conversation
    that did not happen."""
    from dialer.routes_hooks import _drop_twiml
    owner, _ = account
    sample = script_only(owner.id, default=True)
    camp = Campaign(account_id=owner.id, name="C", voicemail_drop_id=sample.id)
    db.session.add(camp)
    db.session.flush()
    call = Call(account_id=owner.id, campaign_id=camp.id, to_number="+18655551234")
    db.session.add(call)
    db.session.commit()

    twiml = _drop_twiml(call)

    assert "<Play>" not in twiml
    assert db.session.get(Call, call.id).voicemail_dropped is not True
    assert "no audio" in (db.session.get(Call, call.id).error or "")


def test_a_call_with_real_audio_is_marked_dropped(account):
    from dialer.routes_hooks import _drop_twiml
    owner, client = account
    upload(client, name="Real")
    drop = VoicemailDrop.query.filter_by(account_id=owner.id).first()
    camp = Campaign(account_id=owner.id, name="C", voicemail_drop_id=drop.id)
    db.session.add(camp)
    db.session.flush()
    call = Call(account_id=owner.id, campaign_id=camp.id, to_number="+18655551234")
    db.session.add(call)
    db.session.commit()

    twiml = _drop_twiml(call)

    assert "<Play>" in twiml
    assert db.session.get(Call, call.id).voicemail_dropped is True


# ------------------------------------------------- exactly one default
def test_two_messages_never_both_claim_the_default(account):
    """Both rows read "Reps drop this one", which is not cosmetic: the
    campaign takes whichever the query returns first, so the label stops
    predicting what will actually play."""
    owner, client = account
    a = script_only(owner.id, name="Sample", default=True)   # shipped default
    upload(client, name="Mine")                               # also claimed it

    client.get("/dialer/setup/10")                            # repairs on sight

    flagged = [d.name for d in VoicemailDrop.query.filter_by(
        account_id=owner.id, is_default=True)]
    assert flagged == ["Mine"]


def test_the_default_moves_off_a_message_that_cannot_play(account):
    owner, client = account
    sample = script_only(owner.id, default=True)
    upload(client, name="Real")
    client.get("/dialer/setup/10")
    assert db.session.get(VoicemailDrop, sample.id).is_default is False


def test_a_lone_script_only_message_is_left_alone(account):
    """Nothing playable to move the default to, so do not invent one."""
    owner, client = account
    sample = script_only(owner.id, default=True)
    client.get("/dialer/setup/10")
    assert db.session.get(VoicemailDrop, sample.id).is_default is False


# ------------------------------------------------------------- length
def test_a_recording_gets_its_length_from_the_file(account):
    """The row showed a dash next to a player that knew the length perfectly
    well, because nothing ever set duration_s."""
    import struct
    owner, client = account
    rate, seconds = 8000, 2
    frames = b"\x00\x00" * (rate * seconds)
    wav = (b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt "
           + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
           + b"data" + struct.pack("<I", len(frames)) + frames)
    client.post("/dialer/voicemail/new", follow_redirects=True,
                content_type="multipart/form-data",
                data={"name": "Two seconds",
                      "audio": (io.BytesIO(wav), "rec.wav", "audio/wav")})
    drop = VoicemailDrop.query.filter_by(account_id=owner.id).first()
    assert drop.duration_s == pytest.approx(2.0, abs=0.2)


def test_an_unreadable_file_reports_no_length_rather_than_a_wrong_one(account):
    owner, client = account
    upload(client, name="mp3 maybe", filename="x.mp3", mimetype="audio/mpeg")
    assert VoicemailDrop.query.filter_by(account_id=owner.id).first().duration_s is None


# ----------------------------------------------- hearing the written sample
def test_the_written_sample_can_be_read_aloud(account):
    """It was a wall of text with no way to hear it. Now it speaks, in the
    AI voice, and saves as its own message you can choose."""
    owner, client = account
    sample = script_only(owner.id)
    client.post(f"/dialer/voicemail/{sample.id}/speak", follow_redirects=True)
    spoken = [d for d in VoicemailDrop.query.filter_by(account_id=owner.id)
              if d.name.startswith("AI voice:")]
    assert len(spoken) == 1
    assert spoken[0].media_id, "it has to be playable or it changed nothing"


def test_the_spoken_copy_does_not_steal_the_default(account):
    """Reading a sample aloud is a preview, not a decision."""
    owner, client = account
    upload(client, name="Mine")
    sample = script_only(owner.id)
    client.post(f"/dialer/voicemail/{sample.id}/speak", follow_redirects=True)
    assert db.session.get(VoicemailDrop,
                          VoicemailDrop.query.filter_by(
                              account_id=owner.id, name="Mine").first().id
                          ).is_default is True


def test_speaking_needs_something_to_say(account):
    owner, client = account
    empty = VoicemailDrop(account_id=owner.id, name="No words", transcript="")
    db.session.add(empty)
    db.session.commit()
    r = client.post(f"/dialer/voicemail/{empty.id}/speak", follow_redirects=True)
    assert "no wording" in r.get_data(as_text=True)


def test_speaking_cannot_reach_another_account(account, ctx):
    owner, client = account
    other = make_user(name="Else", email="y@n.test", dialer=True)
    theirs = VoicemailDrop(account_id=other.id, name="Theirs", transcript="hi")
    db.session.add(theirs)
    db.session.commit()
    assert client.post(f"/dialer/voicemail/{theirs.id}/speak").status_code == 403


# ------------------------------------------------------- the sample wording
def test_the_sample_message_names_nobody(account):
    """One recording reaches every lead, so a name in it is wrong for all but
    one of them."""
    owner, client = account
    body = client.get("/dialer/setup/10").get_data(as_text=True)
    sample = body[body.index("A message that works"):]
    sample = sample[:sample.index("</blockquote>")]
    assert "calling for" not in sample
    assert "Dana" not in sample


def test_the_page_says_to_keep_the_message_general(account):
    owner, client = account
    body = client.get("/dialer/setup/10").get_data(as_text=True)
    assert "Say no names but your own" in body
