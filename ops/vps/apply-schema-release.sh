#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${1:?usage: apply-schema-release.sh MANIFEST [--apply]}"
ACTION="${2:---dry-run}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
COMPOSE=(docker compose --env-file "$ENV_FILE")
cd "$ROOT_DIR"

[[ "$ACTION" == "--dry-run" || "$ACTION" == "--apply" ]] || {
  echo "invalid action" >&2
  exit 2
}
python3 ops/microservices/validate-release-manifest.py "$MANIFEST"
test -s "$ENV_FILE"

target_schema="$(python3 - "$MANIFEST" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["schema_version"]))
PY
)"
mapfile -t release_migrations < <(python3 - "$target_schema" <<'PY'
import re, sys
from pathlib import Path

target = int(sys.argv[1])
pattern = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
for path in sorted(Path("supabase/migrations").glob("*.sql")):
    match = pattern.fullmatch(path.name)
    if match and 132 <= int(match.group(1)) <= target:
        print(path.name)
PY
)
[[ ${#release_migrations[@]} -gt 0 ]] || {
  echo "no release migrations found through schema $target_schema" >&2
  exit 1
}
[[ "${release_migrations[-1]}" == "${target_schema}_"*.sql ]] || {
  echo "target migration $target_schema is missing" >&2
  exit 1
}

mapfile -t applied_migrations < <(
  "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<SQL
select filename from public._compose_migrations
where (substring(filename from '^[0-9]+'))::int between 132 and $target_schema
order by filename;
SQL
)
declare -A applied=()
for filename in "${applied_migrations[@]}"; do applied["$filename"]=1; done
pending=()
for filename in "${release_migrations[@]}"; do
  [[ -n "${applied[$filename]:-}" ]] || pending+=("$filename")
done

inventory_checksum="$(for filename in "${release_migrations[@]}"; do sha256sum "supabase/migrations/$filename"; done | sha256sum | awk '{print "sha256:" $1}')"
echo "schema_preflight target=$target_schema inventory_checksum=$inventory_checksum applied=${#applied_migrations[@]} pending=${#pending[@]} action=$ACTION"
printf 'schema_migration filename=%s state=applied\n' "${applied_migrations[@]}"
printf 'schema_migration filename=%s state=pending\n' "${pending[@]}"
[[ "$ACTION" == "--apply" ]] || exit 0

python3 - <<'PY'
import json
state = json.load(open('.deploy/control/claims-paused.json', encoding='utf-8'))
assert state.get('paused') is True, 'global claims must remain paused'
PY

bash ops/vps/backup.sh
backup_dir="$(realpath /var/backups/brain-ai/latest)"
restore_db="brain_restore_schema${target_schema}_$(date -u +%Y%m%d%H%M%S)"
bash ops/vps/restore.sh "$backup_dir" "$restore_db" --confirm-isolated-restore

if [[ ${#pending[@]} -gt 0 ]]; then
  migration_batch="$(mktemp)"
  trap 'rm -f "$migration_batch"' EXIT
  for filename in "${pending[@]}"; do
    cat "supabase/migrations/$filename" >> "$migration_batch"
    printf "\ninsert into public._compose_migrations(filename) values ('%s') on conflict do nothing;\n" "$filename" >> "$migration_batch"
  done
  "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction' \
    < "$migration_batch"
fi

verification="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<SQL
select count(*) from public._compose_migrations
where filename in ($(printf "'%s'," "${release_migrations[@]}" | sed 's/,$//'));
select has_function_privilege('brain_runtime', 'public.cosine_distance(vector,vector)', 'EXECUTE')::int;
select has_schema_privilege('brain_control_plane', 'storage', 'USAGE')::int;
select has_table_privilege('brain_control_plane', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE')::int;
select has_schema_privilege('brain_transport', 'storage', 'USAGE')::int;
select has_table_privilege('brain_transport', 'storage.objects', 'SELECT,INSERT,UPDATE')::int;
select has_table_privilege('brain_runtime', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE')::int;
select has_table_privilege('brain_gateway', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE')::int;
SQL
)"
expected_count="${#release_migrations[@]}"
[[ "$verification" == "$expected_count"$'\n1\n1\n1\n1\n1\n0\n0' ]] || {
  echo "schema $target_schema verification failed" >&2
  exit 1
}
echo "schema_apply_complete target=$target_schema backup_verified=true isolated_restore=true global_claims_paused=true"
