#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
RESTORE_MARKER="${RESTORE_MARKER:-$BACKUP_ROOT/restore-tests/LAST_SUCCESS}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-35}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)
active_api_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active_api_service" == "api-candidate" ]] || active_api_service=api
impact_class="$(python3 ops/vps/release_lifecycle.py show --field impact_class 2>/dev/null || true)"
require_fresh_backup="${REQUIRE_FRESH_BACKUP:-}"
if [[ -z "$require_fresh_backup" ]]; then
  if [[ "$impact_class" == "migration" ]]; then
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
for required in \
  .env.compose \
  .env.microservices/gateway.env \
  .env.microservices/control-plane.env \
  .env.microservices/runtime.env \
  .env.microservices/transport.env; do
  check_file "$required" "production_config_$(basename "$required")"
done
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
  local service="$1" digest_file="$2" allow_paused_missing="${3:-false}" expected cid image_id
  if [[ ! -s "$digest_file" ]]; then
    printf 'FAIL\t%s_digest\tmissing evidence\n' "$service"; failed=1; return
  fi
  expected="$(tr -d '\r\n' < "$digest_file")"
  if [[ ! "$expected" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'FAIL\t%s_digest\tunresolved\n' "$service"; failed=1; return
  fi
  cid="$("${COMPOSE_BG[@]}" ps -q "$service")"
  if [[ -z "$cid" ]]; then
    if [[ "$allow_paused_missing" == "true" ]] && python3 - <<'PY'
import json
from pathlib import Path

path = Path(".deploy/control/claims-paused.json")
try:
    paused = json.loads(path.read_text(encoding="utf-8")).get("paused") is True
except (OSError, json.JSONDecodeError, AttributeError):
    paused = False
raise SystemExit(0 if paused else 1)
PY
    then
      printf 'PASS\t%s_digest\tcontainer intentionally stopped; claims paused; expected=%s\n' \
        "$service" "$expected"
      return
    fi
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
check_container_digest workers .deploy/release-worker-digest true

"${COMPOSE[@]}" ps
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -P pager=off' <<'SQL'
select 'migration' metric, filename value
from public._compose_migrations
where filename in (
  '112_graph_turn_replay_and_branch_fact_atomicity.sql',
  '113_quiet_burst_supersession.sql',
  '114_context_batches_indexes_and_validator_cas.sql',
  '115_internal_data_api_privileges.sql',
  '116_reconcile_active_conversation_branches.sql',
  '117_wa_validator_queue_and_retention.sql',
  '118_conversation_journeys_and_sales_conversions.sql',
  '119_whatsapp_media_ingest.sql',
  '120_graphrag_faq_projection_v1.sql',
  '121_sdr_journey_state_machine.sql',
  '122_preserve_post_handoff_journey.sql',
  '123_journey_outcome_events.sql',
  '124_reversible_conversion.sql',
  '125_cancel_reverses_the_purchase.sql',
  '126_journey_state_selector.sql',
  '127_sdr_name_service_confirmation.sql',
  '128_confirm_branch_offering_within_journey.sql',
  '129_carry_over_facts_by_lead.sql',
  '130_shared_lead_memory_and_journey_commit_v4.sql',
  '131_microservice_role_grants.sql'
) order by filename;

select 'microservice_role' metric,
       rolname || ':login=' || rolcanlogin::text || ':bypassrls=' || rolbypassrls::text value
from pg_roles
where rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport')
order by rolname;

select 'unsafe_table_grants' metric, count(*)::text value
from information_schema.role_table_grants
where table_schema='public' and grantee in ('PUBLIC','anon','authenticated');

select 'unsafe_function_grants' metric, count(*)::text value
from information_schema.routine_privileges
where specific_schema='public' and grantee in ('PUBLIC','anon','authenticated');

select 'tables_without_rls' metric, count(*)::text value
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relkind in ('r','p') and not c.relrowsecurity;

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
  if (select count(*) from public._compose_migrations where filename in (
      '112_graph_turn_replay_and_branch_fact_atomicity.sql',
      '113_quiet_burst_supersession.sql',
      '114_context_batches_indexes_and_validator_cas.sql',
      '115_internal_data_api_privileges.sql',
      '116_reconcile_active_conversation_branches.sql',
      '117_wa_validator_queue_and_retention.sql',
      '118_conversation_journeys_and_sales_conversions.sql',
      '119_whatsapp_media_ingest.sql',
      '120_graphrag_faq_projection_v1.sql',
      '121_sdr_journey_state_machine.sql',
      '122_preserve_post_handoff_journey.sql',
      '123_journey_outcome_events.sql',
      '124_reversible_conversion.sql',
      '125_cancel_reverses_the_purchase.sql',
      '126_journey_state_selector.sql',
      '127_sdr_name_service_confirmation.sql',
      '128_confirm_branch_offering_within_journey.sql',
      '129_carry_over_facts_by_lead.sql',
      '130_shared_lead_memory_and_journey_commit_v4.sql',
      '131_microservice_role_grants.sql')) <> 20 then
    raise exception 'release migrations 112-131 are incomplete';
  end if;
  if (select count(*) from pg_roles
      where rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport')
        and not rolcanlogin and rolbypassrls) <> 4 then
    raise exception 'microservice database roles are missing or unsafe';
  end if;
  if (select count(*)
      from pg_auth_members membership
      join pg_roles granted_role on granted_role.oid=membership.roleid
      join pg_roles member_role on member_role.oid=membership.member
      where member_role.rolname='authenticator'
        and granted_role.rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport')) <> 4 then
    raise exception 'authenticator cannot assume every microservice role';
  end if;
  if exists (
    select 1
    from pg_auth_members membership
    join pg_roles granted_role on granted_role.oid=membership.roleid
    join pg_roles member_role on member_role.oid=membership.member
    where granted_role.rolname='service_role'
      and member_role.rolname in ('brain_gateway','brain_control_plane','brain_runtime','brain_transport')
  ) then
    raise exception 'microservice role inherits universal service_role';
  end if;
  if exists (
    select 1 from information_schema.role_table_grants
    where table_schema='public' and grantee in ('PUBLIC','anon','authenticated')
  ) then raise exception 'unsafe public table grants remain'; end if;
  if exists (
    select 1 from information_schema.routine_privileges
    where specific_schema='public' and grantee in ('PUBLIC','anon','authenticated')
  ) then raise exception 'unsafe public function grants remain'; end if;
  if exists (
    select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relkind in ('r','p') and not c.relrowsecurity
  ) then raise exception 'public tables without RLS remain'; end if;
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

printf 'INFO\tdocker_stats\n'
docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
df -P "$ROOT_DIR"
disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [[ "$disk_used" =~ ^[0-9]+$ ]] && (( disk_used < DISK_MAX_PERCENT )); then
  printf 'PASS\tdisk_usage\t%s%% limit<%s%%\n' "$disk_used" "$DISK_MAX_PERCENT"
else
  printf 'FAIL\tdisk_usage\t%s%% limit<%s%%\n' "${disk_used:-unknown}" "$DISK_MAX_PERCENT"
  failed=1
fi

latest_backup="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -1560 -print -quit 2>/dev/null || true)"
if [[ -n "$latest_backup" ]]; then printf 'PASS\tbackup_age\t%s\n' "$latest_backup"
elif [[ "$require_fresh_backup" == "true" ]]; then
  printf 'FAIL\tbackup_age\tno data-only backup within 26h impact=%s\n' "${impact_class:-unknown}"
  failed=1
else
  printf 'WARN\tbackup_age\tno data-only backup within 26h; not required for impact=%s\n' "$impact_class"
fi

if [[ -f "$RESTORE_MARKER" && -n "$(find "$RESTORE_MARKER" -mmin -43200 -print -quit 2>/dev/null)" ]]; then
  printf 'PASS\tlast_restore\t%s\n' "$(cat "$RESTORE_MARKER")"
else
  printf 'FAIL\tlast_restore\tno controlled restore proof within 30d\n'; failed=1
fi

exit "$failed"
