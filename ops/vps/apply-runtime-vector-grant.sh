#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${1:?usage: apply-runtime-vector-grant.sh MANIFEST [--apply]}"
ACTION="${2:---dry-run}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
MIGRATION_NAME="132_runtime_vector_distance_grant.sql"
MIGRATION="$ROOT_DIR/supabase/migrations/$MIGRATION_NAME"
COMPOSE=(docker compose --env-file "$ENV_FILE")
cd "$ROOT_DIR"

[[ "$ACTION" == "--dry-run" || "$ACTION" == "--apply" ]] || {
  echo "invalid action" >&2
  exit 2
}
python3 ops/microservices/validate-release-manifest.py "$MANIFEST"
test -s "$MIGRATION"
test -s "$ENV_FILE"
python3 - "$MANIFEST" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["schema_version"] == 132, "manifest must target schema 132"
PY

read -r applied executable current_schema < <(
  "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -F " "' <<'SQL'
select
  (select count(*) from public._compose_migrations where filename='132_runtime_vector_distance_grant.sql'),
  has_function_privilege('brain_runtime', 'public.cosine_distance(vector,vector)', 'EXECUTE')::int,
  coalesce((select max((substring(filename from '^[0-9]+'))::int) from public._compose_migrations), 0);
SQL
)
[[ "$applied" =~ ^[01]$ && "$executable" =~ ^[01]$ && "$current_schema" =~ ^[0-9]+$ ]] || {
  echo "invalid schema preflight result" >&2
  exit 1
}
checksum="$(sha256sum "$MIGRATION" | awk '{print "sha256:" $1}')"
echo "schema_preflight migration=$MIGRATION_NAME checksum=$checksum applied=$applied execute_grant=$executable current_schema=$current_schema action=$ACTION"
[[ "$ACTION" == "--apply" ]] || exit 0

python3 - <<'PY'
import json
state = json.load(open('.deploy/control/claims-paused.json', encoding='utf-8'))
assert state.get('paused') is True, 'global claims must remain paused'
PY
[[ "$current_schema" == "131" || "$applied" == "1" ]] || {
  echo "schema must advance exactly from 131 to 132" >&2
  exit 1
}

bash ops/vps/backup.sh
backup_dir="$(realpath /var/backups/brain-ai/latest)"
restore_db="brain_restore_schema132_$(date -u +%Y%m%d%H%M%S)"
bash ops/vps/restore.sh "$backup_dir" "$restore_db" --confirm-isolated-restore

if [[ "$applied" == "0" ]]; then
  {
    cat "$MIGRATION"
    printf "\ninsert into public._compose_migrations(filename) values ('%s') on conflict do nothing;\n" "$MIGRATION_NAME"
  } | "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction'
fi

verification="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<'SQL'
select count(*) from public._compose_migrations where filename='132_runtime_vector_distance_grant.sql';
select has_function_privilege('brain_runtime', 'public.cosine_distance(vector,vector)', 'EXECUTE')::int;
SQL
)"
[[ "$verification" == $'1\n1' ]] || {
  echo "schema 132 verification failed" >&2
  exit 1
}
echo "schema_apply_complete migration=132 backup_verified=true isolated_restore=true global_claims_paused=true"
