"""Enrichment: website research and email personalisation, mounted at /enrich.

Invisible until an account has feature_enrichment. The work itself lives in
enrich.scrape and enrich.personalize and is driven by enrich.jobs; this package
is the blueprint, the guard that decides who may see any of it, and the screens.

The guard mirrors dialer/__init__.py on purpose. Two modules that answer
"whose data is this?" differently is how one customer ends up looking at
another's research, so the rule is written once per module and written the
same way.
"""
from flask import Blueprint, abort, g, redirect, request, url_for

bp = Blueprint("enrich", __name__, url_prefix="/enrich")


def current_account_id():
    """The User.id that owns the enrichment data for whoever is logged in.

    Corban's admin session has no User row; he operates on account 0, which
    keeps his own scraped sites and saved prompts out of every customer's.
    Identical to dialer.settings_store.current_account_id -- a login must
    resolve to the same account number in every module or the add-ons start
    disagreeing about who is paying.
    """
    from app import current_user
    role, user = current_user()
    if role == "admin":
        return 0
    if user is None:
        return None
    return user.account_id or user.id


def enrichment_enabled():
    """Admin always has it; a customer account needs the add-on flag set on
    the account owner, not on the seat, so a member inherits the account's
    purchase instead of needing their own."""
    from app import User, current_user, db
    role, user = current_user()
    if role == "admin":
        return True
    if user is None:
        return False
    owner = db.session.get(User, user.account_id or user.id)
    return bool(owner and owner.feature_enrichment)


@bp.before_request
def _guard():
    from app import current_user
    role, user = current_user()
    if not role:
        return redirect(url_for("login", next=request.path))
    if not enrichment_enabled():
        # 404, not 403: an account without the add-on should not learn that
        # there is a feature here to ask about from a permission error.
        abort(404)
    g.account_id = current_account_id()
    g.member = user
    return None


def init_app(app):
    """Declare the tables, register the routes, mount the blueprint.

    app.py calls this once at start-up. Importing enrich.models here rather
    than at module scope keeps `import enrich` free of a circular import back
    into app, which is what lets the guard above import app lazily too.
    """
    from enrich import models  # noqa: F401  (declares the tables)
    from enrich import routes  # noqa: F401  (registers the routes)
    app.register_blueprint(bp)
