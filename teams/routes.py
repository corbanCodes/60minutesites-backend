"""Team management: /admin/team plus the public /join/<token> accept page."""
from datetime import datetime, timezone
from functools import wraps

from flask import (abort, flash, g, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import generate_password_hash

from app import User, db, send_email
from dialer.settings_store import account_owner, current_account_id

from teams import bp, perms, seats, tokens
from teams.models import Invitation, log


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require(perm):
    """Route guard. g.member is None for Corban's platform-admin session,
    which perms.can() treats as allowed."""
    def deco(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if not perms.can(getattr(g, "member", None), perm):
                return render_template("teams/denied.html", perm=perm), 403
            return fn(*a, **kw)
        return wrapped
    return deco


@bp.route("/")
@require("team.manage")
def team_home():
    acct = g.account_id
    rows = seats.members(acct)
    owner = account_owner(acct)
    return render_template(
        "teams/team.html", members=rows, owner=owner,
        invites=seats.pending_invites(acct), usage=seats.usage(acct),
        roles=perms.ROLES, role_labels=perms.ROLE_LABELS,
        role_blurbs=perms.ROLE_BLURBS, matrix=perms.matrix_rows(),
        me=g.member, call_counts=_calls_this_week(acct, rows))


def _calls_this_week(account_id, rows):
    from datetime import timedelta

    from dialer.models import Call
    since = _now() - timedelta(days=7)
    out = {}
    for u in rows:
        out[u.id] = (db.session.query(Call.id)
                     .filter(Call.account_id == account_id,
                             Call.agent_user_id == u.id,
                             Call.started_at >= since).count())
    return out


@bp.route("/invite", methods=["POST"])
@require("team.manage")
def invite():
    acct = g.account_id
    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    role = perms.normalize_role(request.form.get("role"))
    title = (request.form.get("job_title") or "").strip()[:80]

    if role == "owner":
        flash("There can only be one owner. Pick Admin instead.", "error")
        return redirect(url_for("teams.team_home"))
    if "@" not in email:
        flash("That doesn't look like an email address.", "error")
        return redirect(url_for("teams.team_home"))

    # Lock the owner row, then count. Two admins clicking at once serialise here.
    seats.lock_account(acct)
    if User.query.filter_by(email=email).first():
        flash("Someone with that email already has a 60 Minute Sites login.", "error")
        return redirect(url_for("teams.team_home"))
    existing = (Invitation.query.filter_by(account_id=acct, email=email)
                .filter(Invitation.accepted_at.is_(None),
                        Invitation.cancelled_at.is_(None)).first())
    if existing and existing.state == "pending":
        flash(f"{email} already has an invitation waiting.", "error")
        return redirect(url_for("teams.team_home"))

    ok, message = seats.can_add(acct)
    if not ok:
        flash(message, "error")
        return redirect(url_for("teams.team_home"))

    inv = Invitation(account_id=acct, email=email, name=name, role=role,
                     job_title=title, invited_by=getattr(g.member, "id", None),
                     expires_at=seats.new_expiry())
    db.session.add(inv)
    db.session.flush()
    link = url_for("join_invite", token=tokens.make(inv.id), _external=True)
    log("team.invite", target=email, detail=f"role={role}", account_id=acct,
        user=g.member)
    db.session.commit()

    owner = account_owner(acct)
    company = (owner.name if owner else "your team")
    sent = send_email(
        email, f"You've been added to {company} on 60 Minute Sites",
        f"<div style='font-family:sans-serif;font-size:15px'>"
        f"<h2>You've got a seat on {company}'s account</h2>"
        f"<p>{(g.member.name if g.member else 'Your admin')} added you as "
        f"<b>{perms.ROLE_LABELS[role]}</b>. Pick a password and you're in:</p>"
        f"<p><a href='{link}' style='background:#FF6B35;color:#fff;padding:12px 22px;"
        f"border-radius:8px;text-decoration:none;font-weight:700'>Set up my login</a></p>"
        f"<p style='color:#777;font-size:13px'>This link works once and expires in "
        f"{seats.INVITE_DAYS} days.</p></div>")
    if sent:
        flash(f"Invitation sent to {email}.")
    else:
        flash(f"Invitation created. Email isn't configured, so send them this "
              f"link yourself: {link}", "sticky")
    return redirect(url_for("teams.team_home"))


@bp.route("/invite/<int:invite_id>/<action>", methods=["POST"])
@require("team.manage")
def invite_action(invite_id, action):
    inv = Invitation.query.get_or_404(invite_id)
    if inv.account_id != g.account_id:
        abort(403)
    if action == "cancel":
        inv.cancelled_at = _now()
        log("team.invite_cancel", target=inv.email, account_id=g.account_id,
            user=g.member)
        flash(f"Invitation for {inv.email} cancelled — the seat is free again.")
    elif action == "resend":
        if inv.state == "expired":
            ok, message = seats.can_add(g.account_id)
            if not ok:
                flash(message, "error")
                return redirect(url_for("teams.team_home"))
        inv.expires_at = seats.new_expiry()
        inv.cancelled_at = None
        link = url_for("join_invite", token=tokens.make(inv.id), _external=True)
        sent = send_email(inv.email, "Your 60 Minute Sites invitation",
                          f"<p style='font-family:sans-serif'>Here's your link again: "
                          f"<a href='{link}'>set up your login</a>.</p>")
        flash(f"Invitation resent to {inv.email}." if sent
              else f"Send them this link: {link}", None if sent else "sticky")
        log("team.invite_resend", target=inv.email, account_id=g.account_id,
            user=g.member)
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("teams.team_home"))


@bp.route("/member/<int:user_id>/<action>", methods=["POST"])
@require("team.manage")
def member_action(user_id, action):
    acct = g.account_id
    user = User.query.get_or_404(user_id)
    if (user.account_id or user.id) != acct:
        abort(403)
    me = g.member

    # The owner is protected from everyone except the owner.
    if user.account_id is None and not perms.can(me, "team.remove_owner"):
        flash("Only the account owner can change the owner.", "error")
        return redirect(url_for("teams.team_home"))
    if me is not None and user.id == me.id and action in ("deactivate", "role"):
        flash("You can't change your own access — ask another admin.", "error")
        return redirect(url_for("teams.team_home"))

    if action == "role":
        role = perms.normalize_role(request.form.get("role"))
        if role == "owner":
            flash("There can only be one owner.", "error")
            return redirect(url_for("teams.team_home"))
        old, user.role = user.role, role
        log("team.role_change", target=user.email, detail=f"{old} -> {role}",
            account_id=acct, user=me)
        flash(f"{user.name} is now {perms.ROLE_LABELS[role]}.")
    elif action == "deactivate":
        user.active = False
        log("team.deactivate", target=user.email, account_id=acct, user=me)
        flash(f"{user.name} can no longer log in. Their seat is free and their "
              f"notes and calls are kept.")
    elif action == "reactivate":
        ok, message = seats.can_add(acct)
        if not ok:
            flash(message, "error")
            return redirect(url_for("teams.team_home"))
        user.active = True
        log("team.reactivate", target=user.email, account_id=acct, user=me)
        flash(f"{user.name} is back on the team.")
    elif action == "reset":
        import secrets as _s
        pw = _s.token_urlsafe(8)
        user.password_hash = generate_password_hash(pw)
        log("team.password_reset", target=user.email, account_id=acct, user=me)
        flash(f"New password for {user.name}: {pw}", "sticky")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("teams.team_home"))


