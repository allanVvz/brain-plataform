#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)
active_api_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active_api_service" == "api-candidate" ]] || active_api_service=api
impact_class="$(python3 ops/vps/release_lifecycle.py show --field impact_class 2>/dev/null || true)"
release_class="$(python3 ops/vps/release_lifecycle.py show --field release_class 2>/dev/null || true)"
backup_mode="$(python3 ops/vps/release_lifecycle.py show --field backup_mode 2>/dev/null || true)"
require_fresh_backup="${REQUIRE_FRESH_BACKUP:-}"
if [[ -z "$require_fresh_backup" ]]; then
  if [[ "$backup_mode" == "fresh_required" ]]; then
    require_fresh_backup=true
  elif [[ -n "$impact_class" ]]; then
    require_fresh_backup=false
  else
    # A standalone audit without durable release context remains fail closed.
    require_fresh_backup=true
  fi
fi
[[ "$require_fresh_backup" == "true" || "$require_fresh_backup" == "false" ]] || {
  echo "REQUIRE_FRESH_BACKUP must be true or false" >&2
  exit 2
}
failed=0

check_file() {
  local path="$1" label="$2"
  if [[ -s "$path" ]]; then printf 'PASS\t%s\t%s\n' "$label" "$path"
  else printf 'FAIL\t%s\t%s\n' "$label" "$path"; failed=1; fi
}

check_file .deploy/release-source-sha release_source_sha
check_file .deploy/release-directory release_directory
if [[ -n "${EXPECTED_RELEASE_SHA:-}" && -s .deploy/release-source-sha ]]; then
  installed_sha="$(tr -d '\r\n' < .deploy/release-source-sha)"
  if [[ "$installed_sha" == "$EXPECTED_RELEASE_SHA" ]]; then
    printf 'PASS\trelease_source_identity\t%s\n' "$installed_sha"
  else
    printf 'FAIL\trelease_source_identity\texpected=%s installed=%s\n' \
      "$EXPECTED_RELEASE_SHA" "$installed_sha"
    failed=1
  fi
fi
if [[ -s .deploy/release-directory ]]; then
  release_dir="$(tr -d '\r\n' < .deploy/release-directory)"
  if [[ -d "$release_dir" && -f "$release_dir/SHA256SUMS" ]] \
     && (cd "$release_dir" && sha256sum --check --quiet SHA256SUMS); then
    printf 'PASS\trelease_checksums\t%s\n' "$release_dir"
  else
    printf 'FAIL\trelease_checksums\t%s\n' "$release_dir"; failed=1
  fi
fi

