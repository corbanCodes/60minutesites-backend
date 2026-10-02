"""Test harness for a single-file Flask app whose import runs ensure_schema().

The env must be set BEFORE `import app`, so this module does that at import
time rather than in a fixture.  A file-backed SQLite DB, never :memory: --
separate connections would each get their own empty database.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="60ms-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
os.environ["DEMO_PASSWORD"] = "test-demo-pw"
os.environ["DIALER_SIMULATION"] = "1"
os.environ.pop("DIALER_DISABLED", None)
os.environ.pop("DIALER_SIMULATION_FAIL", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("GITHUB_TOKEN", None)
os.environ.pop("RESEND_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
from app import User, db  # noqa: E402

ADMIN_PW = "test-admin-pw"


@pytest.fixture(scope="session")
def flask_app():
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app_module.app


@pytest.fixture(autouse=True)
def _clean_db(flask_app):
    """Each test starts from an empty database with the seeds in place."""
    with flask_app.app_context():
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        from dialer.compliance import seed_state_rules
        seed_state_rules()
        from dialer.providers.fakes import simulator
        simulator().reset()
    yield
    with flask_app.app_context():
        db.session.rollback()


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def ctx(flask_app):
    with flask_app.app_context():
        yield


# ------------------------------------------------------------------ factories
def make_user(name="Owner One", email=None, password="pw123456", role="owner",
              account_id=None, dialer=False, multi=False, seats=None,
              active=True, **kw):
    from werkzeug.security import generate_password_hash
    email = email or f"{name.lower().replace(' ', '.')}@example.com"
    u = User(name=name, email=email, password_hash=generate_password_hash(password),
             role=role, account_id=account_id, active=active,
             feature_dialer=dialer, feature_multi_user=multi, seat_limit=seats, **kw)
    db.session.add(u)
    db.session.commit()
    return u


def make_lead(owner_id=None, name="Dana Vance", phone="(865) 555-1231",
              business="The Tap Room", **kw):
    from app import Lead
    lead = Lead(owner_id=owner_id, name=name, phone=phone, business=business, **kw)
    db.session.add(lead)
    db.session.commit()
    from dialer.compliance import enrich_lead
    enrich_lead(lead)
    db.session.commit()
    return lead


def login_admin(client):
    return client.post("/login", data={"email": "", "password": ADMIN_PW},
                       follow_redirects=False)


def login_user(client, email, password="pw123456"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=False)


@pytest.fixture
def factories():
    return {"user": make_user, "lead": make_lead,
            "login_admin": login_admin, "login_user": login_user}
