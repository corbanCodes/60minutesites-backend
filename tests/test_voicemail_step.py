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
