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

> Data lives in Railway Postgres (`DATABASE_URL`); deploys never touch it. Backups: Railway PITR + volume snapshots + HQ Setup → Export.

---

## Teams & AI Calling (the dialer module)

Two add-ons, switched on per account from **Admin → Customers** (or at signup).
An account without the flags sees no new navigation and `/dialer` returns 404,
so existing customers are unaffected.

- **Multi-user support** — seats, five roles (owner / admin / manager / agent /
  viewer), email invitations, an activity log. Members share the owner's CRM
  data; tasks are personal.
- **AI calling system** — a human power dialer with a pop-out phone, an AI
  voice agent for inbound and outbound, recordings, transcripts, call scoring,
  automatic follow-up tasks, campaigns and reporting.

### Bring your own keys

The platform holds no vendor accounts. Each customer enters their own Twilio,
ElevenLabs and OpenAI keys in **Calling → Setup**, stored encrypted, and pays
those vendors directly. Nothing is marked up, and no key is ever typed into
Railway by hand.

### Practice mode

`DIALER_SIMULATION=1`, or the per-account **Practice mode** switch, replaces
every vendor with an in-process fake that drives the real webhook and
processing path. Every screen and the whole campaign flow work with no
accounts and no spend — which is also the right surface for a live demo.
Outcomes are deterministic, keyed off the last digit of the number dialled:
1 human · 2 answering machine · 3 busy · 4 no answer · 5 wrong number ·
6 mobile · 7 VoIP.

### The compliance gate

`dialer/compliance.py:can_dial()` runs before every dial and its decision is
frozen onto the call row as evidence. It checks suppression, the calling
window in the **lead's** timezone, a per-state posture table, and — for AI
calls only — line type and consent. Human dialing is never line-type gated.

The AI line-type restriction is **on by default and overridable** by an
owner/admin with a typed attestation, which is audit-logged and attached to
every call it produces. Calling mobile numbers with a synthetic voice without
consent carries real legal exposure in the US; the software supplies the
control and the paper trail, the operator makes the call about their own list.

### Running it

```bash
pip install -r requirements.txt
DIALER_SIMULATION=1 python app.py      # http://localhost:5062
pytest -q                              # the full suite
```

### Deploying

The web service needs threaded workers — Twilio fires roughly seven webhooks
per dial and wants a response inside 150ms:

```
web: gunicorn app:app -k gthread -w 2 --threads 8 --timeout 60 --bind 0.0.0.0:$PORT
```

AI campaigns and housekeeping need a second Railway service from this same
repo with the start command `python worker.py`. Power dialing does not — the
rep's browser drives it.

| Env var | Purpose |
|---|---|
| `FERNET_KEYS` | Comma-separated, newest first. Encrypts stored vendor keys. Falls back to deriving one from `SECRET_KEY`. |
| `PUBLIC_URL` | The https origin webhooks come back to. The worker has no request to infer it from. |
| `DIALER_SIMULATION` | `1` turns on practice mode globally. |
| `DIALER_DISABLED` | `1` makes every `/dialer` route 503 and idles the worker, with no code change. |
| `DIALER_SIMULATION_FAIL` | `twilio` / `elevenlabs` / `llm` — forces a vendor failure, for testing the error screens. |

Before any deploy that touches this module:

```bash
railway postgres pitr backup create --service Postgres --name pre-deploy-$(date +%F)
pytest -q tests/test_migration_safety.py
```

That suite restores the real production export, upgrades the schema over it
twice, and asserts no customer-visible change. If it is red, do not deploy.
