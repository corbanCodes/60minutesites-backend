"""Per-account vendor-key encryption.

Keys are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). We use
MultiFernet so a key rotation is: prepend the new key to FERNET_KEYS, deploy,
run rotate_all(), deploy again without the old key. No schema migration.

If FERNET_KEYS is unset we derive one key from SECRET_KEY, so the module works
on a laptop and on Railway without an extra env var. Setting FERNET_KEYS is
still recommended in production: rotating SECRET_KEY would otherwise make every
stored vendor key unreadable.
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT = b"60ms-dialer-v1"
_cached = None


def _derive(secret):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT,
                     iterations=1_200_000)
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _fernet():
    """MultiFernet over FERNET_KEYS (newest first), else derived from SECRET_KEY."""
    global _cached
    if _cached is not None:
        return _cached
    raw = os.environ.get("FERNET_KEYS", "").strip()
    keys = []
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                keys.append(Fernet(part.encode("utf-8")))
            except Exception:
                # tolerate a passphrase in FERNET_KEYS instead of a real key
                keys.append(Fernet(_derive(part)))
    if not keys:
        secret = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
        keys.append(Fernet(_derive(secret)))
    _cached = MultiFernet(keys)
    return _cached


def reset_cache():
    """Tests change env vars between cases."""
    global _cached
    _cached = None


def encrypt(plaintext):
    """str -> ciphertext str. None/'' round-trips to None so empty stays empty."""
    if plaintext is None or plaintext == "":
        return None
    return _fernet().encrypt(str(plaintext).encode("utf-8")).decode("ascii")


def decrypt(token):
    """ciphertext str -> str, or None if absent/unreadable (never raises)."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, AttributeError):
        return None


def rotate(token):
    """Re-encrypt under the primary key, preserving the original timestamp."""
    if not token:
        return None
    try:
        return _fernet().rotate(token.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        return token


def last4(plaintext):
    """What the UI shows. Never decrypt just to render a field."""
    if not plaintext:
        return ""
    s = str(plaintext)
    return s[-4:] if len(s) >= 4 else s


def mask(last_four):
    return f"••••••••{last_four}" if last_four else ""
