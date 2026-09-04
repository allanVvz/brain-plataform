#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
TARGET_SHA="${1:?usage: resume-production-workers.sh <full-git-sha>}"
RESUME_OBSERVE_SECONDS="${RESUME_OBSERVE_SECONDS:-120}"
RESUME_POLL_SECONDS="${RESUME_POLL_SECONDS:-2}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-35}"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "full Git SHA required" >&2; exit 2; }
cd "$ROOT_DIR"

# Resume must resolve the same immutable registry repositories as the
# incremental deploy. Older production installs only declare API_IMAGE, so
# derive the sibling worker/migrate repositories instead of falling back to
# the local Compose defaults (brain-workers/brain-migrate).
read_env_value() {
  local requested="$1" key value
  while IFS='=' read -r key value; do
    [[ "$key" == "$requested" ]] || continue
    value="${value%$'\r'}"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    printf '%s' "$value"
    return 0
  done < "$ENV_FILE"
}
API_IMAGE="$(read_env_value API_IMAGE)"
WORKER_IMAGE="$(read_env_value WORKER_IMAGE)"
MIGRATE_IMAGE="$(read_env_value MIGRATE_IMAGE)"
API_IMAGE="${API_IMAGE:-brain-api}"
if [[ -z "$WORKER_IMAGE" || -z "$MIGRATE_IMAGE" ]]; then
  [[ "$API_IMAGE" == *brain-api ]] || {
    echo "WORKER_IMAGE and MIGRATE_IMAGE are required when API_IMAGE does not end in brain-api" >&2
    exit 1
  }
  image_prefix="${API_IMAGE%brain-api}"
  WORKER_IMAGE="${WORKER_IMAGE:-${image_prefix}brain-workers}"
  MIGRATE_IMAGE="${MIGRATE_IMAGE:-${image_prefix}brain-migrate}"
fi
export API_IMAGE WORKER_IMAGE MIGRATE_IMAGE

COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)
released=false
API_TAG="$TARGET_SHA"
WORKER_TAG="$TARGET_SHA"
MIGRATE_TAG="$TARGET_SHA"
if [[ -s .deploy/components.env ]]; then
  while IFS='=' read -r key value; do
    [[ "$value" =~ ^[0-9a-f]{40}$ ]] || continue
    case "$key" in
      API_TAG) API_TAG="$value" ;;
      WORKER_TAG) WORKER_TAG="$value" ;;
      MIGRATE_TAG) MIGRATE_TAG="$value" ;;
    esac
  done < .deploy/components.env
fi
export API_TAG WORKER_TAG MIGRATE_TAG IMAGE_TAG="$TARGET_SHA"

pause_after_failure() {
  local exit_code="$?"
  if [[ "$released" == "true" ]]; then
    python3 ops/vps/release_lifecycle.py pause-claims \
      --reason "automatic safety pause after resume verification failure" \
      --safety-pause >/dev/null || true
  fi
  exit "$exit_code"
}
trap pause_after_failure ERR

lifecycle_stage="$(python3 ops/vps/release_lifecycle.py show --field stage)"
python3 ops/vps/release_lifecycle.py assert \
  --stage "$lifecycle_stage" --candidate-sha "$TARGET_SHA" >/dev/null
case "$lifecycle_stage" in
  awaiting_resume_authorization) resume_already_released=false ;;
  workers_resumed) resume_already_released=true; released=true ;;
  verified)
    [[ ! -e .deploy/control/claims-paused.json ]] || {
      echo "verified release unexpectedly has claims paused" >&2; exit 1;
    }
    verified_worker="$("${COMPOSE[@]}" ps -q workers 2>/dev/null)"
    [[ -n "$verified_worker" \
          && "$(docker inspect -f '{{.State.Status}}' "$verified_worker")" == "running" ]] || {
      echo "verified release worker is not running" >&2; exit 1;
    }
    echo "workers already resumed and release verified: $TARGET_SHA"
    exit 0
    ;;
  *) echo "release is not ready for worker resume: $lifecycle_stage" >&2; exit 1 ;;
