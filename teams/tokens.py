"""Signed invite links. The token carries only the invitation row id; the row
is what makes it single-use and revocable."""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SALT = "60ms-team-invite"


def _serializer():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.secret_key, salt=SALT)


def make(invite_id):
    return _serializer().dumps({"i": int(invite_id)})


def read(token, max_age_days=7):
    """-> invitation id, or None."""
    try:
        data = _serializer().loads(token, max_age=max_age_days * 86400)
        return int(data["i"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
