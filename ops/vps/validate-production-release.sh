#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
RESTORE_MARKER="${RESTORE_MARKER:-$BACKUP_ROOT/restore-tests/LAST_SUCCESS}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
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
  '126_journey_state_selector.sql'
) order by filename;

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
      '126_journey_state_selector.sql')) <> 15 then
    raise exception 'release migrations 112-126 are incomplete';
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

latest_backup="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -1560 -print -quit 2>/dev/null || true)"
if [[ -n "$latest_backup" ]]; then printf 'PASS\tbackup_age\t%s\n' "$latest_backup"
else printf 'FAIL\tbackup_age\tno data-only backup within 26h\n'; failed=1; fi

if [[ -f "$RESTORE_MARKER" && -n "$(find "$RESTORE_MARKER" -mmin -43200 -print -quit 2>/dev/null)" ]]; then
  printf 'PASS\tlast_restore\t%s\n' "$(cat "$RESTORE_MARKER")"
else
  printf 'FAIL\tlast_restore\tno controlled restore proof within 30d\n'; failed=1
fi

exit "$failed"
