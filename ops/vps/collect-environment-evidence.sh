#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
RESTORE_MARKER="${RESTORE_MARKER:-$BACKUP_ROOT/restore-tests/LAST_SUCCESS}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-85}"
OUTPUT="${ENVIRONMENT_EVIDENCE_FILE:-$ROOT_DIR/.deploy/evidence/environment.json}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
psql_scalar() {
  printf '%s\n' "$1" | "${COMPOSE[@]}" exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}
unsafe_tables="$(psql_scalar "select count(*) from information_schema.role_table_grants where table_schema='public' and grantee in ('PUBLIC','anon','authenticated');")"
unsafe_functions="$(psql_scalar "select count(*) from information_schema.routine_privileges where specific_schema='public' and grantee in ('PUBLIC','anon','authenticated');")"
without_rls="$(psql_scalar "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p') and not c.relrowsecurity;")"
disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
latest_backup="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -1560 -print -quit 2>/dev/null || true)"
backup_ok=false; [[ -n "$latest_backup" ]] && backup_ok=true
restore_ok=false; restore_detail=""
if [[ -f "$RESTORE_MARKER" && -n "$(find "$RESTORE_MARKER" -mmin -43200 -print -quit 2>/dev/null)" ]]; then
  restore_ok=true; restore_detail="$(tr -d '\r\n' < "$RESTORE_MARKER")"
fi
python3 ops/vps/environment_evidence.py collect \
  --output "$OUTPUT" --disk-percent "$disk_used" --disk-limit "$DISK_MAX_PERCENT" \
  --unsafe-table-grants "$unsafe_tables" --unsafe-function-grants "$unsafe_functions" \
  --tables-without-rls "$without_rls" --backup-ok "$backup_ok" \
  --backup-detail "$latest_backup" --restore-ok "$restore_ok" --restore-detail "$restore_detail"
