"""Launch HQ against the local demo database, in practice mode.

Used for demos and for looking at the dialer without touching anything real.
Port 5077 because 5062 is often already serving the normal dev database, and
5060/5061 are SIP ports Chrome refuses to load.
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DIALER_SIMULATION", "1")
os.environ.setdefault("SECRET_KEY", "demo")
os.environ.setdefault("ADMIN_PASSWORD", "demoadmin")
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE, "instance",
                                                "dialer-demo.db"))

from app import app  # noqa: E402  (env must be set before app imports)

if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5077)))
