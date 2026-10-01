"""Multi-user accounts: seats, roles, invites. Mounted at /admin/team."""
from flask import Blueprint, abort, g, redirect, request, url_for

bp = Blueprint("teams", __name__, url_prefix="/admin/team")


@bp.before_request
def _guard():
    from app import current_user
    from dialer.settings_store import current_account_id, teams_enabled
    role, user = current_user()
    if not role:
        return redirect(url_for("login", next=request.path))
    if not teams_enabled():
        abort(404)
    g.account_id = current_account_id()
    g.member = user
    return None


def init_app(app):
    from teams import models  # noqa: F401  (declares the tables)
    from teams import routes  # noqa: F401
    app.register_blueprint(bp)
    # /join/<token> lives outside the guarded blueprint: an invitee has no
    # session yet and the account's flag is irrelevant to accepting a seat.
    app.add_url_rule("/join/<token>", "join_invite", routes.join_invite,
                     methods=["GET", "POST"])
