"""60 Minute Sites — Backend HQ v2
Admin + customer accounts · Leads CRM · Forms (Formspree-style, feeds Leads)
· WYSIWYG site builder on real 60MS templates (+ AI text/design) · Flipbooks.

Persistence: set DATABASE_URL (Railway Postgres) and everything survives
deploys. Falls back to local SQLite (data.db) for development.
AI: set OPENAI_API_KEY (and optionally OPENAI_MODEL) to enable editor AI.
"""
import io
import json
import os
import re
import secrets
from datetime import datetime, timezone
from functools import wraps

import pymupdf as fitz  # PyMuPDF
import requests as http
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for, Response)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------- app config
app = Flask(__name__, static_folder="site", static_url_path="")

db_url = os.environ.get("DATABASE_URL", "sqlite:///data.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme60")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

db = SQLAlchemy(app)

LEAD_STATUSES = ["New", "Contacted", "Booked", "Built", "Client", "Dead"]
STATUS_COLORS = {
    "New": "#2E86DE", "Contacted": "#9A6B14", "Booked": "#E85D2A",
    "Built": "#8E44AD", "Client": "#2E7D4F", "Dead": "#888888",
}
LEAD_FIELDS = ["name", "phone", "email", "business", "business_type"]


# -------------------------------------------------------------------- models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)  # None = admin's lead
    form_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    business = db.Column(db.String(120), default="")
    business_type = db.Column(db.String(120), default="")
    source = db.Column(db.String(120), default="manual")
    status = db.Column(db.String(20), default="New")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.relationship("Note", backref="lead", cascade="all, delete-orphan",
                            order_by="Note.created_at.desc()")


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Form(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    redirect_url = db.Column(db.String(400), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    business_name = db.Column(db.String(120), nullable=False)
    template = db.Column(db.String(80), default="")
    html = db.Column(db.Text, default="")
    # legacy v1 fields (older generated sites still render through them)
    tagline = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    services = db.Column(db.Text, default="")
    about = db.Column(db.Text, default="")
    color = db.Column(db.String(9), default="#FF6B35")
    style = db.Column(db.String(20), default="clean")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=True)
    filename = db.Column(db.String(200), default="upload")
    mimetype = db.Column(db.String(100), default="application/octet-stream")
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Flipbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    title = db.Column(db.String(160), nullable=False)
    page_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pages = db.relationship("FlipbookPage", backref="flipbook",
                            cascade="all, delete-orphan",
                            order_by="FlipbookPage.page_num")


class FlipbookPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flipbook_id = db.Column(db.Integer, db.ForeignKey("flipbook.id"), nullable=False)
    page_num = db.Column(db.Integer, nullable=False)
    image = db.Column(db.LargeBinary, nullable=False)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)


def ensure_schema():
    """create_all + additive column migration so existing DBs upgrade in place."""
    db.create_all()
    insp = inspect(db.engine)
    wanted = {
        "lead": {"owner_id": "INTEGER", "form_id": "INTEGER"},
        "site": {"owner_id": "INTEGER", "template": "VARCHAR(80)", "html": "TEXT"},
    }
    with db.engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


with app.app_context():
    ensure_schema()


# ------------------------------------------------------------------- helpers
def current_user():
    if session.get("admin"):
        return "admin", None
    uid = session.get("uid")
    if uid:
        user = db.session.get(User, uid)
        if user:
            return "user", user
        session.clear()
    return None, None


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        role, _ = current_user()
        if not role:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def owner_filter(query, model):
    """Admin sees everything; customers see their own rows."""
    role, user = current_user()
    if role == "admin":
        return query
    return query.filter(model.owner_id == user.id)


def my_owner_id():
    role, user = current_user()
    return None if role == "admin" else user.id


def can_touch(obj):
    role, user = current_user()
    return role == "admin" or (user and obj.owner_id == user.id)


def slugify(txt):
    base = re.sub(r"[^a-z0-9]+", "-", (txt or "").lower()).strip("-") or "item"
    return f"{base}-{secrets.token_hex(2)}"


@app.context_processor
def inject_globals():
    role, user = current_user()
    return {"STATUSES": LEAD_STATUSES, "STATUS_COLORS": STATUS_COLORS,
            "role": role, "me": user}


TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "site", "landing-pages")


