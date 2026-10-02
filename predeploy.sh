#!/usr/bin/env bash
# Run this before every deploy that touches the dialer.
#
#   ./predeploy.sh
#
# It takes a named Railway backup, downloads a JSON export, and runs the test
# that restores the real production data and upgrades the schema over it. If
# anything here is red, do not deploy.
set -uo pipefail
cd "$(dirname "$0")"

STAMP="$(date +%F-%H%M)"
BACKUPS="../60MS-backups"
PY=".venv/bin/python"
fail=0

say()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32mok\033[0m   %s\n" "$*"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$*"; fail=1; }
warn() { printf "  \033[33mnote\033[0m %s\n" "$*"; }

say "1. Railway database backup"
if command -v railway >/dev/null 2>&1; then
  if railway postgres pitr backup create --service Postgres \
       --name "pre-deploy-$STAMP" >/dev/null 2>&1; then
    ok "named backup pre-deploy-$STAMP created"
  else
    bad "could not create a Railway backup (is the project linked? 'railway link')"
  fi
else
  bad "the railway CLI is not installed"
fi

say "2. Full data export"
mkdir -p "$BACKUPS"
OUT="$BACKUPS/60ms-prod-export-$STAMP.json"
PW="$(railway variables -s web --json 2>/dev/null \
      | $PY -c 'import json,sys; print(json.load(sys.stdin).get("ADMIN_PASSWORD",""))' 2>/dev/null)"
if [ -n "$PW" ]; then
  if $PY - "$OUT" "$PW" <<'PYEOF'
import sys, requests
out, pw = sys.argv[1], sys.argv[2]
s = requests.Session()
s.post("https://60minutesites.com/login", data={"email": "", "password": pw},
       allow_redirects=False, timeout=30)
r = s.get("https://60minutesites.com/admin/export.json", timeout=180)
r.raise_for_status()
open(out, "wb").write(r.content)
import json
d = json.loads(r.content)
print("   ", " ".join(f"{k}={len(v)}" for k, v in d.items() if isinstance(v, list)))
PYEOF
  then ok "exported to $OUT"
  else bad "the export did not download"
  fi
else
  warn "no ADMIN_PASSWORD from Railway; skipping the live export"
fi

say "3. Migration safety against real production data"
if $PY -m pytest tests/test_migration_safety.py -q >/tmp/predeploy-mig.log 2>&1; then
  ok "$(tail -2 /tmp/predeploy-mig.log | head -1)"
else
  bad "migration safety FAILED — see /tmp/predeploy-mig.log"
  tail -20 /tmp/predeploy-mig.log
fi

say "4. Full test suite"
if $PY -m pytest tests/ -q >/tmp/predeploy-all.log 2>&1; then
  ok "$(grep -E '[0-9]+ passed' /tmp/predeploy-all.log | tail -1)"
else
  bad "tests FAILED — see /tmp/predeploy-all.log"
  grep -E "FAILED|Error" /tmp/predeploy-all.log | head -20
fi

say "5. Branch and working tree"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "   on branch $BRANCH"
if [ -n "$(git status --porcelain)" ]; then
  warn "uncommitted changes:"; git status --short | head -10
else
  ok "working tree clean"
fi

say "6. Deploy reminders"
cat <<'NOTES'
   Railway web service — Variables to add before the first dialer deploy:
     FERNET_KEYS   a long random string (openssl rand -hex 32)
     PUBLIC_URL    https://60minutesites.com
   Procfile now asks for threaded workers; confirm the start command is:
     gunicorn app:app -k gthread -w 2 --threads 8 --timeout 60 --bind 0.0.0.0:$PORT
   AI campaigns also need a second service from this repo: python worker.py
   Rollback: Railway -> web -> Deployments -> the previous one -> Rollback.
   Old code runs fine on the new schema; every change was additive.
NOTES

if [ "$fail" -eq 0 ]; then
  printf "\n\033[32mReady to deploy.\033[0m\n"
else
  printf "\n\033[31mNot ready. Fix the failures above first.\033[0m\n"; exit 1
fi
