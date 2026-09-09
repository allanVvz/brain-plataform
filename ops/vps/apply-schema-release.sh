#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${1:?usage: apply-schema-release.sh MANIFEST PLAN [--dry-run|--apply]}"
PLAN="${2:?usage: apply-schema-release.sh MANIFEST PLAN [--dry-run|--apply]}"
ACTION="${3:---dry-run}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
COMPOSE=(docker compose --env-file "$ENV_FILE")
cd "$ROOT_DIR"

[[ "$ACTION" == "--dry-run" || "$ACTION" == "--apply" ]] || {
  echo "invalid action" >&2
  exit 2
}
test -s "$MANIFEST"
test -s "$PLAN"
test -s "$ENV_FILE"
python3 ops/microservices/validate-release-manifest.py "$MANIFEST"

validated_files="$(mktemp)"
applied_files="$(mktemp)"
pending_files="$(mktemp)"
combined_sql="$(mktemp)"
cleanup() {
  rm -f "$validated_files" "$applied_files" "$pending_files" "$combined_sql"
}
trap cleanup EXIT

# The plan is the immutable contract produced by the dry-run job. Validate its
# complete inventory against the checked-out bytes before looking at production.
python3 - "$MANIFEST" "$PLAN" "$validated_files" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

manifest_path, plan_path, output_path = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
plan = json.loads(plan_path.read_text(encoding="utf-8"))
entries = plan.get("migrations") or []
assert plan.get("schema_version") == manifest.get("schema_version"), "plan/manifest schema mismatch"
assert entries and plan.get("target_migration") == entries[-1].get("filename"), "invalid target migration"
assert plan.get("migration_count") == len(entries), "invalid migration count"

seen_versions: set[int] = set()
inventory = hashlib.sha256()
filenames: list[str] = []
for entry in entries:
    version = entry.get("version")
    filename = entry.get("filename")
    assert isinstance(version, int) and version not in seen_versions, "duplicate/invalid migration version"
    assert isinstance(filename, str) and re.fullmatch(r"\d{3}_[a-z0-9_]+\.sql", filename), "unsafe migration filename"
    assert int(filename[:3]) == version, "migration version/filename mismatch"
    path = Path("supabase/migrations") / filename
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert content_hash == entry.get("sha256"), f"migration checksum mismatch: {filename}"
    inventory.update(f"{filename}\0{content_hash}\n".encode())
    seen_versions.add(version)
    filenames.append(filename)

assert "sha256:" + inventory.hexdigest() == plan.get("inventory_checksum"), "inventory checksum mismatch"
assert entries[-1]["version"] == manifest["schema_version"], "plan does not end at manifest schema"
output_path.write_text("\n".join(filenames) + "\n", encoding="utf-8")
PY

"${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1' <<'SQL' > "$applied_files"
select filename from public._compose_migrations order by filename;
SQL

current_schema="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1' <<'SQL'
select coalesce(max((substring(filename from '^[0-9]+'))::int), 0)
from public._compose_migrations;
SQL
)"
[[ "$current_schema" =~ ^[0-9]+$ ]] || { echo "invalid current schema" >&2; exit 1; }
target_schema="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["schema_version"])' "$MANIFEST")"
if (( current_schema > target_schema )); then
  echo "production schema is ahead of authorized target: current=$current_schema target=$target_schema" >&2
  exit 1
fi

while IFS= read -r filename; do
  if grep -Fxq "$filename" "$applied_files"; then
    continue
  fi
  version="${filename%%_*}"
  if (( 10#$version <= current_schema )); then
    echo "schema history gap below current version: $filename current=$current_schema" >&2
    exit 1
  fi
  printf '%s\n' "$filename" >> "$pending_files"
done < "$validated_files"

pending_count="$(wc -l < "$pending_files" | tr -d ' ')"
echo "schema_preflight current=$current_schema target=$target_schema pending=$pending_count action=$ACTION"
while IFS= read -r filename; do
  [[ -n "$filename" ]] || continue
  checksum="$(sha256sum "supabase/migrations/$filename" | awk '{print "sha256:" $1}')"
  echo "schema_pending migration=$filename checksum=$checksum"
done < "$pending_files"

[[ "$ACTION" == "--apply" ]] || exit 0

python3 - <<'PY'
import json
state = json.load(open('.deploy/control/claims-paused.json', encoding='utf-8'))
assert state.get('paused') is True, 'global claims must remain paused'
PY

if (( pending_count == 0 )); then
  echo "schema_apply_complete current=$current_schema target=$target_schema pending=0 global_claims_paused=true"
  exit 0
fi

# A single-transaction release cannot safely contain statements that escape
# or control the transaction. Future migrations using those constructs need a
# separately reviewed executor instead of silently weakening atomicity.
python3 ops/microservices/validate-atomic-migrations.py "$pending_files"

# A release-specific backup and isolated restore proof are mandatory even when
# another fresh operational backup exists. No production schema is changed
# before this proof succeeds.
bash ops/vps/backup.sh
backup_dir="$(realpath /var/backups/brain-ai/latest)"
restore_db="brain_restore_schema${target_schema}_$(date -u +%Y%m%d%H%M%S)"
bash ops/vps/restore.sh "$backup_dir" "$restore_db" --confirm-isolated-restore

while IFS= read -r filename; do
  [[ -n "$filename" ]] || continue
  cat "supabase/migrations/$filename" >> "$combined_sql"
  printf "\ninsert into public._compose_migrations(filename) values ('%s') on conflict do nothing;\n" "$filename" >> "$combined_sql"
done < "$pending_files"

"${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction' \
  < "$combined_sql"

missing_after="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1' <<SQL
select count(*)
from (values $(sed "s/.*/('&'),/" "$pending_files" | sed '$ s/,$//')) as expected(filename)
where not exists (
  select 1 from public._compose_migrations applied
  where applied.filename=expected.filename
);
SQL
)"
[[ "$missing_after" == "0" ]] || { echo "schema verification failed missing=$missing_after" >&2; exit 1; }
echo "schema_apply_complete previous=$current_schema target=$target_schema applied=$pending_count backup=$backup_dir isolated_restore=true global_claims_paused=true"