esac
[[ "$(python3 ops/vps/release_lifecycle.py show --field resume_authorization.authorized)" == "True" ]] || {
  echo "durable resume authorization is missing" >&2
  exit 1
}
installed_sha="$(tr -d '\r\n' < .deploy/release-source-sha)"
[[ "$installed_sha" == "$TARGET_SHA" ]] || {
  echo "installed release SHA does not match resume target" >&2
  exit 1
}

active_api_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active_api_service" == "api-candidate" ]] || active_api_service=api
api_cid="$("${COMPOSE_BG[@]}" ps -q "$active_api_service")"
[[ -n "$api_cid" && "$(docker inspect -f '{{.State.Status}}' "$api_cid")" == "running" ]] || {
  echo "API is not running" >&2
  exit 1
}
api_source_sha="$(docker exec "$api_cid" sh -c 'tr -d "\r\n" < /image-source-sha')"
[[ "$api_source_sha" == "$API_TAG" ]] || {
  echo "API source SHA does not match approved API component" >&2
  exit 1
}
api_bind="$("${COMPOSE_BG[@]}" port "$active_api_service" 8080)"
curl --fail --silent --show-error "http://$api_bind/health/ready" >/dev/null

disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]] && (( disk_used < DISK_MAX_PERCENT )) || {
  echo "disk gate failed: ${disk_used:-unknown}% (required <${DISK_MAX_PERCENT}%)" >&2
  exit 1
}

psql_scalar() {
  printf '%s\n' "$1" | "${COMPOSE[@]}" exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}

cas_conflicts=0
critical_rows=0
safety_paused_bindings=0
claimable_with_commit=0
if [[ "$resume_already_released" == "false" ]]; then
  cas_conflicts="$(psql_scalar "
select count(*) from public.system_events
where created_at >= now()-interval '15 minutes'
and (event_type='conversation_ledger_revision_cas'
or payload::text like '%conversation_ledger_revision_cas%');")"
  critical_rows="$(psql_scalar \
  "select count(*) from public.lead_buffer where status in ('processing','awaiting_proof');")"
  safety_paused_bindings="$(psql_scalar "
select count(*) from public.workflow_bindings
where active
and (connection_status='safety_paused'
or coalesce((metadata->>'safety_paused')::boolean,false));")"
  claimable_with_commit="$(psql_scalar "
select count(*) from public.lead_buffer
where direction='inbound'
and status in ('received','buffered','retry')
and payload->'conversation_commit' is not null;")"
  for gate in "$cas_conflicts" "$critical_rows" "$safety_paused_bindings" "$claimable_with_commit"; do
    [[ "$gate" == "0" ]] || {
      echo "resume database gate failed: cas=$cas_conflicts critical=$critical_rows safety_paused=$safety_paused_bindings claimable_with_commit=$claimable_with_commit" >&2
      exit 1
    }
  done

  EXPECTED_RELEASE_SHA="$TARGET_SHA" DISK_MAX_PERCENT="$DISK_MAX_PERCENT" \
    bash ops/vps/validate-production-release.sh
fi

eligible_file=".deploy/resume-eligible-${TARGET_SHA}.txt"
if [[ "$resume_already_released" == "false" ]]; then
  psql_scalar "
select id::text from (
  select distinct on (coalesce(batch_key,id::text)) id,created_at
  from public.lead_buffer
  where direction='inbound'
  and status in ('received','buffered','retry')
  and payload->'conversation_commit' is null
  order by coalesce(batch_key,id::text),created_at desc,id desc
) canonical
order by created_at,id;" > "$eligible_file"
  chmod 0600 "$eligible_file"
else
  [[ -f "$eligible_file" ]] || { echo "resume evidence inventory is missing" >&2; exit 1; }
