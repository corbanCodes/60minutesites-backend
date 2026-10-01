"""Roles and permissions for multi-user accounts.

Modeled as (verb, scope) rather than a flat role enum, following the shape
HubSpot/Close use: every record verb carries a scope (all | own | none) so the
same table can produce BOTH the yes/no check and the SQLAlchemy filter for list
views. One source of truth; no view can forget to scope its query.

Corban's admin session is not a User row and is not covered here -- admin_required
already gates those pages and admin bypasses every check (see `can`).
"""

ROLES = ["owner", "admin", "manager", "agent", "viewer"]

ROLE_LABELS = {
    "owner": "Owner",
    "admin": "Admin",
    "manager": "Manager",
    "agent": "Agent",
    "viewer": "Viewer",
}

ROLE_BLURBS = {
    "owner": "Full control, including API keys and team management. There is exactly one.",
    "admin": "Everything the owner can do except removing the owner.",
    "manager": "Runs the floor: all leads, campaigns, coaching, exports, team reports.",
    "agent": "Makes calls and works their own leads. No exports, no deletes, no settings.",
    "viewer": "Read-only. Sees leads and reports, changes nothing.",
}

# Verbs that carry a scope. Value is the scope each role gets.
#   all  = every record on the account
#   own  = only records assigned to / created by this user
#   none = no access
SCOPED = {
    "leads.view":        {"owner": "all", "admin": "all", "manager": "all", "agent": "all",  "viewer": "all"},
    "leads.edit":        {"owner": "all", "admin": "all", "manager": "all", "agent": "all",  "viewer": "none"},
    "tasks.view":        {"owner": "all", "admin": "all", "manager": "all", "agent": "own",  "viewer": "all"},
    "tasks.edit":        {"owner": "all", "admin": "all", "manager": "all", "agent": "own",  "viewer": "none"},
    "calls.view":        {"owner": "all", "admin": "all", "manager": "all", "agent": "own",  "viewer": "all"},
    "recordings.listen": {"owner": "all", "admin": "all", "manager": "all", "agent": "own",  "viewer": "none"},
    "reports.view":      {"owner": "all", "admin": "all", "manager": "all", "agent": "own",  "viewer": "all"},
}

# Plain on/off verbs.
FLAGS = {
    "leads.create":        {"owner", "admin", "manager", "agent"},
    "leads.delete":        {"owner", "admin"},
    "leads.import":        {"owner", "admin", "manager"},
    "leads.export":        {"owner", "admin", "manager"},
    "notes.create":        {"owner", "admin", "manager", "agent"},
    "tasks.assign":        {"owner", "admin", "manager"},
    "calls.make":          {"owner", "admin", "manager", "agent"},
    "calls.disposition":   {"owner", "admin", "manager", "agent"},
    "recordings.download": {"owner", "admin"},
    "coaching.monitor":    {"owner", "admin", "manager"},
    "campaigns.manage":    {"owner", "admin", "manager"},
    "playbooks.edit":      {"owner", "admin", "manager"},
    "agents.edit":         {"owner", "admin", "manager"},
    "dialer.settings":     {"owner", "admin"},
    "dialer.keys":         {"owner", "admin"},
    "compliance.override": {"owner", "admin"},
    "team.manage":         {"owner", "admin"},
    "team.remove_owner":   {"owner"},
    "build.pages":         {"owner", "admin"},
}

ALL_PERMS = sorted(set(SCOPED) | set(FLAGS))


def normalize_role(role):
    role = (role or "owner").strip().lower()
    return role if role in ROLES else "viewer"


def scope_for(role, perm):
    """'all' | 'own' | 'none' for a scoped verb; 'all'/'none' for a flag."""
    role = normalize_role(role)
    if perm in SCOPED:
        return SCOPED[perm].get(role, "none")
    if perm in FLAGS:
        return "all" if role in FLAGS[perm] else "none"
    return "none"


def can(user_or_role, perm):
    """True if the role may do this at all. Admin session (role string 'admin'
    from current_user()) is handled by the caller -- here `user_or_role` is
    either a User row, a role string, or None (= Corban's admin session)."""
    if user_or_role is None:
        return True  # platform admin
    role = getattr(user_or_role, "role", None) or user_or_role
    if not getattr(user_or_role, "active", True):
        return False
    return scope_for(role, perm) != "none"


def matrix_rows():
    """For the Team page's 'who can do what' table."""
    groups = [
        ("Leads", ["leads.view", "leads.create", "leads.edit", "leads.delete",
                   "leads.import", "leads.export", "notes.create"]),
        ("Tasks", ["tasks.view", "tasks.edit", "tasks.assign"]),
        ("Calling", ["calls.make", "calls.view", "calls.disposition",
                     "recordings.listen", "recordings.download", "coaching.monitor"]),
        ("Setup", ["campaigns.manage", "playbooks.edit", "agents.edit",
                   "dialer.settings", "dialer.keys", "compliance.override"]),
        ("Account", ["reports.view", "team.manage", "build.pages"]),
    ]
    labels = {
        "leads.view": "See leads", "leads.create": "Add leads", "leads.edit": "Edit leads",
        "leads.delete": "Delete leads", "leads.import": "Import CSV", "leads.export": "Export CSV",
        "notes.create": "Add notes", "tasks.view": "See tasks", "tasks.edit": "Complete tasks",
        "tasks.assign": "Assign tasks to others", "calls.make": "Make calls",
        "calls.view": "See call history", "calls.disposition": "Set call outcomes",
        "recordings.listen": "Play recordings", "recordings.download": "Bulk-download recordings",
        "coaching.monitor": "Listen in / whisper / barge", "campaigns.manage": "Start & stop campaigns",
        "playbooks.edit": "Edit scripts & objections", "agents.edit": "Edit AI agents",
        "dialer.settings": "Change calling settings", "dialer.keys": "Manage API keys",
        "compliance.override": "Change compliance gates", "reports.view": "See reports",
        "team.manage": "Invite & manage people", "build.pages": "Sites, forms, chat, email",
    }
    out = []
    for group, perms in groups:
        rows = []
        for p in perms:
            rows.append({"perm": p, "label": labels.get(p, p),
                         "by_role": {r: scope_for(r, p) for r in ROLES}})
        out.append({"group": group, "rows": rows})
    return out
