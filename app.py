"""60 Minute Sites — Backend HQ
Flask app: leads CRM, simple website builder, PDF flipbook animator.
Serves the copied marketing site at / and the admin at /admin.

Persistence: set DATABASE_URL (Railway Postgres) and data survives every
deploy. Falls back to local SQLite (data.db) for development only.
"""
import io
import os
import re
import secrets
from datetime import datetime, timezone
from functools import wraps

import pymupdf as fitz  # PyMuPDF
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, session, url_for, Response)
from flask_sqlalchemy import SQLAlchemy

# ---------------------------------------------------------------- app config
app = Flask(__name__, static_folder="site", static_url_path="")

db_url = os.environ.get("DATABASE_URL", "sqlite:///data.db")
if db_url.startswith("postgres://"):
    # Railway/Heroku style URL; SQLAlchemy needs the postgresql:// scheme
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # 40MB uploads

app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme60")

db = SQLAlchemy(app)

LEAD_STATUSES = ["New", "Contacted", "Booked", "Built", "Client", "Dead"]
STATUS_COLORS = {
    "New": "#2E86DE", "Contacted": "#9A6B14", "Booked": "#E85D2A",
    "Built": "#8E44AD", "Client": "#2E7D4F", "Dead": "#888888",
}


# -------------------------------------------------------------------- models
class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    business = db.Column(db.String(120), default="")
    business_type = db.Column(db.String(120), default="")
    source = db.Column(db.String(120), default="manual")  # utm_content / manual
    status = db.Column(db.String(20), default="New")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.relationship("Note", backref="lead", cascade="all, delete-orphan",
                            order_by="Note.created_at.desc()")


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    business_name = db.Column(db.String(120), nullable=False)
    tagline = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    services = db.Column(db.Text, default="")       # one per line
    about = db.Column(db.Text, default="")
    color = db.Column(db.String(9), default="#FF6B35")
    style = db.Column(db.String(20), default="clean")  # clean | bold
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


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
    image = db.Column(db.LargeBinary, nullable=False)  # PNG bytes, lives in the DB
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)


with app.app_context():
    db.create_all()


# ------------------------------------------------------------------- helpers
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def slugify(text):
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "item"
    return f"{base}-{secrets.token_hex(2)}"


@app.context_processor
def inject_globals():
    return {"STATUSES": LEAD_STATUSES, "STATUS_COLORS": STATUS_COLORS}


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
        if request.form.get("password") == ADMIN_PASSWORD:
            session["authed"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Wrong password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboard
@app.route("/admin")
@login_required
def dashboard():
    stats = {
        "leads": Lead.query.count(),
        "booked": Lead.query.filter(Lead.status.in_(["Booked", "Built", "Client"])).count(),
        "sites": Site.query.count(),
        "flipbooks": Flipbook.query.count(),
    }
    recent = Lead.query.order_by(Lead.created_at.desc()).limit(8).all()
    return render_template("dashboard.html", stats=stats, recent=recent)


# -------------------------------------------------------------- leads center
@app.route("/admin/leads")
@login_required
def leads():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    query = Lead.query
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
        lead = Lead(
            name=request.form.get("name", "").strip() or "Unknown",
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            business=request.form.get("business", "").strip(),
            business_type=request.form.get("business_type", "").strip(),
            source=request.form.get("source", "manual").strip() or "manual",
            status=request.form.get("status", "New"),
        )
        db.session.add(lead)
        db.session.commit()
        flash(f"Lead “{lead.name}” added.")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_form.html", lead=None)


@app.route("/admin/leads/<int:lead_id>", methods=["GET", "POST"])
@login_required
def lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "status":
            new_status = request.form.get("status")
            if new_status in LEAD_STATUSES:
                lead.status = new_status
        elif action == "note":
            body = request.form.get("body", "").strip()
            if body:
                db.session.add(Note(lead_id=lead.id, body=body))
        elif action == "update":
            for field in ["name", "phone", "email", "business", "business_type", "source"]:
                setattr(lead, field, request.form.get(field, "").strip())
        elif action == "delete":
            db.session.delete(lead)
            db.session.commit()
            flash("Lead deleted.")
            return redirect(url_for("leads"))
        db.session.commit()
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_detail.html", lead=lead)


# ------------------------------------------------------------ website builder
@app.route("/admin/sites")
@login_required
def sites():
    rows = Site.query.order_by(Site.created_at.desc()).all()
    return render_template("sites.html", rows=rows)


def _site_from_form(site, form):
    site.business_name = form.get("business_name", "").strip() or "My Business"
    site.tagline = form.get("tagline", "").strip()
    site.phone = form.get("phone", "").strip()
    site.email = form.get("email", "").strip()
    site.services = form.get("services", "").strip()
    site.about = form.get("about", "").strip()
    site.color = form.get("color", "#FF6B35")
    site.style = form.get("style", "clean")
    return site


@app.route("/admin/sites/new", methods=["GET", "POST"])
@login_required
def site_new():
    if request.method == "POST":
        site = _site_from_form(Site(slug="tmp"), request.form)
        site.slug = slugify(site.business_name)
        db.session.add(site)
        db.session.commit()
        flash(f"Site “{site.business_name}” is live at /s/{site.slug}")
        return redirect(url_for("sites"))
    return render_template("site_form.html", site=None)


@app.route("/admin/sites/<int:site_id>", methods=["GET", "POST"])
@login_required
def site_edit(site_id):
    site = Site.query.get_or_404(site_id)
    if request.method == "POST":
        if request.form.get("action") == "delete":
            db.session.delete(site)
            db.session.commit()
            flash("Site deleted.")
            return redirect(url_for("sites"))
        _site_from_form(site, request.form)
        db.session.commit()
        flash("Site updated.")
        return redirect(url_for("sites"))
    return render_template("site_form.html", site=site)


@app.route("/s/<slug>")
def public_site(slug):
    site = Site.query.filter_by(slug=slug).first_or_404()
    services = [s.strip() for s in site.services.splitlines() if s.strip()]
    return render_template("public_site.html", site=site, services=services)


# ---------------------------------------------------------- flipbook animator
@app.route("/admin/flipbooks", methods=["GET", "POST"])
@login_required
def flipbooks():
    if request.method == "POST":
        file = request.files.get("pdf")
        title = request.form.get("title", "").strip() or "Untitled"
        if not file or not file.filename.lower().endswith(".pdf"):
            flash("Upload a PDF file.")
            return redirect(url_for("flipbooks"))
        data = file.read()
        try:
            doc = fitz.open(stream=data, filetype="pdf")
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
@login_required
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
