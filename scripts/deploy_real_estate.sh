#!/usr/bin/env bash
# Deploy the backend `app/` folder to the VPS (Docker) and run the Real Estate migration.
#
#   ./scripts/deploy_real_estate.sh deploy [--dry-run] [--skip-backup]
#   ./scripts/deploy_real_estate.sh activate        # show the Real Estate category in the apps
#   ./scripts/deploy_real_estate.sh deactivate      # hide it again
#   ./scripts/deploy_real_estate.sh rollback        # restore the code snapshot taken by the last deploy
#
# Config (environment variables; no secrets are stored in this file):
#   DEPLOY_HOST        required, e.g. 76.13.245.174
#   DEPLOY_USER        default: root
#   DEPLOY_PATH        default: /root/am5-backend
#   DEPLOY_CONTAINER   default: am5_backend
#   DEPLOY_PORT        default: 22
#   DEPLOY_KEY         optional path to an SSH private key. Without it ssh asks for the password
#                      ONCE (the connection is reused for every step).
set -euo pipefail

HOST="${DEPLOY_HOST:-}"
USER_="${DEPLOY_USER:-root}"
RPATH="${DEPLOY_PATH:-/root/am5-backend}"
CONTAINER="${DEPLOY_CONTAINER:-am5_backend}"
PORT="${DEPLOY_PORT:-22}"
BACKUPS="\$HOME/am5-backups"

CMD="${1:-}"; shift || true
DRY=0; SKIP_BACKUP=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --skip-backup) SKIP_BACKUP=1 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die()   { red "ERROR: $*"; exit 1; }

[[ -n "$CMD" ]] || { sed -n '2,17p' "$0"; exit 2; }
[[ -n "$HOST" ]] || die "Set DEPLOY_HOST (e.g. export DEPLOY_HOST=76.13.245.174)"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"          # .../am5-backend
CTL="$(mktemp -u /tmp/am5deploy.XXXXXX)"
SSH_OPTS=(-p "$PORT" -o ControlMaster=auto -o "ControlPath=$CTL" -o ControlPersist=15m -o ServerAliveInterval=30)
[[ -n "${DEPLOY_KEY:-}" ]] && SSH_OPTS+=(-i "$DEPLOY_KEY")
TARGET="$USER_@$HOST"