check_container_digest() {
  local service="$1" digest_file="$2" expected cid image_id
  if [[ ! -s "$digest_file" ]]; then
    printf 'FAIL\t%s_digest\tmissing evidence\n' "$service"; failed=1; return
  fi
  expected="$(tr -d '\r\n' < "$digest_file")"
  if [[ ! "$expected" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'FAIL\t%s_digest\tunresolved\n' "$service"; failed=1; return
  fi
  cid="$("${COMPOSE_BG[@]}" ps -q "$service")"
  if [[ -z "$cid" ]]; then
    printf 'FAIL\t%s_digest\tcontainer missing\n' "$service"; failed=1; return
  fi
  image_id="$(docker inspect -f '{{.Image}}' "$cid")"
  if docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id" | grep -Fq "@$expected"; then
    printf 'PASS\t%s_digest\t%s\n' "$service" "$expected"
  else
    printf 'FAIL\t%s_digest\texpected=%s\n' "$service" "$expected"; failed=1
  fi
}
check_container_digest "$active_api_service" .deploy/release-api-digest
if [[ "$release_class" == "runtime" ]]; then
  check_container_digest workers .deploy/release-worker-digest
fi

"${COMPOSE[@]}" ps
evidence_file="${ENVIRONMENT_EVIDENCE_FILE:-$ROOT_DIR/.deploy/evidence/environment.json}"
evidence_args=(verify --input "$evidence_file" --max-age-hours "${ENVIRONMENT_EVIDENCE_MAX_AGE_HOURS:-26}")
if [[ "$release_class" == "runtime" ]]; then
  if python3 ops/vps/environment_evidence.py "${evidence_args[@]}" --strict; then
    printf 'PASS\tenvironment_evidence\t%s\n' "$evidence_file"
  else
    printf 'FAIL\tenvironment_evidence\tmissing, stale or unhealthy\n'
    failed=1
  fi
else
  evidence_result="$(python3 ops/vps/environment_evidence.py "${evidence_args[@]}")"
  if [[ "$evidence_result" == *'"ok": true'* ]]; then
    printf 'PASS\tenvironment_evidence\t%s\n' "$evidence_file"
  else
    printf 'WARN\tenvironment_evidence\t%s\n' "$evidence_result"
  fi
fi
if [[ "$impact_class" == "migration" ]]; then
  [[ -n "${release_dir:-}" && -s "$release_dir/MIGRATION_MANIFEST.json" ]] || {
    printf 'FAIL\tmigration_manifest\tmissing from installed release\n'
    failed=1
  }
  if [[ -n "${release_dir:-}" && -s "$release_dir/MIGRATION_MANIFEST.json" ]]; then
    applied_file="$(mktemp)"
    trap 'rm -f -- "${applied_file:-}"' EXIT
    "${COMPOSE[@]}" exec -T db sh -c \
      'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq -c "select filename from public._compose_migrations order by filename"' \
      > "$applied_file"
    if python3 "$release_dir/scripts/migration_manifest.py" verify-applied \
      --manifest "$release_dir/MIGRATION_MANIFEST.json" --applied "$applied_file"; then
      printf 'PASS\tmigration_manifest\tdynamic runner manifest satisfied\n'
    else
      printf 'FAIL\tmigration_manifest\tledger is behind runner manifest\n'
      failed=1
    fi
  fi
fi
if [[ "$release_class" == "runtime" ]]; then
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -P pager=off' <<'SQL'
select 'cas_conflicts_15m' metric, count(*)::text value
from public.system_events
where created_at >= now()-interval '15 minutes'
  and (event_type='conversation_ledger_revision_cas'
       or payload::text like '%conversation_ledger_revision_cas%');

select 'critical_buffer_rows' metric, count(*)::text value
from public.lead_buffer where status in ('processing','awaiting_proof');

select 'outbound_rows_15m' metric, count(*)::text value
from public.lead_buffer
where direction='outbound' and created_at >= now()-interval '15 minutes';

select 'unproved_agent_outbound_15m' metric, count(*)::text value
from public.lead_buffer b
where b.direction='outbound'
  and b.created_at >= now()-interval '15 minutes'
  and coalesce(b.payload->>'sender_type','')='agent'
  and not exists (
    select 1 from public.conversation_turn_proofs p
    where p.outbound_id=b.id::text
      and coalesce((p.proof_result->>'valid')::boolean, false)
  );

select 'graph_checksum_divergence' metric, count(*)::text value
from public.conversation_ledgers l
join public.graph_publications p on p.id=l.publication_id
where l.graph_checksum is distinct from p.checksum;

select 'active_publications_without_checksum' metric, count(*)::text value
from public.graph_publications
where status='active' and checksum !~ '^sha256:[0-9a-f]{64}$';

do $$
begin
  if exists (
    select 1 from public.system_events
    where created_at >= now()-interval '15 minutes'
      and (event_type='conversation_ledger_revision_cas'
           or payload::text like '%conversation_ledger_revision_cas%')
  ) then raise exception 'CAS conflict observed inside stability window'; end if;
  if exists (
    select 1 from public.lead_buffer
    where status='processing' and coalesce(locked_at, updated_at) < now()-interval '5 minutes'
  ) then raise exception 'orphan processing buffer rows remain'; end if;
  if exists (
    select 1 from public.lead_buffer
    where status='awaiting_proof' and updated_at < now()-interval '5 minutes'
  ) then raise exception 'orphan proof buffer rows remain'; end if;
  if exists (
    select 1 from public.lead_buffer b
    where b.direction='outbound'
      and b.created_at >= now()-interval '15 minutes'
      and coalesce(b.payload->>'sender_type','')='agent'
      and not exists (
        select 1 from public.conversation_turn_proofs p
        where p.outbound_id=b.id::text
          and coalesce((p.proof_result->>'valid')::boolean, false)
      )
  ) then raise exception 'unproved agent outbound observed'; end if;
  if exists (
    select 1 from public.conversation_ledgers l
    join public.graph_publications p on p.id=l.publication_id
    where l.graph_checksum is distinct from p.checksum
  ) then raise exception 'ledger/publication checksum divergence remains'; end if;
end
$$;
SQL
fi

if [[ "$require_fresh_backup" == "true" ]]; then
  latest_backup="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -60 -print -quit 2>/dev/null || true)"
  if [[ -n "$latest_backup" ]]; then
    printf 'PASS\tfresh_backup\t%s\n' "$latest_backup"
  else
    printf 'FAIL\tfresh_backup\tno backup created within 60m for data-risk migration\n'
    failed=1
  fi
fi

exit "$failed"
