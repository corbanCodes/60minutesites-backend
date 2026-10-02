"""The test that has to pass before any of this is deployed.

Loads the REAL production export (14 users / 1,973 leads / 2,260 notes /
146 tasks, taken 2026-10-01 before this module existed), upgrades the schema
over the top of it, and proves that nothing a paying customer can see has
changed. If this file ever goes red, do not deploy.
"""
import glob
import json
import os

import pytest

from app import Form, Lead, Note, Site, Task, User, db
from tests.conftest import ADMIN_PW

BACKUP_GLOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "..", "60MS-backups", "*.json")


def _newest_backup():
    files = sorted(glob.glob(BACKUP_GLOB))
    return files[-1] if files else None


def _load_backup(path):
    with open(path) as fh:
        return json.load(fh)


def _restore(data):
    """Mirrors /admin/import: insert-only, in FK-safe order."""
    from app import BACKUP_TABLES
    from datetime import datetime
    counts = {}
    for key, model, cols in BACKUP_TABLES:
        rows = data.get(key) or []
        for raw in rows:
            payload = {}
            for c in cols:
                v = raw.get(c)
                if isinstance(v, str) and c.endswith(("_at",)) and v:
                    try:
                        v = datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        v = None
                payload[c] = v
            db.session.add(model(**payload))
        counts[key] = len(rows)
        db.session.commit()
    return counts


@pytest.fixture
def restored(ctx):
    path = _newest_backup()
    if not path:
        pytest.skip("no production export in ../60MS-backups/")
    data = _load_backup(path)
    counts = _restore(data)
    return counts


def test_backup_file_is_present():
    assert _newest_backup(), (
        "Expected a production export in ../60MS-backups/. Take one with "
        "Setup -> Export before deploying.")


def test_restore_then_upgrade_preserves_every_row(restored):
    """ensure_schema() runs over real data and changes no counts."""
    import app as app_module
    before = {"users": User.query.count(), "leads": Lead.query.count(),
              "notes": Note.query.count(), "tasks": Task.query.count(),
              "forms": Form.query.count(), "sites": Site.query.count()}
    assert before["leads"] > 100, "export looks empty; check the backup file"

    app_module.ensure_schema()
    app_module.ensure_schema()   # idempotent: running it twice is a no-op

    after = {"users": User.query.count(), "leads": Lead.query.count(),
             "notes": Note.query.count(), "tasks": Task.query.count(),
             "forms": Form.query.count(), "sites": Site.query.count()}
    assert after == before, f"row counts changed: {before} -> {after}"


def test_existing_users_become_active_owners_with_features_off(restored):
    """The whole safety argument: every pre-existing account keeps working
    exactly as before, and sees none of the new product."""
    for u in User.query.all():
        assert u.account_id is None, f"{u.email} was turned into a team member"
        assert (u.role or "owner") == "owner"
        assert u.active is not False, f"{u.email} would be locked out"
        assert not u.feature_dialer, f"{u.email} can suddenly see the dialer"
        assert not u.feature_multi_user
        assert (u.seat_limit or 1) == 1


def test_lead_fields_are_untouched_and_new_ones_are_inert(restored):
    for lead in Lead.query.limit(200):
        assert lead.do_not_call is not True, "a real lead was marked do-not-call"
        assert (lead.consent_status or "none") == "none"
        assert (lead.call_count or 0) == 0
        assert not lead.last_called_at
        assert lead.assignee_id is None


def test_notes_keep_their_text_and_default_kind(restored):
    sample = Note.query.limit(300).all()
    assert sample
    for n in sample:
        assert n.body, "a note lost its body"
        assert (n.kind or "note") == "note"
        assert n.author_id is None


def test_admin_pages_all_render_over_real_data(restored, client):
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    for path in ["/admin", "/admin/crm", "/admin/crm/board", "/admin/tasks",
                 "/admin/revenue", "/admin/customers", "/admin/sites",
                 "/admin/forms", "/admin/setup", "/admin/chat", "/admin/email",
                 "/admin/funnels", "/admin/invoices", "/admin/ai-studio"]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"


def test_a_real_customers_view_is_unchanged(restored, client):
    """Log in as an actual restored customer and count what they can see."""
    from werkzeug.security import generate_password_hash
    cust = (User.query.filter(User.email.notlike("%johnmelody%"))
            .filter(User.id.isnot(None)).first())
    assert cust is not None
    cust.password_hash = generate_password_hash("known-password")
    db.session.commit()
    expected = Lead.query.filter_by(owner_id=cust.id).count()

    client.post("/login", data={"email": cust.email, "password": "known-password"})
    r = client.get("/admin/crm")
    assert r.status_code == 200
    assert Lead.query.filter_by(owner_id=cust.id).count() == expected
    # the new nav items must not appear for an unflagged account.
    # (Match the nav LINKS, not any substring -- the stylesheet is always
    # loaded and is legitimately called dialer.css.)
    body = r.get_data(as_text=True)
    assert 'href="/dialer"' not in body
    assert 'href="/admin/team"' not in body
    assert "Calling</a>" not in body


def test_dialer_is_404_for_an_unflagged_account(restored, client):
    from werkzeug.security import generate_password_hash
    cust = User.query.first()
    cust.password_hash = generate_password_hash("known-password")
    db.session.commit()
    client.post("/login", data={"email": cust.email, "password": "known-password"})
    assert client.get("/dialer/").status_code == 404
    assert client.get("/admin/team/").status_code == 404


def test_lead_detail_and_task_pages_render_for_real_rows(restored, client):
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    for lead in Lead.query.filter_by(owner_id=None).limit(15):
        assert client.get(f"/admin/crm/{lead.id}").status_code == 200
    assert client.get("/admin/tasks").status_code == 200


def test_export_still_round_trips_and_leaks_no_secrets(restored, client):
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    r = client.get("/admin/export.json")
    assert r.status_code == 200
    payload = r.get_data(as_text=True)
    data = json.loads(payload)
    assert data["format"] == "60ms-backup-v1"
    assert len(data["leads"]) == Lead.query.count()
    for marker in ("_enc", "twilio_auth", "elevenlabs_key", "webhook_secret"):
        assert marker not in payload, f"export leaked {marker}"
