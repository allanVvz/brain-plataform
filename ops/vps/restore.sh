#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_DIR="${1:-}"
TARGET_DB="${2:-}"
CONFIRM="${3:-}"
SCHEMA_SQL="${5:-}"
GRAPH_REHEARSAL="${6:-}"
[[ "$CONFIRM" == "--confirm-isolated-restore" ]] || {
  echo "usage: restore.sh <backup-dir> <isolated-target-db> --confirm-isolated-restore" >&2
  exit 2
}
[[ "$TARGET_DB" =~ ^brain_restore_[a-z0-9_]{1,40}$ ]] || {
  echo "Target must be an isolated brain_restore_* database" >&2; exit 2;
}
if [[ -n "${4:-}" ]]; then
  [[ "$4" == "--rehearse-schema" && -f "$SCHEMA_SQL" && -r "$SCHEMA_SQL" ]] || {
    echo "Invalid isolated schema rehearsal arguments" >&2; exit 2;
  }
  [[ -z "$GRAPH_REHEARSAL" || "$GRAPH_REHEARSAL" == "--graph-editor-rehearsal" ]] || {
    echo "Unknown isolated rehearsal" >&2; exit 2;
  }
elif [[ -n "$SCHEMA_SQL$GRAPH_REHEARSAL" ]]; then
  echo "Schema rehearsal requires --rehearse-schema" >&2; exit 2;
fi
[[ $# -le 6 ]] || { echo "Unexpected restore arguments" >&2; exit 2; }
BACKUP_DIR="$(realpath "$BACKUP_DIR")"
[[ -d "$BACKUP_DIR" && -f "$BACKUP_DIR/postgres-data.dump" \
   && -f "$BACKUP_DIR/postgres-schema.dump" && -f "$BACKUP_DIR/SHA256SUMS" ]] || {
  echo "Invalid data-only backup directory" >&2; exit 2;
}
(cd "$BACKUP_DIR" && sha256sum --check SHA256SUMS)
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
active_db="$("${COMPOSE[@]}" exec -T db sh -c 'printf %s "$POSTGRES_DB"')"
[[ "$TARGET_DB" != "$active_db" ]] || { echo "Refusing active database target" >&2; exit 2; }

"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" createdb -U "$POSTGRES_USER" '"$TARGET_DB"
cleanup() {
  "${COMPOSE[@]}" exec -T db sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" dropdb -U "$POSTGRES_USER" --if-exists '"$TARGET_DB" >/dev/null
}
trap cleanup EXIT

"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d '"$TARGET_DB"' --schema-only --no-owner --exit-on-error' \
  < "$BACKUP_DIR/postgres-schema.dump"
"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d '"$TARGET_DB"' --data-only --disable-triggers --no-owner --exit-on-error' \
  < "$BACKUP_DIR/postgres-data.dump"
"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d '"$TARGET_DB"' -v ON_ERROR_STOP=1 -Atc "select count(*) from personas; select count(*) from messages;"'

# Rehearse while the disposable database still exists. EXIT always removes it,
# including when the migration or its contract proof fails.
if [[ -n "$SCHEMA_SQL" ]]; then
  "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 --single-transaction' sh "$TARGET_DB" \
    < "$SCHEMA_SQL"
  if [[ "$GRAPH_REHEARSAL" == "--graph-editor-rehearsal" ]]; then
    bash ops/vps/rehearse-graph-editor-schema.sh "$TARGET_DB"
  fi
fi

marker_root="${RESTORE_MARKER_ROOT:-/var/backups/brain-ai/restore-tests}"
mkdir -p "$marker_root"
printf '%s backup=%s target=%s\n' "$(date -u +%FT%TZ)" "$BACKUP_DIR" "$TARGET_DB" \
  > "$marker_root/LAST_SUCCESS"
echo "Controlled restore verified; isolated database will be dropped."