cleanup() { ssh "${SSH_OPTS[@]}" -O exit "$TARGET" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# run a command on the server (printed instead of executed in --dry-run)
remote() {
  if (( DRY )); then echo "   [dry-run] ssh $TARGET: $*"; return 0; fi
  ssh "${SSH_OPTS[@]}" "$TARGET" "$@"
}

confirm() {
  (( DRY )) && return 0
  read -r -p "$1 [type yes to continue] " ans
  [[ "$ans" == "yes" ]] || die "Cancelled."
}

connect() {
  step "Connecting to $TARGET"
  if (( DRY )); then echo "   [dry-run] would open one SSH connection (password asked once)"; return; fi
  ssh "${SSH_OPTS[@]}" "$TARGET" "echo connected as \$(whoami) on \$(hostname)" || die "Cannot connect."
  remote "test -d $RPATH" || die "$RPATH not found on the server"
  remote "docker ps --format '{{.Names}}' | grep -qx $CONTAINER" || die "Container $CONTAINER is not running"
}

# ------------------------------------------------------------------ deploy
do_deploy() {
  step "Pre-flight (local)"
  [[ -d "$ROOT/app/categories/real_estate" ]] || die "Run from the am5-backend repo (app/categories missing)."
  python3 -m compileall -q "$ROOT/app" >/dev/null || die "Python syntax error in app/. Fix before deploying."
  ( cd "$ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null | sed 's/^/   branch: /' || true )
  if [[ -n "$(cd "$ROOT" && git status --porcelain app 2>/dev/null)" ]]; then
    red "   WARNING: app/ has uncommitted changes. Production should match a committed version."
  fi
  echo "   will upload: app/ only (never .env, .venv, scripts, docs, __pycache__)"
  confirm "Deploy to $TARGET:$RPATH (container $CONTAINER)?"

  connect
  TS="$(date +%Y%m%d-%H%M%S)"

  step "1/7 Database backup"
  if (( SKIP_BACKUP )); then
    red "   skipped (--skip-backup)"
  else
    remote "mkdir -p $BACKUPS && cd $RPATH && \
      get() { grep -E \"^\$1=\" .env | tail -1 | cut -d= -f2- | sed -e 's/^[\"'\\'']//' -e 's/[\"'\\'']\$//'; } && \
      command -v pg_dump >/dev/null || { echo 'pg_dump not installed on the server. Install postgresql-client or use --skip-backup after backing up yourself.'; exit 3; } && \
      OUT=$BACKUPS/db-$TS.sql && \
      PGPASSWORD=\"\$(get POSTGRES_PASSWORD)\" pg_dump -h \"\$(get POSTGRES_SERVER)\" -p \"\$(get POSTGRES_PORT)\" -U \"\$(get POSTGRES_USER)\" -f \"\$OUT\" \"\$(get POSTGRES_DB)\" && \
      test \"\$(wc -c < \"\$OUT\")\" -gt 1000 && gzip -f \"\$OUT\" && ls -lh \"\$OUT.gz\"" || { remote "rm -f $BACKUPS/db-$TS.sql $BACKUPS/db-$TS.sql.gz" || true; die "Database backup failed or is empty. Nothing was changed."; }
    (( DRY )) || green "   backup saved on the server: $BACKUPS/db-$TS.sql.gz"
  fi

  step "2/7 Snapshot current code (for rollback)"
  remote "mkdir -p $BACKUPS && cd $RPATH && tar czf $BACKUPS/app-$TS.tgz app && ls -lh $BACKUPS/app-$TS.tgz" || die "Snapshot failed."

  step "3/7 Upload app/ (rsync)"
  RSYNC_SSH="ssh ${SSH_OPTS[*]}"
  RS=(rsync -az --info=stats1 --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' --exclude '.env' --exclude 'tests/' -e "$RSYNC_SSH")
  if (( DRY )); then
    echo "   [dry-run] ${RS[*]} $ROOT/app/ $TARGET:$RPATH/app/"
  else
    "${RS[@]}" "$ROOT/app/" "$TARGET:$RPATH/app/" || die "Upload failed."
  fi

  step "4/7 Check the container sees the new code"
  if (( DRY )); then
    echo "   [dry-run] docker exec $CONTAINER test -f /app/app/categories/registry.py (else docker cp)"
  elif ! remote "docker exec $CONTAINER test -f /app/app/categories/registry.py"; then
    echo "   bind mount not active; copying into the container"
    remote "docker cp $RPATH/app/. $CONTAINER:/app/app/" || die "docker cp failed."
    remote "docker exec $CONTAINER test -f /app/app/categories/registry.py" || die "New code still not in the container."
  fi
  (( DRY )) || green "   ok"

  step "5/7 Run the migration (columns, tables, seed). Real Estate stays HIDDEN."
  remote "docker exec $CONTAINER python -m app.db.migrate_real_estate" || die "Migration failed. The new code is uploaded but the running API was NOT restarted and still uses the old code. Fix the problem and re-run deploy BEFORE anything restarts the container."

  step "6/7 Restart and health check"
  remote "docker restart $CONTAINER >/dev/null"
  if (( DRY )); then echo "   [dry-run] poll http://localhost:8000/health for up to 60s"; else
    ok=0
    for i in $(seq 1 30); do
      if remote "curl -fsS http://localhost:8000/health >/dev/null"; then ok=1; break; fi
      sleep 2
    done
    (( ok )) || { red "Health check failed after restart."; echo "   Roll back with: DEPLOY_HOST=$HOST $0 rollback"; exit 1; }
    green "   /health ok"
  fi

  step "7/7 Verify"
  remote "curl -fsS http://localhost:8000/api/v1/openapi.json | grep -c '/real-estate/master' | sed 's/^/   real-estate routes registered in OpenAPI: /'"
  echo "   startup errors in the last 200 log lines (should be none for the two category_* keys):"
  remote "docker logs --tail 200 $CONTAINER 2>&1 | grep -E 'category_migration_error|category_seed_error' || echo '   none'"
  echo "   note: 'db_table_init_error' may appear. It is an older, separate startup issue."

  (( DRY )) && { green "
DRY RUN: nothing was executed. Remove --dry-run to deploy."; return; }
  (( SKIP_BACKUP )) && BK="(skipped)" || BK="$BACKUPS/db-$TS.sql.gz"
  green "
Deployed.  Backup: $BK   Code snapshot: $BACKUPS/app-$TS.tgz
The Real Estate category is HIDDEN from the apps. When the app and panel releases are live:
   DEPLOY_HOST=$HOST $0 activate"
}

# ------------------------------------------------------------ activate etc.
do_toggle() {   # $1 = --activate | --deactivate
  connect
  confirm "Run 'migrate_real_estate $1' on $TARGET?"
  remote "docker exec $CONTAINER python -m app.db.migrate_real_estate $1" || die "Failed."
}

do_rollback() {
  connect
  step "Latest code snapshot"
  LATEST="$(remote "ls -1t $BACKUPS/app-*.tgz 2>/dev/null | head -1" || true)"
  (( DRY )) && LATEST="$BACKUPS/app-<latest>.tgz"
  [[ -n "$LATEST" ]] || die "No snapshot found in $BACKUPS"
  echo "   $LATEST"
  confirm "Restore this snapshot and restart $CONTAINER? (the database is NOT rolled back; the new tables and columns are harmless to old code)"
  remote "cd $RPATH && rm -rf app.rollback-tmp && mkdir app.rollback-tmp && tar xzf $LATEST -C app.rollback-tmp && rsync -a --delete app.rollback-tmp/app/ app/ && rm -rf app.rollback-tmp"
  remote "docker cp $RPATH/app/. $CONTAINER:/app/app/ >/dev/null 2>&1 || true; docker restart $CONTAINER >/dev/null"
  green "Rolled back. Check: ssh $TARGET 'curl -s localhost:8000/health'"
}

case "$CMD" in
  deploy)     do_deploy ;;
  activate)   do_toggle --activate ;;
  deactivate) do_toggle --deactivate ;;
  rollback)   do_rollback ;;
  *) die "Unknown command '$CMD' (use deploy | activate | deactivate | rollback)" ;;
esac