def list_templates():
    out = []
    if os.path.isdir(TEMPLATE_DIR):
        for f in sorted(os.listdir(TEMPLATE_DIR)):
            if f.endswith(".html") and f != "landing-page.html":
                out.append(f[:-5])
    return out


def instantiate_template(name, business_name):
    """Load a landing-page template and strip 60MS-specific wiring so it
    becomes a clean starting point for a customer site."""
    if name == "blank":
        html = render_template("blank_site.html", business_name=business_name)
        return html
    path = os.path.join(TEMPLATE_DIR, f"{name}.html")
    if not os.path.isfile(path):
        abort(404)
    html = open(path, encoding="utf-8", errors="ignore").read()
    # strip Meta pixel / gtag / hls / shared header+footer loaders
    html = re.sub(r"<script[^>]*>[^<]*(?:fbq|googletagmanager|gtag)\b.*?</script>",
                  "", html, flags=re.S)
    html = re.sub(r"<script[^>]*src=\"[^\"]*(?:gtag|googletagmanager|hls\.js)[^\"]*\"[^>]*>\s*</script>",
                  "", html)
    html = re.sub(r"<noscript><img[^>]*facebook[^>]*></noscript>", "", html)
    html = re.sub(r"<script src=\"/js/components.js\"></script>", "", html)
    html = html.replace('<div id="site-header"></div>', "")
    html = html.replace('<div id="site-footer"></div>', "")
    html = re.sub(r"<title>.*?</title>",
                  f"<title>{business_name}</title>", html, count=1, flags=re.S)
    return html


EDITOR_SNIPPET = ('<link rel="stylesheet" href="/static-admin/editor.css" data-wys="1">'
                  '<script src="/static-admin/editor.js" data-wys="1" defer></script>')


def strip_editor_artifacts(html):
    html = re.sub(r"<[^>]+data-wys=\"1\"[^>]*>\s*(</script>)?", "", html)
    html = re.sub(r"<div id=\"wys-toolbar\".*?</div>\s*(?=</body>)", "", html, flags=re.S)
    html = html.replace(' contenteditable="true"', "").replace(" contenteditable=\"\"", "")
    html = re.sub(r"<style id=\"wys-hover-style\">.*?</style>", "", html, flags=re.S)
    return html


# ---------------------------------------------------------------- auth + home
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/static-admin/<path:filename>")
def static_admin(filename):
    return send_from_directory(os.path.join(app.root_path, "static"), filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email and password == ADMIN_PASSWORD:
            session.clear()
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        user = User.query.filter_by(email=email).first() if email else None
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["uid"] = user.id
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("No match — check email + password (owner: leave email blank).")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not (name and email and len(password) >= 6):
            flash("Name, email, and a 6+ character password required.")
        elif User.query.filter_by(email=email).first():
            flash("That email already has an account — log in instead.")
        else:
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["uid"] = user.id
            return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboard
@app.route("/admin")
@login_required
def dashboard():
    stats = {
        "leads": owner_filter(Lead.query, Lead).count(),
        "booked": owner_filter(Lead.query, Lead)
                  .filter(Lead.status.in_(["Booked", "Built", "Client"])).count(),
        "sites": owner_filter(Site.query, Site).count(),
        "forms": owner_filter(Form.query, Form).count(),
    }
    recent = owner_filter(Lead.query, Lead).order_by(Lead.created_at.desc()).limit(8).all()
    return render_template("dashboard.html", stats=stats, recent=recent)


# -------------------------------------------------------------- leads center
@app.route("/admin/leads")
@login_required
def leads():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    query = owner_filter(Lead.query, Lead)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like),
                                    Lead.email.ilike(like), Lead.business.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(Lead.created_at.desc()).all()
    return render_template("leads.html", rows=rows, q=q, status=status)


@app.route("/admin/leads/new", methods=["GET", "POST"])
@login_required
def lead_new():
    if request.method == "POST":
        lead = Lead(owner_id=my_owner_id(),
                    source=request.form.get("source", "manual").strip() or "manual",
                    status=request.form.get("status", "New"),
                    **{f: request.form.get(f, "").strip() for f in LEAD_FIELDS})
        lead.name = lead.name or "Unknown"
        db.session.add(lead)
        db.session.commit()
        flash(f"Lead “{lead.name}” added.")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_form.html", lead=None)


