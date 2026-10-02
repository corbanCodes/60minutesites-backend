"""Per-client tool visibility, and the third add-on.

The rule that matters: an account nobody has configured must behave exactly as
it did before any of this existed.
"""
import pytest

from app import TOOLS, TOOLS_ALWAYS_ON, User, db
from tests.conftest import ADMIN_PW, make_user


def nav_labels(client):
    import re
    body = client.get("/admin").get_data(as_text=True)
    return re.findall(r'nav-item[^>]*>(?:<i[^>]*></i>)?([A-Za-z ]+)</a>', body)


def test_an_untouched_account_sees_the_same_tools_as_before(ctx, client):
    u = make_user(name="Legacy", email="legacy@x.com")
    assert u.hidden_tools in ("", None)
    client.post("/login", data={"email": "legacy@x.com", "password": "pw123456"})
    labels = nav_labels(client)
    for expected in ["Dashboard", "CRM", "Tasks", "Sites", "Forms", "Chat",
                     "Funnels", "Invoices", "AI Studio", "Email"]:
        assert expected in labels, f"{expected} vanished for a legacy account"
    # and nothing new appeared
    for new in ["Calling", "Enrichment", "Team"]:
        assert new not in labels


def test_hiding_a_tool_removes_it_from_the_menu_and_blocks_the_page(ctx, client):
    owner = make_user(name="Client", email="c@x.com")
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    client.post(f"/admin/customers/{owner.id}/tools",
                data={"tool": ["dashboard", "crm", "tasks", "sites"]},
                follow_redirects=True)
    db.session.refresh(owner)
    assert "invoices" in owner.hidden and "chat" in owner.hidden

    client.get("/logout")
    client.post("/login", data={"email": "c@x.com", "password": "pw123456"})
    labels = nav_labels(client)
    assert "Invoices" not in labels and "Chat" not in labels
    assert "CRM" in labels and "Sites" in labels
    # hiding is enforced, not decorative
    assert client.get("/admin/invoices").status_code == 404
    assert client.get("/admin/chat").status_code == 404
    assert client.get("/admin/crm").status_code == 200


def test_the_dashboard_can_never_be_taken_away(ctx, client):
    owner = make_user(name="Client", email="c2@x.com")
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    client.post(f"/admin/customers/{owner.id}/tools", data={"tool": []},
                follow_redirects=True)
    db.session.refresh(owner)
    assert "dashboard" not in owner.hidden
    client.get("/logout")
    client.post("/login", data={"email": "c2@x.com", "password": "pw123456"})
    assert client.get("/admin").status_code == 200


def test_hiding_one_clients_tools_does_not_touch_another(ctx, client):
    a = make_user(name="A", email="a@x.com")
    b = make_user(name="B", email="b@x.com")
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    client.post(f"/admin/customers/{a.id}/tools",
                data={"tool": ["dashboard", "crm"]}, follow_redirects=True)
    db.session.refresh(b)
    assert not b.hidden_tools
    client.get("/logout")
    client.post("/login", data={"email": "b@x.com", "password": "pw123456"})
    assert client.get("/admin/invoices").status_code == 200


def test_the_admin_is_never_gated(ctx, client):
    owner = make_user(name="C", email="c3@x.com", )
    owner.hidden_tools = ",".join(k for k, *_ in TOOLS if k not in TOOLS_ALWAYS_ON)
    db.session.commit()
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    for p in ["/admin/crm", "/admin/invoices", "/admin/chat", "/admin/sites"]:
        assert client.get(p).status_code == 200, p


def test_the_enrichment_flag_controls_the_enrichment_menu(ctx, client):
    """Two conditions, both required: the add-on is on AND the code that
    serves it is deployed. A menu item that 404s is worse than a missing one,
    so the nav never advertises a blueprint that is not registered."""
    import app as app_module
    make_user(name="Plain", email="p@x.com")
    rich = make_user(name="Rich", email="r@x.com")
    rich.feature_enrichment = True
    db.session.commit()
    mounted = "enrich" in app_module.app.blueprints

    client.post("/login", data={"email": "p@x.com", "password": "pw123456"})
    assert "Enrichment" not in nav_labels(client), "shown without the add-on"

    client.get("/logout")
    client.post("/login", data={"email": "r@x.com", "password": "pw123456"})
    if mounted:
        assert "Enrichment" in nav_labels(client)
        assert client.get("/enrich").status_code in (200, 302, 308)
    else:
        assert "Enrichment" not in nav_labels(client), (
            "the menu offered a tool whose blueprint is not registered")


def test_the_nav_never_offers_an_unmounted_tool(ctx, client):
    """The general rule, not just for enrichment."""
    import app as app_module
    u = make_user(name="All", email="all@x.com", dialer=True, multi=True,
                  seats=5)
    u.feature_enrichment = True
    db.session.commit()
    client.post("/login", data={"email": "all@x.com", "password": "pw123456"})
    labels = nav_labels(client)
    for key, label, _s, _u, _i, _f in app_module.TOOLS:
        bp = app_module.TOOL_BLUEPRINT.get(key)
        if bp and bp not in app_module.app.blueprints:
            assert label not in labels, f"{label} is offered but {bp} is not mounted"


def test_creating_a_customer_with_the_enrichment_add_on(ctx, client):
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    client.post("/admin/customers",
                data={"name": "New Co", "email": "new@x.com",
                      "feature_enrichment": "on"}, follow_redirects=True)
    u = User.query.filter_by(email="new@x.com").first()
    assert u is not None and u.feature_enrichment is True
    assert u.feature_dialer is not True


def test_members_are_not_listed_as_customers(ctx, client):
    """The Customers page lists accounts, not seats."""
    owner = make_user(name="Owner", email="o@x.com", multi=True, seats=5)
    make_user(name="Member", email="m@x.com", role="agent", account_id=owner.id)
    client.post("/login", data={"email": "", "password": ADMIN_PW})
    body = client.get("/admin/customers").get_data(as_text=True)
    assert "o@x.com" in body
    assert "m@x.com" not in body


def test_a_member_inherits_the_owners_hidden_tools(ctx, client):
    owner = make_user(name="Owner", email="o2@x.com", multi=True, seats=5)
    owner.hidden_tools = "invoices,chat"
    make_user(name="Rep", email="rep2@x.com", role="agent", account_id=owner.id)
    db.session.commit()
    client.post("/login", data={"email": "rep2@x.com", "password": "pw123456"})
    assert client.get("/admin/invoices").status_code == 404
    assert "Invoices" not in nav_labels(client)