@bp.route("/log")
@require("team.manage")
def audit():
    from teams.models import AuditLog
    rows = (AuditLog.query.filter_by(account_id=g.account_id)
            .order_by(AuditLog.created_at.desc()).limit(200).all())
    return render_template("teams/audit.html", rows=rows)


# ------------------------------------------------------- public accept page
def join_invite(token):
    """Outside the blueprint guard: the invitee has no session yet."""
    invite_id = tokens.read(token, max_age_days=seats.INVITE_DAYS)
    inv = db.session.get(Invitation, invite_id) if invite_id else None
    if inv is None or inv.state != "pending":
        reason = {"accepted": "That invitation has already been used.",
                  "cancelled": "That invitation was cancelled.",
                  "expired": "That invitation has expired."}.get(
                      inv.state if inv else "", "That invitation link isn't valid.")
        return render_template("teams/join_problem.html", reason=reason), 400

    owner = account_owner(inv.account_id)
    company = owner.name if owner else "your team"

    if request.method == "POST":
        name = (request.form.get("name") or inv.name or "").strip()
        pw = request.form.get("password") or ""
        if not name or len(pw) < 6:
            flash("Your name and a password of at least 6 characters, please.",
                  "error")
            return render_template("teams/join.html", inv=inv, company=company,
                                   token=token)
        if User.query.filter_by(email=inv.email).first():
            return render_template("teams/join_problem.html",
                                   reason="There's already a login for that "
                                          "email address."), 400
        # Re-check the seat at ACCEPT time, not just at invite time.
        seats.lock_account(inv.account_id)
        u = seats.usage(inv.account_id)
        if u["members"] >= u["limit"]:
            return render_template(
                "teams/join_problem.html",
                reason=seats.FULL_MESSAGE.format(limit=u["limit"])), 400

        user = User(name=name, email=inv.email, role=inv.role,
                    account_id=inv.account_id, active=True,
                    job_title=inv.job_title,
                    password_hash=generate_password_hash(pw))
        db.session.add(user)
        inv.accepted_at = _now()
        db.session.flush()
        log("team.join", target=inv.email, detail=f"role={inv.role}",
            account_id=inv.account_id, user=user)
        db.session.commit()
        session.clear()
        session["uid"] = user.id
        flash(f"You're in. Welcome to {company}.")
        return redirect(url_for("dashboard"))

    return render_template("teams/join.html", inv=inv, company=company, token=token)