fi
eligible_count="$(wc -l < "$eligible_file" | tr -d '[:space:]')"
if [[ "$resume_already_released" == "false" ]]; then
  python3 ops/vps/release_lifecycle.py record-gate \
    --gate "resume_disk_percent=$disk_used" \
    --gate "resume_eligible_inbound=$eligible_count" \
    --gate "resume_cas_conflicts=$cas_conflicts" >/dev/null
fi

mkdir -p .deploy/control
if [[ "$resume_already_released" == "false" ]]; then
  "${COMPOSE[@]}" up -d --no-deps workers
fi
worker_cid="$("${COMPOSE[@]}" ps -q workers)"
[[ -n "$worker_cid" ]] || { echo "worker container was not created" >&2; exit 1; }
worker_source_sha="$(docker exec "$worker_cid" sh -c 'tr -d "\r\n" < /image-source-sha')"
[[ "$worker_source_sha" == "$WORKER_TAG" ]] || {
  echo "worker source SHA does not match approved worker component" >&2
  exit 1
}
verify_container_digest() {
  local cid="$1" digest_file="$2" component="$3" expected image_id
  [[ -s "$digest_file" ]] || { echo "$component digest evidence is missing" >&2; return 1; }
  expected="$(tr -d '\r\n' < "$digest_file")"
  [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "$component digest evidence is unresolved" >&2; return 1;
  }
  image_id="$(docker inspect -f '{{.Image}}' "$cid")"
  docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id" | \
    grep -Fq "@$expected" || {
      echo "$component registry digest does not match approved evidence" >&2
      return 1
    }
}
verify_container_digest "$api_cid" .deploy/release-api-digest api
verify_container_digest "$worker_cid" .deploy/release-worker-digest worker
if [[ "$resume_already_released" == "false" ]]; then
  python3 ops/vps/release_lifecycle.py resume-claims --candidate-sha "$TARGET_SHA" >/dev/null
  released=true
  python3 ops/vps/release_lifecycle.py advance --stage workers_resumed \
    --gate "api_source_sha=$api_source_sha" \
    --gate "worker_source_sha=$worker_source_sha" \
    --gate image_digests_verified=true >/dev/null
fi

if (( eligible_count == 0 )); then
  python3 ops/vps/release_lifecycle.py advance --stage verified \
    --gate first_claim=not_applicable_empty_backlog \
    --gate worker_restart_count="$(docker inspect -f '{{.RestartCount}}' "$worker_cid")" >/dev/null
  trap - ERR
  printf 'workers_resumed\tsha=%s\tfirst_claim=none\n' "$TARGET_SHA"
  exit 0
fi

deadline=$((SECONDS + RESUME_OBSERVE_SECONDS))
verified_inbound=""
while (( SECONDS < deadline )); do
  while IFS= read -r inbound_id; do
    [[ -n "$inbound_id" ]] || continue
    status="$(psql_scalar \
      "select status from public.lead_buffer where id='$inbound_id'::uuid;")"
    case "$status" in
      received|buffered|retry|processing|awaiting_proof) ;;
      ignored) ;;
      *) verified_inbound="$inbound_id"; break 2 ;;
    esac
  done < "$eligible_file"
  sleep "$RESUME_POLL_SECONDS"
done
[[ -n "$verified_inbound" ]] || {
  echo "no eligible inbound completed inside the resume observation window" >&2
  false
}

audit_json="$(psql_scalar \
  "select public.audit_conversation_turn_v3('$verified_inbound'::uuid)::text;")"
verification="$(printf '%s' "$audit_json" | python3 ops/vps/verify_first_claim.py \
  --inbound-id "$verified_inbound")"
python3 ops/vps/release_lifecycle.py advance --stage verified \
  --gate "first_claim_inbound=$verified_inbound" \
  --gate first_claim_exactly_once=true \
  --gate worker_restart_count="$(docker inspect -f '{{.RestartCount}}' "$worker_cid")" >/dev/null
trap - ERR
printf 'workers_resumed\tsha=%s\tverification=%s\n' "$TARGET_SHA" "$verification"
