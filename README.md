# 60 Minute Sites — Backend HQ

Flask app that serves the marketing site at `/` and an admin HQ at `/admin`:

- **Leads Center (CRM)** — pipeline: New → Contacted → Booked → Built → Client → Dead, with notes and source tracking (`utm_content` from the ad funnel).
- **Website Builder** — business name + a few lines → a clean one-page site live at `/s/<slug>`, brand color + light/dark style. Built for doing it live on the 60-minute call.
- **PDF Flipbook Animator** — upload any PDF, get a page-turning book at `/f/<slug>`. Pages are rendered once (PyMuPDF) and stored **in the database**, so they survive redeploys.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # http://localhost:5060  (login password: changeme60)
```

## Deploy on Railway (and never lose data again)

The reason past deploys wiped your data: SQLite writes to the app container's
filesystem, and Railway **replaces that container on every deploy**. The fix is
to keep data in a Postgres service that lives outside the container:

1. Push this repo to GitHub, connect it in Railway (New Project → Deploy from GitHub).
2. In the same Railway project: **New → Database → PostgreSQL.**
3. On the app service → Variables → add `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   (reference variable). The app auto-detects it — nothing else to change.
4. Also set:
   - `ADMIN_PASSWORD` — your login password (default is `changeme60`; change it)
   - `SECRET_KEY` — any long random string (keeps you logged in across deploys)

That's it. Redeploy as often as you want — leads, sites, and flipbooks all live
in Postgres now and carry over every time. (Without `DATABASE_URL` the app
falls back to local SQLite, which is fine on your laptop and ephemeral on Railway.)

## Env vars

| Var | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection (Railway plugin) | sqlite:///data.db |
| `ADMIN_PASSWORD` | /login password | changeme60 |
| `SECRET_KEY` | session signing | dev value — set your own |
