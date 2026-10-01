from flask import Blueprint

hooks_bp = Blueprint("dialer_hooks", __name__, url_prefix="/dialer/hooks")


@hooks_bp.route("/ping")
def ping():
    return "", 204
