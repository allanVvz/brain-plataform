#!/usr/bin/env bash
set -Eeuo pipefail

# Nightly snapshot refresh: dumps prod's Postgres and restores it into QA's,
# so QA always tests against real (if slightly stale) production data. Prod
# is only ever read from (pg_dump), never written to. No-ops safely if the
# QA stack isn't running (e.g. after qa-down.sh) so a stale cron entry never
# has to wake prod up or fail loudly.
#
# Intentionally standalone rather than reusing backup.sh/restore.sh: those
# are prod-only tooling (hardcoded `com.docker.compose.project=brain-ai`
# volume-label filters) and this only needs pg_dump/pg_restore, not the
# volume tar/restore they also do.
#
# Scheduled from the QA checkout, e.g.:
#   0 4 * * * /opt/brain-ai-qa/ops/vps/qa-refresh-db.sh >> /var/log/brain-ai-qa-refresh.log 2>&1

QA_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
QA_ENV_FILE="${QA_ENV_FILE:-$QA_ROOT_DIR/.env.compose}"
PROD_ROOT_DIR="${PROD_ROOT_DIR:-/opt/brain-ai}"
PROD_ENV_FILE="${PROD_ENV_FILE:-$PROD_ROOT_DIR/.env.compose}"

qa_running="$(cd "$QA_ROOT_DIR" && docker compose --env-file "$QA_ENV_FILE" ps -q db)"
if [[ -z "$qa_running" ]]; then
  echo "QA db is not running; skipping refresh."
  exit 0
fi

DUMP_FILE="$(mktemp)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo "Dumping prod database..."
(
  cd "$PROD_ROOT_DIR"
  docker compose --env-file "$PROD_ENV_FILE" exec -T db sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc'
) > "$DUMP_FILE"

echo "Restoring into QA database..."
(
  cd "$QA_ROOT_DIR"
  docker compose --env-file "$QA_ENV_FILE" exec -T db sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner'
) < "$DUMP_FILE"

echo "QA database refreshed from prod at $(date -u +%FT%TZ)."
