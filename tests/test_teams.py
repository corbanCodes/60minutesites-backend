"""Seats, invitations and the role matrix."""
import pytest

from app import User, db
from teams import perms, seats, tokens
from teams.models import AuditLog, Invitation
from tests.conftest import make_lead, make_user


@pytest.fixture
def account(ctx):
    owner = make_user(name="Napkin Co", email="owner@napkin.test",
                      multi=True, dialer=True, seats=3)
    return owner


def as_owner(client, email="owner@napkin.test"):
    client.post("/login", data={"email": email, "password": "pw123456"})
    return client


# ------------------------------------------------------------------ the page
def test_team_page_404s_without_the_feature(ctx, client):
    make_user(name="No Teams", email="not@x.com", multi=False)
    client.post("/login", data={"email": "not@x.com", "password": "pw123456"})
    assert client.get("/admin/team/").status_code == 404


def test_team_page_renders_with_seats_and_matrix(account, client):
    as_owner(client)
    body = client.get("/admin/team/").get_data(as_text=True)
    assert "1 of 3 seats" in body
    assert "Send invitation" in body
    for label in ("Admin", "Manager", "Agent", "Viewer"):
        assert label in body


# ------------------------------------------------------------------ invites
def test_invite_creates_a_pending_row_and_consumes_a_seat(account, client):
    as_owner(client)
    client.post("/admin/team/invite",
                data={"email": "rep@napkin.test", "role": "agent"},
                follow_redirects=True)
    inv = Invitation.query.filter_by(email="rep@napkin.test").first()
    assert inv is not None and inv.state == "pending"
    u = seats.usage(account.id)
    assert u["pending"] == 1 and u["used"] == 2 and u["free"] == 1


