"""Multi-user account tables. Additive only: nothing here touches existing rows.

Import order note: these modules do `from app import db`, which works because
app.py imports the blueprints at the very bottom, after db and the core models
exist. Always import `app` first (tests/conftest.py does).
"""
from datetime import datetime, timezone

from app import db


def _utcnow():
    return datetime.now(timezone.utc)


class Invitation(db.Model):
    """A pending seat. The emailed token carries only this row's id; the row is
    what makes it single-use and revocable."""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    email = db.Column(db.String(160), nullable=False)
    name = db.Column(db.String(120), default="")
    role = db.Column(db.String(20), default="agent")
    job_title = db.Column(db.String(80), default="")
    invited_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    @property
    def state(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if self.accepted_at:
            return "accepted"
        if self.cancelled_at:
            return "cancelled"
        if self.expires_at and self.expires_at < now:
            return "expired"
        return "pending"

    @property
    def counts_against_seats(self):
        return self.state == "pending"


class AuditLog(db.Model):
    """Who changed what. Written for team changes, key changes, compliance
    overrides and number releases -- the things someone may have to explain."""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=True)
    actor = db.Column(db.String(160), default="")      # readable: name or "platform admin"
    action = db.Column(db.String(60), nullable=False)  # e.g. "team.invite"
    target = db.Column(db.String(160), default="")
    detail = db.Column(db.Text, default="")
    ip = db.Column(db.String(60), default="")
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)


def log(action, target="", detail="", account_id=None, user=None, actor=None, ip=None):
    """Append-only; never raises into the request path."""
    try:
        from flask import has_request_context, request
        if ip is None and has_request_context():
            ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or request.remote_addr or "")
        db.session.add(AuditLog(
            account_id=account_id,
            user_id=getattr(user, "id", None),
            actor=actor or (getattr(user, "name", None) or "platform admin"),
            action=action, target=str(target)[:160], detail=str(detail)[:4000],
            ip=(ip or "")[:60]))
    except Exception:
        pass
