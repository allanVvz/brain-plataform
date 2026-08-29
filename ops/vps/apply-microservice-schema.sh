#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${1:?usage: apply-microservice-schema.sh MANIFEST [--apply]}"
ACTION="${2:---dry-run}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
MIGRATION="$ROOT_DIR/supabase/migrations/131_microservice_role_grants.sql"
COMPOSE=(docker compose --env-file "$ENV_FILE")
cd "$ROOT_DIR"

[[ "$ACTION" == "--dry-run" || "$ACTION" == "--apply" ]] || { echo "invalid action" >&2; exit 2; }
python3 ops/microservices/validate-release-manifest.py "$MANIFEST"
test -s "$MIGRATION"
test -s "$ENV_FILE"

applied="$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' <<'SQL'
select count(*) from public._compose_migrations where filename='131_microservice_role_grants.sql';
SQL
)"
[[ "$applied" =~ ^[01]$ ]] || { echo "invalid migration ledger state" >&2; exit 1; }
echo "schema_preflight migration_131_applied=$applied action=$ACTION"
[[ "$ACTION" == "--apply" ]] || exit 0

candidate_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_sha"])' "$MANIFEST")"
previous_sha="$(tr -d '\r\n' < .deploy/release-source-sha)"
python3 ops/vps/release_lifecycle.py prepare \
  --candidate-sha "$candidate_sha" --previous-sha "$previous_sha" \
  --impact-class migration --pause-reason "authorized initial microservice cutover" \
  --force --force-reason "owner authorized migration 131 and cutover" >/dev/null
python3 ops/vps/release_lifecycle.py pause-claims --reason "authorized initial microservice cutover" >/dev/null
"${COMPOSE[@]}" stop -t 180 workers
bash ops/vps/drain-worker-claims.sh

bash ops/vps/backup.sh
backup_dir="$(realpath /var/backups/brain-ai/latest)"
restore_db="brain_restore_cutover_$(date -u +%Y%m%d%H%M%S)"
bash ops/vps/restore.sh "$backup_dir" "$restore_db" --confirm-isolated-restore

if [[ "$applied" == "0" ]]; then
  {
    cat "$MIGRATION"
    printf "\ninsert into public._compose_migrations(filename) values ('131_microservice_role_grants.sql') on conflict do nothing;\n"
  } | "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction'
fi

python3 ops/microservices/bootstrap-service-envs.py
verification="$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq' <<'SQL'
select count(*) from pg_roles
where rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport')
  and not rolcanlogin and rolbypassrls;
select count(*) from pg_auth_members m
join pg_roles granted on granted.oid=m.roleid
join pg_roles member on member.oid=m.member
where member.rolname='authenticator'
  and granted.rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport');
select count(*) from public._compose_migrations where filename='131_microservice_role_grants.sql';
SQL
)"
[[ "$verification" == $'4\n4\n1' ]] || {
  echo "migration verification failed" >&2
  exit 1
}
python3 ops/vps/release_lifecycle.py advance --stage migration_complete \
  --gate migration_131=true --gate backup_verified=true --gate isolated_restore=true \
  --gate global_claims_paused=true >/dev/null
echo "schema_apply_complete migration=131 workers=paused"
