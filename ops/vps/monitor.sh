#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-35}"
cd "$ROOT_DIR"
failed=0
COMPOSE=(docker compose --env-file "$ENV_FILE" --profile blue-green)
active_api_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active_api_service" == "api-candidate" ]] || active_api_service=api
services=(db rest storage kong workers caddy "$active_api_service")
lifecycle_stage=""
lifecycle_age_seconds=""
if [[ -s .deploy/lifecycle.json ]]; then
  lifecycle_stage="$(python3 ops/vps/release_lifecycle.py show --field stage 2>/dev/null || true)"
  lifecycle_age_seconds="$(python3 - <<'PY'
import datetime as dt, json
from pathlib import Path
state=json.loads(Path('.deploy/lifecycle.json').read_text(encoding='utf-8'))
stamp=dt.datetime.fromisoformat(str(state['stage_entered_at']).replace('Z','+00:00'))
print(max(0, int((dt.datetime.now(dt.timezone.utc)-stamp).total_seconds())))
PY
)"
fi
registered_pause=false
case "$lifecycle_stage" in
  claims_paused|queue_drained|migration_complete|candidate_healthy|validator_complete|soak_complete|awaiting_resume_authorization)
    registered_pause=true ;;
esac
evolution_enabled="$(
  awk -F= '
    /^[[:space:]]*EVOLUTION_ENABLED[[:space:]]*=/ {
      value=tolower($2); gsub(/[[:space:]"\047]/, "", value); print value
    }
  ' "$ENV_FILE" | tail -n 1
)"
if [[ "$evolution_enabled" =~ ^(1|true|yes)$ ]]; then
  services+=(evolution-redis evolution-api)
fi
for service in "${services[@]}"; do
  cid="$("${COMPOSE[@]}" ps -q "$service")"
  if [[ -z "$cid" || "$(docker inspect -f '{{.State.Status}}' "$cid")" != "running" ]]; then
    if [[ "$service" == "workers" && "$registered_pause" == "true" \
          && "$lifecycle_age_seconds" =~ ^[0-9]+$ \
          && "$lifecycle_age_seconds" -lt 600 ]]; then
      echo "WARNING: workers stopped inside registered release window (${lifecycle_age_seconds}s)"
    else
      echo "CRITICAL: $service is not running"; failed=1
    fi
  elif [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")" == "unhealthy" ]]; then
    echo "CRITICAL: $service is unhealthy"; failed=1
  fi
done
if [[ "$lifecycle_stage" == "awaiting_resume_authorization" \
      && "$lifecycle_age_seconds" =~ ^[0-9]+$ \
      && "$lifecycle_age_seconds" -ge 600 ]]; then
  echo "CRITICAL: release has awaited worker resume for ${lifecycle_age_seconds}s"
  failed=1
fi

api_cid="$("${COMPOSE[@]}" ps -q "$active_api_service")"
worker_cid="$("${COMPOSE[@]}" ps -q workers)"
if [[ -n "$api_cid" && -n "$worker_cid" \
      && "$(docker inspect -f '{{.State.Status}}' "$worker_cid")" == "running" ]]; then
  api_sha="$(docker exec "$api_cid" sh -c 'cat /image-source-sha' 2>/dev/null || true)"
  worker_sha="$(docker exec "$worker_cid" sh -c 'cat /image-source-sha' 2>/dev/null || true)"
  expected_api=""; expected_worker=""
  if [[ -s .deploy/components.env ]]; then
    expected_api="$(awk -F= '$1=="API_TAG" {print $2}' .deploy/components.env)"
    expected_worker="$(awk -F= '$1=="WORKER_TAG" {print $2}' .deploy/components.env)"
  fi
  if [[ -z "$api_sha" || -z "$worker_sha" \
        || ( -n "$expected_api" && "$api_sha" != "$expected_api" ) \
        || ( -n "$expected_worker" && "$worker_sha" != "$expected_worker" ) ]]; then
    echo "CRITICAL: component SOURCE_SHA is not approved api=${api_sha:-unknown}/${expected_api:-unknown} worker=${worker_sha:-unknown}/${expected_worker:-unknown}"
    failed=1
  elif [[ "$api_sha" != "$worker_sha" ]]; then
    echo "WARNING: approved API/worker component SHAs diverge api=$api_sha worker=$worker_sha"
  fi
  api_domain="$(awk -F= '/^[[:space:]]*API_DOMAIN[[:space:]]*=/ {value=$2; gsub(/[[:space:]"\047]/,"",value); print value}' "$ENV_FILE" | tail -n 1)"
  external_sha="$(curl --fail --silent --show-error "https://$api_domain/health/ready" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("source_sha") or "")' 2>/dev/null || true)"
  if [[ -z "$external_sha" || "$external_sha" != "$api_sha" ]]; then
    echo "CRITICAL: Caddy upstream does not expose the approved active API SHA external=${external_sha:-unknown} active=$api_sha"
    failed=1
  fi
