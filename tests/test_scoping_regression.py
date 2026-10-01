"""The five helpers in app.py that teams rewired are the ones that decide who
sees whose data. These tests pin today's behaviour for a solo account and the
platform admin, so a future change to seats can never silently widen access.
"""
from app import Lead, Task, User, db
from tests.conftest import ADMIN_PW, make_lead, make_user


def test_solo_customer_sees_only_their_own_leads(ctx, client):
    a = make_user(name="Alpha Co", email="a@x.com", password="pw123456")
    b = make_user(name="Beta Co", email="b@x.com", password="pw123456")
    for i in range(3):
        make_lead(owner_id=a.id, name=f"A lead {i}", phone=f"865555100{i}")
    make_lead(owner_id=b.id, name="B lead", phone="8655552001")
    make_lead(owner_id=None, name="Corban lead", phone="8655553001")

    client.post("/login", data={"email": "a@x.com", "password": "pw123456"})
    body = client.get("/admin/crm").get_data(as_text=True)
    assert "A lead 0" in body and "A lead 2" in body
    assert "B lead" not in body
    assert "Corban lead" not in body


def test_admin_default_scope_is_still_only_corbans_own_leads(ctx, client):
    cust = make_user(name="Cust", email="c@x.com")
    make_lead(owner_id=None, name="Mine", phone="8655554001")
    make_lead(owner_id=cust.id, name="Theirs", phone="8655554002")
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    body = client.get("/admin/crm").get_data(as_text=True)
    assert "Mine" in body
    assert "Theirs" not in body
    assert "Theirs" in client.get("/admin/crm?scope=all").get_data(as_text=True)


def test_account_owner_id_identity_for_solo_users(ctx):
    from app import account_owner_id
    solo = make_user(name="Solo", email="solo@x.com")
    assert account_owner_id(solo) == solo.id
    member = make_user(name="Member", email="m@x.com", role="agent",
                       account_id=solo.id)
    assert account_owner_id(member) == solo.id
    assert account_owner_id(None) is None


def test_member_reads_and_writes_the_owners_leads(ctx, client):
    owner = make_user(name="Owner", email="o@x.com", multi=True, seats=5)
    make_user(name="Rep", email="rep@x.com", role="agent", account_id=owner.id)
    lead = make_lead(owner_id=owner.id, name="Shared Lead", phone="8655555001")

    client.post("/login", data={"email": "rep@x.com", "password": "pw123456"})
    assert "Shared Lead" in client.get("/admin/crm").get_data(as_text=True)
    r = client.post(f"/admin/crm/{lead.id}",
                    data={"action": "note", "body": "Rep called them"},
                    follow_redirects=True)
    assert r.status_code == 200
    from app import Note
    assert Note.query.filter_by(lead_id=lead.id).count() == 1


def test_member_cannot_reach_another_accounts_lead(ctx, client):
    owner = make_user(name="Owner", email="o2@x.com", multi=True, seats=5)
    make_user(name="Rep", email="rep2@x.com", role="agent", account_id=owner.id)
    other = make_user(name="Other", email="other@x.com")
    foreign = make_lead(owner_id=other.id, name="Not Yours", phone="8655556001")
    client.post("/login", data={"email": "rep2@x.com", "password": "pw123456"})
    assert client.get(f"/admin/crm/{foreign.id}").status_code == 403


def test_tasks_stay_personal_on_a_solo_account(ctx, client):
    owner = make_user(name="Solo2", email="s2@x.com")
    db.session.add(Task(owner_id=owner.id, title="My task"))
    db.session.commit()
    client.post("/login", data={"email": "s2@x.com", "password": "pw123456"})
    assert "My task" in client.get("/admin/tasks").get_data(as_text=True)


def test_member_sees_only_tasks_assigned_to_them(ctx, client):
    owner = make_user(name="Owner3", email="o3@x.com", multi=True, seats=5)
    rep = make_user(name="Rep3", email="rep3@x.com", role="agent",
                    account_id=owner.id)
    db.session.add_all([
        Task(owner_id=owner.id, title="Owner only", assignee_id=None),
        Task(owner_id=owner.id, title="Rep job", assignee_id=rep.id),
    ])
    db.session.commit()

    client.post("/login", data={"email": "rep3@x.com", "password": "pw123456"})
    body = client.get("/admin/tasks").get_data(as_text=True)
    assert "Rep job" in body
    assert "Owner only" not in body

    client.get("/logout")
    client.post("/login", data={"email": "o3@x.com", "password": "pw123456"})
    owner_body = client.get("/admin/tasks").get_data(as_text=True)
    assert "Owner only" in owner_body
    assert "Rep job" not in owner_body   # assigned away, off the owner's day


def test_deactivated_member_cannot_log_in(ctx, client):
    owner = make_user(name="Owner4", email="o4@x.com", multi=True, seats=5)
    make_user(name="Gone", email="gone@x.com", role="agent",
              account_id=owner.id, active=False)
    r = client.post("/login", data={"email": "gone@x.com", "password": "pw123456"},
                    follow_redirects=True)
    assert "deactivated" in r.get_data(as_text=True).lower()
    assert client.get("/admin/crm").status_code in (302, 308)


def test_login_stamps_last_login(ctx, client):
    u = make_user(name="Stamp", email="stamp@x.com")
    assert u.last_login_at is None
    client.post("/login", data={"email": "stamp@x.com", "password": "pw123456"})
    assert db.session.get(User, u.id).last_login_at is not None
