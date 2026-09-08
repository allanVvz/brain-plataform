#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPERATION_ROOT="${OPERATION_ROOT:-/opt/brain-ai}"
MANIFEST="${1:?usage: apply-schema-plan.sh MANIFEST PLAN [--apply]}"
PLAN="${2:?usage: apply-schema-plan.sh MANIFEST PLAN [--apply]}"
ACTION="${3:---dry-run}"
ENV_FILE="${ENV_FILE:-$OPERATION_ROOT/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
RESTORE_MARKER="${RESTORE_MARKER:-$BACKUP_ROOT/restore-tests/LAST_SUCCESS}"
COMPOSE=(docker compose -p brain-ai --project-directory "$OPERATION_ROOT" --env-file "$ENV_FILE" -f "$OPERATION_ROOT/docker-compose.yml")

[[ "$ACTION" == "--dry-run" || "$ACTION" == "--apply" ]] || {
  echo "expected --dry-run or --apply" >&2; exit 2;
}
cd "$ROOT_DIR"
mkdir -p .deploy
python3 ops/microservices/validate-release-manifest.py "$MANIFEST"
python3 ops/microservices/plan-schema-release.py "$MANIFEST" > .deploy/schema-plan.actual.json
python3 - "$PLAN" .deploy/schema-plan.actual.json <<'PY'
import json, sys
approved = json.load(open(sys.argv[1], encoding="utf-8"))
actual = json.load(open(sys.argv[2], encoding="utf-8"))
if approved != actual:
    raise SystemExit("schema plan does not match installed release")
PY

target="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["schema_version"])' "$PLAN")"
current="$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<'SQL'
select coalesce(max((substring(filename from '^[0-9]+'))::int), 0)
from public._compose_migrations;
SQL
)"
[[ "$current" =~ ^[0-9]+$ && "$target" =~ ^[0-9]+$ ]] || {
  echo "invalid schema versions current=$current target=$target" >&2; exit 1;
}
(( current <= target )) || { echo "database schema is newer than release" >&2; exit 1; }

mapfile -t pending < <(python3 - "$PLAN" "$current" <<'PY'
import json, re, sys
plan, current = json.load(open(sys.argv[1], encoding="utf-8")), int(sys.argv[2])
for row in plan["migrations"]:
    if row["version"] > current:
        if not re.fullmatch(r"[0-9]{3}_[a-z0-9_]+\.sql", row["filename"]):
            raise SystemExit("invalid migration filename")
        print(f'{row["filename"]}\t{row["sha256"]}')
PY
)
printf 'schema_preflight current=%s target=%s pending=%s action=%s\n' \
  "$current" "$target" "${#pending[@]}" "$ACTION"
for row in "${pending[@]}"; do
  IFS=$'\t' read -r filename expected <<<"$row"
  actual="$(sha256sum "supabase/migrations/$filename" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || { echo "migration checksum mismatch: $filename" >&2; exit 1; }
  printf 'pending_migration=%s sha256=%s\n' "$filename" "$actual"
done
[[ "$ACTION" == "--apply" ]] || exit 0

OPERATION_ROOT="$OPERATION_ROOT" python3 - <<'PY'
import json
import os
state = json.load(open(os.path.join(os.environ['OPERATION_ROOT'], '.deploy/control/claims-paused.json'), encoding='utf-8'))
assert state.get('paused') is True, 'global claims must remain paused'
PY
find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -1560 -print -quit | grep -q . || {
  echo "fresh data-only backup is required" >&2; exit 1;
}
[[ -s "$RESTORE_MARKER" ]] && find "$RESTORE_MARKER" -mtime -30 -print -quit | grep -q . || {
  echo "controlled restore proof is missing or stale" >&2; exit 1;
}

if ((${#pending[@]})); then
  {
    for row in "${pending[@]}"; do
      IFS=$'\t' read -r filename _ <<<"$row"
      cat "supabase/migrations/$filename"
      printf "\ninsert into public._compose_migrations(filename) values ('%s') on conflict do nothing;\n" "$filename"
    done
  } | "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction'
fi

verified="$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<'SQL'
select coalesce(max((substring(filename from '^[0-9]+'))::int), 0)
from public._compose_migrations;
SQL
)"
[[ "$verified" == "$target" ]] || { echo "schema verification failed: $verified" >&2; exit 1; }
echo "schema_apply_complete version=$verified claims=paused"