@app.route("/admin/leads/<int:lead_id>", methods=["GET", "POST"])
@login_required
def lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if not can_touch(lead):
        abort(403)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "status" and request.form.get("status") in LEAD_STATUSES:
            lead.status = request.form.get("status")
        elif action == "note":
            body = request.form.get("body", "").strip()
            if body:
                db.session.add(Note(lead_id=lead.id, body=body))
        elif action == "update":
            for f in LEAD_FIELDS + ["source"]:
                setattr(lead, f, request.form.get(f, "").strip())
        elif action == "delete":
            db.session.delete(lead)
            db.session.commit()
            flash("Lead deleted.")
            return redirect(url_for("leads"))
        db.session.commit()
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_detail.html", lead=lead)


# ------------------------------------------------------- forms (formspree-ish)
@app.route("/admin/forms", methods=["GET", "POST"])
@login_required
def forms():
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Contact form"
        form = Form(owner_id=my_owner_id(), name=name, slug=slugify(name),
                    redirect_url=request.form.get("redirect_url", "").strip())
        db.session.add(form)
        db.session.commit()
        flash(f"Form “{name}” created — grab the embed code below.")
        return redirect(url_for("forms"))
    rows = owner_filter(Form.query, Form).order_by(Form.created_at.desc()).all()
    counts = {f.id: Lead.query.filter_by(form_id=f.id).count() for f in rows}
    return render_template("forms.html", rows=rows, counts=counts,
                           host=request.host_url.rstrip("/"))


@app.route("/admin/forms/<int:form_id>/delete", methods=["POST"])
@login_required
def form_delete(form_id):
    form = Form.query.get_or_404(form_id)
    if not can_touch(form):
        abort(403)
    db.session.delete(form)
    db.session.commit()
    flash("Form deleted (its leads are kept).")
    return redirect(url_for("forms"))


@app.route("/form/<slug>", methods=["POST", "OPTIONS"])
def form_submit(slug):
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    form = Form.query.filter_by(slug=slug).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    if data.get("_gotcha"):  # honeypot
        return _cors(jsonify(ok=True))
    lead = Lead(owner_id=form.owner_id, form_id=form.id,
                source=data.get("source") or data.get("utm_content") or form.name,
                **{f: str(data.get(f, ""))[:200] for f in LEAD_FIELDS})
    lead.name = lead.name or "Unknown"
    db.session.add(lead)
    db.session.flush()
    extras = {k: v for k, v in data.items()
              if k not in LEAD_FIELDS + ["source", "_gotcha", "_next"] and v}
    if extras:
        db.session.add(Note(lead_id=lead.id, body="Form extras: " +
                            json.dumps(extras, ensure_ascii=False)[:2000]))
    db.session.commit()
    if request.is_json:
        return _cors(jsonify(ok=True, lead_id=lead.id))
    return redirect(data.get("_next") or form.redirect_url
                    or url_for("form_thanks", slug=slug))


@app.route("/form/<slug>/thanks")
def form_thanks(slug):
    form = Form.query.filter_by(slug=slug).first_or_404()
    return render_template("form_thanks.html", form=form)


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


# ---------------------------------------------------------- customers (admin)
@app.route("/admin/customers", methods=["GET", "POST"])
@admin_required
def customers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "") or secrets.token_urlsafe(8)
        if not (name and email):
            flash("Name and email required.")
        elif User.query.filter_by(email=email).first():
            flash("That email already exists.")
        else:
            db.session.add(User(name=name, email=email,
                                password_hash=generate_password_hash(password)))
            db.session.commit()
            flash(f"Customer “{name}” created — password: {password}")
        return redirect(url_for("customers"))
    rows = User.query.order_by(User.created_at.desc()).all()
    stats = {u.id: {"sites": Site.query.filter_by(owner_id=u.id).count(),
                    "leads": Lead.query.filter_by(owner_id=u.id).count()}
             for u in rows}
    return render_template("customers.html", rows=rows, stats=stats)


@app.route("/admin/customers/<int:user_id>/<action>", methods=["POST"])
@admin_required
def customer_action(user_id, action):
    user = User.query.get_or_404(user_id)
    if action == "delete":
        db.session.delete(user)
        flash(f"Customer “{user.name}” deleted (their sites/leads are kept, unowned).")
    elif action == "reset":
        new_pw = secrets.token_urlsafe(8)
        user.password_hash = generate_password_hash(new_pw)
        flash(f"New password for {user.name}: {new_pw}")
    db.session.commit()
    return redirect(url_for("customers"))


