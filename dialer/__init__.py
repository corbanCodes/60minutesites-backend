"""The AI calling module. Mounted at /dialer, invisible until an account has
feature_dialer set. Nothing here runs for an account without the flag."""
import os

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

bp = Blueprint("dialer", __name__, url_prefix="/dialer")


def disabled():
    """A whole-module kill switch that needs no code change: set
    DIALER_DISABLED=1 on the service and every /dialer route 503s, the nav item
    disappears, and the worker idles."""
    return str(os.environ.get("DIALER_DISABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


@bp.before_request
def _guard():
    from app import current_user
    from dialer.settings_store import current_account_id, dialer_enabled
    if disabled():
        return ("<h1>Calling is temporarily switched off</h1>"
                "<p>The AI calling module is disabled on this server. "
                "Everything else in HQ is unaffected.</p>", 503)
    # webhooks authenticate themselves by signature, not by session
    if request.path.startswith("/dialer/hooks/"):
        return None
    role, user = current_user()
    if not role:
        return redirect(url_for("login", next=request.path))
    if not dialer_enabled():
        abort(404)          # not "forbidden" -- the feature does not exist here
    g.account_id = current_account_id()
    g.member = user
    return None


def init_app(app):
    from dialer import models  # noqa: F401  (declares the tables)
    from dialer import routes_hooks, routes_ui  # noqa: F401  (registers routes)
    app.register_blueprint(bp)
    app.register_blueprint(routes_hooks.hooks_bp)