fi

psql_scalar() {
  printf '%s\n' "$1" | "${COMPOSE[@]}" exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}
oldest_buffered_seconds="$(psql_scalar "
select coalesce(extract(epoch from now()-min(created_at))::bigint,0)
from public.lead_buffer
where direction='inbound' and status in ('received','buffered','retry');")"
backlog_count="$(psql_scalar "
select count(*) from public.lead_buffer
where direction='inbound' and status in ('received','buffered','retry');")"
if [[ "$oldest_buffered_seconds" =~ ^[0-9]+$ ]] && (( oldest_buffered_seconds >= 300 )); then
  echo "CRITICAL: oldest eligible inbound is ${oldest_buffered_seconds}s old"
  failed=1
fi
if [[ "$lifecycle_stage" =~ ^(workers_resumed|verified)$ \
      && "$backlog_count" =~ ^[0-9]+$ ]]; then
  previous_backlog="$(tr -d '[:space:]' < .deploy/monitor-backlog-count 2>/dev/null || true)"
  if [[ "$previous_backlog" =~ ^[0-9]+$ ]] && (( backlog_count > previous_backlog )); then
    echo "CRITICAL: backlog increased after resume previous=$previous_backlog current=$backlog_count"
    failed=1
  fi
  backlog_temp="$(mktemp .deploy/.monitor-backlog-count.XXXXXX)"
  printf '%s\n' "$backlog_count" > "$backlog_temp"
  mv -f "$backlog_temp" .deploy/monitor-backlog-count
fi
duplicate_proofs="$(psql_scalar "
select count(*) from (
  select canonical_inbound_id from public.conversation_turn_proofs
  group by canonical_inbound_id having count(*) > 1
) duplicate;")"
if [[ "$duplicate_proofs" != "0" ]]; then
  echo "CRITICAL: $duplicate_proofs canonical inbounds have multiple proof rows"
  failed=1
fi
release_image_count="$(docker image ls --format '{{.Repository}}:{{.Tag}}' | \
  awk '/brain-(runtime-base|api|workers|migrate):[0-9a-f]{40}$/ {count++} END {print count+0}')"
if (( release_image_count > 8 )); then
  echo "CRITICAL: $release_image_count immutable Brain release images remain locally"
  failed=1
fi
disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
(( disk_used < DISK_MAX_PERCENT )) || {
  echo "CRITICAL: disk usage is ${disk_used}% (required <${DISK_MAX_PERCENT}%)"
  failed=1
}
memory_used="$(free | awk '/Mem:/ {printf("%.0f", $3/$2*100)}')"
(( memory_used < 90 )) || { echo "WARNING: memory usage is ${memory_used}%"; failed=1; }
latest="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres-data.dump -mmin -1560 -print -quit 2>/dev/null || true)"
[[ -n "$latest" ]] || { echo "CRITICAL: no successful database backup in the last 26 hours"; failed=1; }
exit "$failed"
