"""Seat accounting.

A seat is consumed by an ACTIVE member and by a PENDING invitation. Counting
only members would let two admins invite simultaneously and both pass the
check, so every mutation locks the owner row first and counts inside that
transaction.
"""
from datetime import datetime, timedelta, timezone

from app import User, db

from teams.models import Invitation

INVITE_DAYS = 7


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def lock_account(account_id):
    """SELECT ... FOR UPDATE on the owner row. On SQLite (tests, local dev)
    with_for_update is a no-op, which is fine -- there is one writer."""
    q = User.query.filter_by(id=account_id)
    try:
        return q.with_for_update().first()
    except Exception:
        return q.first()


def members(account_id, include_inactive=True):
    q = User.query.filter(db.or_(User.id == account_id,
                                 User.account_id == account_id))
    if not include_inactive:
        q = q.filter(User.active.isnot(False))
    return q.order_by(User.account_id.is_(None).desc(), User.name).all()


def pending_invites(account_id):
    cutoff = _now()
    return (Invitation.query
            .filter_by(account_id=account_id)
            .filter(Invitation.accepted_at.is_(None),
                    Invitation.cancelled_at.is_(None),
                    Invitation.expires_at > cutoff)
            .order_by(Invitation.created_at.desc()).all())


def usage(account_id):
    """-> {limit, used, members, pending, free}"""
    owner = db.session.get(User, account_id)
    limit = (owner.seat_limit or 1) if owner else 1
    active = len(members(account_id, include_inactive=False))
    pending = len(pending_invites(account_id))
    used = active + pending
    return {"limit": limit, "used": used, "members": active, "pending": pending,
            "free": max(0, limit - used), "full": used >= limit}


FULL_MESSAGE = ("You've reached your account limit of {limit} seats. "
                "Contact your admin (60 Minute Sites) to add more.")


def can_add(account_id):
    """-> (ok, message). The message is the exact copy the product promises."""
    u = usage(account_id)
    if u["full"]:
        return False, FULL_MESSAGE.format(limit=u["limit"])
    return True, ""


def new_expiry():
    return _now() + timedelta(days=INVITE_DAYS)