# ------------------------------------------------------ site builder (wysiwyg)
@app.route("/admin/sites")
@login_required
def sites():
    rows = owner_filter(Site.query, Site).order_by(Site.updated_at.desc()).all()
    return render_template("sites.html", rows=rows)


@app.route("/admin/sites/new", methods=["GET", "POST"])
@login_required
def site_new():
    if request.method == "POST":
        business = request.form.get("business_name", "").strip() or "My Business"
        template = request.form.get("template", "blank")
        site = Site(owner_id=my_owner_id(), slug=slugify(business),
                    business_name=business, template=template,
                    html=instantiate_template(template, business))
        db.session.add(site)
        db.session.commit()
        return redirect(url_for("editor", site_id=site.id))
    return render_template("site_picker.html", templates=list_templates())


@app.route("/edit/<int:site_id>")
@login_required
def editor(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    if not site.html:  # legacy v1 site — wrap its rendered page for editing
        services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
        site.html = render_template("public_site.html", site=site, services=services)
        db.session.commit()
    html = site.html
    my_forms = owner_filter(Form.query, Form).all()
    boot = ("<script data-wys=\"1\">window.WYS = " + json.dumps({
        "siteId": site.id, "slug": site.slug, "ai": bool(OPENAI_API_KEY),
        "forms": [{"name": f.name, "slug": f.slug} for f in my_forms],
    }) + ";</script>")
    inject = boot + EDITOR_SNIPPET
    if "</body>" in html:
        html = html.replace("</body>", inject + "</body>", 1)
    else:
        html += inject
    return Response(html, mimetype="text/html")


@app.route("/edit/<int:site_id>/save", methods=["POST"])
@login_required
def editor_save(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    payload = request.get_json(silent=True) or {}
    html = payload.get("html", "")
    if not html:
        return jsonify(ok=False, error="empty"), 400
    site.html = strip_editor_artifacts(html)
    db.session.commit()
    return jsonify(ok=True)


@app.route("/admin/sites/<int:site_id>/delete", methods=["POST"])
@login_required
def site_delete(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    db.session.delete(site)
    db.session.commit()
    flash("Site deleted.")
    return redirect(url_for("sites"))


@app.route("/s/<slug>")
def public_site(slug):
    site = Site.query.filter_by(slug=slug).first_or_404()
    if site.html:
        return Response(site.html, mimetype="text/html")
    services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
    return render_template("public_site.html", site=site, services=services)


# ---------------------------------------------------- funnels (links + export)
@app.route("/admin/funnels")
@login_required
def funnels():
    rows = owner_filter(Site.query, Site).order_by(Site.updated_at.desc()).all()
    my_forms = owner_filter(Form.query, Form).all()
    return render_template("funnels.html", rows=rows, my_forms=my_forms,
                           host=request.host_url.rstrip("/"))


@app.route("/admin/sites/<int:site_id>/download")
@login_required
def site_download(site_id):
    site = Site.query.get_or_404(site_id)
    if not can_touch(site):
        abort(403)
    html = site.html or ""
    if not html:
        services = [s.strip() for s in (site.services or "").splitlines() if s.strip()]
        html = render_template("public_site.html", site=site, services=services)
    # absolutize root-relative assets so the file renders anywhere it's hosted
    base = request.host_url.rstrip("/")
    html = re.sub(r'(src|href|action)="/(?!/)', rf'\1="{base}/', html)
    return Response(html, mimetype="text/html", headers={
        "Content-Disposition": f'attachment; filename="{site.slug}.html"'})


# --------------------------------------------------------------------- media
@app.route("/media", methods=["POST"])
@login_required
def media_upload():
    file = request.files.get("file")
    if not file or not file.mimetype.startswith("image/"):
        return jsonify(ok=False, error="image files only"), 400
    m = Media(owner_id=my_owner_id(), filename=file.filename,
              mimetype=file.mimetype, data=file.read())
    db.session.add(m)
    db.session.commit()
    return jsonify(ok=True, url=f"/media/{m.id}")


@app.route("/media/<int:media_id>")
def media_get(media_id):
    m = Media.query.get_or_404(media_id)
    return Response(m.data, mimetype=m.mimetype,
                    headers={"Cache-Control": "public, max-age=604800"})


# ------------------------------------------------------------------ editor AI
def _openai(messages, max_tokens=2000):
    r = http.post("https://api.openai.com/v1/chat/completions",
                  headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                  json={"model": OPENAI_MODEL, "messages": messages,
                        "max_tokens": max_tokens, "temperature": 0.7},
                  timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


@app.route("/ai/text", methods=["POST"])
@login_required
def ai_text():
    if not OPENAI_API_KEY:
        return jsonify(ok=False, error="Set OPENAI_API_KEY on the server."), 400
    p = request.get_json(silent=True) or {}
    try:
        out = _openai([
            {"role": "system", "content":
             "You write tight, persuasive copy for small-business websites. "
             "Return ONLY the replacement text — no quotes, no commentary, no markdown."},
            {"role": "user", "content":
             f"Instruction: {p.get('instruction', 'improve this')}\n\n"
             f"Current text:\n{p.get('text', '')[:4000]}"},
        ], max_tokens=800)
        return jsonify(ok=True, text=out)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 502


@app.route("/ai/design", methods=["POST"])
@login_required
def ai_design():
    if not OPENAI_API_KEY:
        return jsonify(ok=False, error="Set OPENAI_API_KEY on the server."), 400
    p = request.get_json(silent=True) or {}
    try:
        out = _openai([
            {"role": "system", "content":
             "You are a web designer. Given a page's structural outline and a design "
             "instruction, return ONLY a CSS stylesheet (no markdown fences, no <style> tag) "
             "that restyles the page. Use specific selectors from the outline, use "
             "!important where needed to override existing styles, and keep it tasteful."},
            {"role": "user", "content":
             f"Design instruction: {p.get('instruction', '')}\n\n"
             f"Page outline (tag.class/#id list):\n{p.get('outline', '')[:6000]}\n\n"
             f"Current AI override CSS (replace it):\n{p.get('current_css', '')[:3000]}"},
        ], max_tokens=2500)
        out = re.sub(r"^```(?:css)?|```$", "", out, flags=re.M).strip()
        return jsonify(ok=True, css=out)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 502


# ---------------------------------------------------------- flipbook animator
@app.route("/admin/flipbooks", methods=["GET", "POST"])
@admin_required
def flipbooks():
    if request.method == "POST":
        file = request.files.get("pdf")
        title = request.form.get("title", "").strip() or "Untitled"
        if not file or not file.filename.lower().endswith(".pdf"):
            flash("Upload a PDF file.")
            return redirect(url_for("flipbooks"))
        try:
            doc = fitz.open(stream=file.read(), filetype="pdf")
        except Exception:
            flash("Couldn't read that PDF.")
            return redirect(url_for("flipbooks"))
        if doc.page_count > 80:
            flash("PDF too long (80-page max).")
            return redirect(url_for("flipbooks"))
        book = Flipbook(slug=slugify(title), title=title, page_count=doc.page_count)
        db.session.add(book)
        db.session.flush()
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            db.session.add(FlipbookPage(flipbook_id=book.id, page_num=i,
                                        image=pix.tobytes("png"),
                                        width=pix.width, height=pix.height))
        db.session.commit()
        flash(f"Flipbook “{title}” ready at /f/{book.slug}")
        return redirect(url_for("flipbooks"))
    rows = Flipbook.query.order_by(Flipbook.created_at.desc()).all()
    return render_template("flipbooks.html", rows=rows)


@app.route("/admin/flipbooks/<int:book_id>/delete", methods=["POST"])
@admin_required
def flipbook_delete(book_id):
    book = Flipbook.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash("Flipbook deleted.")
    return redirect(url_for("flipbooks"))


@app.route("/f/<slug>")
def flipbook_view(slug):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    first = book.pages[0] if book.pages else None
    return render_template("flipbook_view.html", book=book, first=first)


@app.route("/f/<slug>/page/<int:num>.png")
def flipbook_page(slug, num):
    book = Flipbook.query.filter_by(slug=slug).first_or_404()
    page = FlipbookPage.query.filter_by(flipbook_id=book.id, page_num=num).first()
    if not page:
        abort(404)
    return Response(page.image, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    app.run(debug=True, port=5060)
