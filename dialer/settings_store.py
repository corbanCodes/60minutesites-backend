"""Get-or-create the per-account settings row, plus the account helpers the
blueprints lean on."""
from app import User, current_user, db

from dialer.models import DialerSettings


def current_account_id():
    """The User.id that owns the data for whoever is logged in. Corban's admin
    session has no User row; he operates on account 0, which keeps his own
    dialer data separate from every customer's."""
    role, user = current_user()
    if role == "admin":
        return 0
    if user is None:
        return None
    return user.account_id or user.id


def current_member():
    """The User row acting, or None for the platform admin session."""
    return current_user()[1]


def account_owner(account_id):
    if not account_id:
        return None
    return db.session.get(User, account_id)


def get_settings(account_id=None, create=True):
    account_id = current_account_id() if account_id is None else account_id
    if account_id is None:
        return None
    row = DialerSettings.query.filter_by(account_id=account_id).first()
    if row is None and create:
        row = DialerSettings(account_id=account_id)
        db.session.add(row)
        db.session.commit()
    return row


def dialer_enabled(account_id=None):
    """Admin always has it; a customer account needs the flag."""
    role, user = current_user()
    if role == "admin":
        return True
    if user is None:
        return False
    owner = account_owner(user.account_id or user.id)
    return bool(owner and owner.feature_dialer)


def teams_enabled(account_id=None):
    role, user = current_user()
    if role == "admin":
        return True
    if user is None:
        return False
    owner = account_owner(user.account_id or user.id)
    return bool(owner and owner.feature_multi_user)