def test_seat_limit_message_is_exactly_the_promised_copy(account, client):
    as_owner(client)
    for i in range(2):                       # owner + 2 invites == 3 seats
        client.post("/admin/team/invite",
                    data={"email": f"r{i}@napkin.test", "role": "agent"},
                    follow_redirects=True)
    r = client.post("/admin/team/invite",
                    data={"email": "toomany@napkin.test", "role": "agent"},
                    follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "You&#39;ve reached your account limit of 3 seats." in body \
        or "You've reached your account limit of 3 seats." in body
    assert "Contact your admin (60 Minute Sites) to add more." in body
    assert Invitation.query.filter_by(email="toomany@napkin.test").count() == 0


def test_cancelling_an_invite_frees_the_seat(account, client):
    as_owner(client)
    client.post("/admin/team/invite",
                data={"email": "x@napkin.test", "role": "agent"},
                follow_redirects=True)
    inv = Invitation.query.filter_by(email="x@napkin.test").first()
    assert seats.usage(account.id)["free"] == 1
    client.post(f"/admin/team/invite/{inv.id}/cancel", follow_redirects=True)
    assert seats.usage(account.id)["free"] == 2


def test_accepting_an_invite_creates_an_active_member(account, client):
    as_owner(client)
    client.post("/admin/team/invite",
                data={"email": "newrep@napkin.test", "name": "New Rep",
                      "role": "manager"}, follow_redirects=True)
    inv = Invitation.query.filter_by(email="newrep@napkin.test").first()
    token = tokens.make(inv.id)

    client.get("/logout")
    assert client.get(f"/join/{token}").status_code == 200
    r = client.post(f"/join/{token}",
                    data={"name": "New Rep", "password": "newpw123"},
                    follow_redirects=True)
    assert r.status_code == 200
    member = User.query.filter_by(email="newrep@napkin.test").first()
    assert member is not None
    assert member.account_id == account.id
    assert member.role == "manager" and member.active is True
    assert db.session.get(Invitation, inv.id).state == "accepted"


def test_an_invite_token_only_works_once(account, client):
    as_owner(client)
    client.post("/admin/team/invite",
                data={"email": "once@napkin.test", "role": "agent"},
                follow_redirects=True)
    inv = Invitation.query.filter_by(email="once@napkin.test").first()
    token = tokens.make(inv.id)
    client.get("/logout")
    client.post(f"/join/{token}", data={"name": "A", "password": "pw123456"})
    r = client.get(f"/join/{token}")
    assert r.status_code == 400
    assert "already been used" in r.get_data(as_text=True)


def test_a_tampered_token_is_rejected(account, client):
    r = client.get("/join/not-a-real-token")
    assert r.status_code == 400
    assert "isn&#39;t valid" in r.get_data(as_text=True) \
        or "isn't valid" in r.get_data(as_text=True)


def test_cancelled_invite_cannot_be_accepted(account, client):
    as_owner(client)
    client.post("/admin/team/invite",
                data={"email": "nope@napkin.test", "role": "agent"},
                follow_redirects=True)
    inv = Invitation.query.filter_by(email="nope@napkin.test").first()
    token = tokens.make(inv.id)
    client.post(f"/admin/team/invite/{inv.id}/cancel", follow_redirects=True)
    client.get("/logout")
    assert client.get(f"/join/{token}").status_code == 400


def test_invite_is_refused_for_an_existing_login(account, client):
    make_user(name="Taken", email="taken@elsewhere.test")
    as_owner(client)
    r = client.post("/admin/team/invite",
                    data={"email": "taken@elsewhere.test", "role": "agent"},
                    follow_redirects=True)
    assert "already has a 60 Minute Sites login" in r.get_data(as_text=True)


def test_cannot_invite_a_second_owner(account, client):
    as_owner(client)
    r = client.post("/admin/team/invite",
                    data={"email": "owner2@napkin.test", "role": "owner"},
                    follow_redirects=True)
    assert "only be one owner" in r.get_data(as_text=True)


# -------------------------------------------------------------- memberships
def test_deactivate_frees_a_seat_and_reactivate_takes_it_back(account, client):
    rep = make_user(name="Rep", email="rep@napkin.test", role="agent",
                    account_id=account.id)
    as_owner(client)
    assert seats.usage(account.id)["members"] == 2
    client.post(f"/admin/team/member/{rep.id}/deactivate", follow_redirects=True)
    assert db.session.get(User, rep.id).active is False
    assert seats.usage(account.id)["members"] == 1
    client.post(f"/admin/team/member/{rep.id}/reactivate", follow_redirects=True)
    assert db.session.get(User, rep.id).active is True


def test_role_can_be_changed_and_is_audited(account, client):
    rep = make_user(name="Rep", email="rep@napkin.test", role="agent",
                    account_id=account.id)
    as_owner(client)
    client.post(f"/admin/team/member/{rep.id}/role", data={"role": "manager"},
                follow_redirects=True)
    assert db.session.get(User, rep.id).role == "manager"
    row = AuditLog.query.filter_by(action="team.role_change").first()
    assert row and "agent -> manager" in row.detail


def test_a_member_cannot_reach_the_team_page(account, client):
    make_user(name="Rep", email="rep@napkin.test", role="agent",
              account_id=account.id)
    client.post("/login", data={"email": "rep@napkin.test", "password": "pw123456"})
    r = client.get("/admin/team/")
    assert r.status_code == 403
    assert "role doesn" in r.get_data(as_text=True).lower()


def test_an_admin_member_cannot_touch_the_owner(account, client):
    admin = make_user(name="Admin", email="adm@napkin.test", role="admin",
                      account_id=account.id)
    client.post("/login", data={"email": "adm@napkin.test", "password": "pw123456"})
    r = client.post(f"/admin/team/member/{account.id}/deactivate",
                    follow_redirects=True)
    assert "Only the account owner" in r.get_data(as_text=True)
    assert db.session.get(User, account.id).active is not False


def test_you_cannot_demote_yourself(account, client):
    admin = make_user(name="Admin", email="adm@napkin.test", role="admin",
                      account_id=account.id)
    client.post("/login", data={"email": "adm@napkin.test", "password": "pw123456"})
    r = client.post(f"/admin/team/member/{admin.id}/role",
                    data={"role": "viewer"}, follow_redirects=True)
    assert "can&#39;t change your own access" in r.get_data(as_text=True) \
        or "can't change your own access" in r.get_data(as_text=True)
    assert db.session.get(User, admin.id).role == "admin"


# ------------------------------------------------------------ the role matrix
EXPECTED = {
    "leads.delete":      {"owner", "admin"},
    "leads.export":      {"owner", "admin", "manager"},
    "calls.make":        {"owner", "admin", "manager", "agent"},
    "dialer.keys":       {"owner", "admin"},
    "compliance.override": {"owner", "admin"},
    "team.manage":       {"owner", "admin"},
    "campaigns.manage":  {"owner", "admin", "manager"},
    "coaching.monitor":  {"owner", "admin", "manager"},
    "recordings.download": {"owner", "admin"},
}


@pytest.mark.parametrize("perm,allowed", sorted(EXPECTED.items()))
def test_role_matrix(ctx, perm, allowed):
    for role in perms.ROLES:
        got = perms.scope_for(role, perm) != "none"
        assert got is (role in allowed), f"{role} / {perm}"


def test_agent_sees_only_their_own_recordings(ctx):
    assert perms.scope_for("agent", "recordings.listen") == "own"
    assert perms.scope_for("manager", "recordings.listen") == "all"
    assert perms.scope_for("viewer", "recordings.listen") == "none"


def test_viewer_can_look_but_not_touch(ctx):
    assert perms.scope_for("viewer", "leads.view") == "all"
    for p in ("leads.edit", "leads.create", "calls.make", "notes.create"):
        assert perms.scope_for("viewer", p) == "none", p


def test_platform_admin_bypasses_everything(ctx):
    assert perms.can(None, "team.remove_owner")
    assert perms.can(None, "dialer.keys")


def test_inactive_user_can_do_nothing(ctx):
    u = make_user(name="Off", email="off@x.com", role="admin", active=False)
    assert perms.can(u, "leads.view") is False
