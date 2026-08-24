#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
IMPACT="${1:?usage: deploy-incremental.sh <api|worker|conversational|migration> <sha> [--apply]}"
TARGET_SHA="${2:?usage: deploy-incremental.sh <impact> <sha> [--apply]}"
MODE="${3:---dry-run}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-35}"
[[ "$IMPACT" =~ ^(api|worker|conversational|migration)$ ]] || { echo "unsupported VPS impact: $IMPACT" >&2; exit 2; }
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "full Git SHA required" >&2; exit 2; }
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "expected --dry-run or --apply" >&2; exit 2; }
cd "$ROOT_DIR"
python3 ops/vps/validate_env.py "$ENV_FILE"

# Existing production installs predate the split API/worker/migrate images and
# may only declare API_IMAGE. Bootstrap sibling image names from that immutable
# registry path so the first incremental release does not fall back to a local
# Docker Hub name. Explicit values in .env.compose remain authoritative.
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

STATE_DIR="$ROOT_DIR/.deploy"
COMPONENTS_FILE="$STATE_DIR/components.env"
CURRENT_SHA="$(tr -d '\r\n' < "$STATE_DIR/current-tag" 2>/dev/null || true)"
[[ "$CURRENT_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "a full current production SHA is required before an incremental deploy" >&2
  exit 1
}
API_TAG="$CURRENT_SHA"
WORKER_TAG="$CURRENT_SHA"
MIGRATE_TAG="$CURRENT_SHA"
if [[ -s "$COMPONENTS_FILE" ]]; then
  # File is host-generated and accepts only full SHA assignments below.
  while IFS='=' read -r key value; do
    [[ "$value" =~ ^[0-9a-f]{40}$ ]] || continue
    case "$key" in
      API_TAG) API_TAG="$value" ;;
      WORKER_TAG) WORKER_TAG="$value" ;;
      MIGRATE_TAG) MIGRATE_TAG="$value" ;;
    esac
  done < "$COMPONENTS_FILE"
fi

pull_services=()
replace_services=()
case "$IMPACT" in
  api)
    API_TAG="$TARGET_SHA"; pull_services=(api); replace_services=(api) ;;
  worker)
    WORKER_TAG="$TARGET_SHA"; pull_services=(workers); replace_services=(workers) ;;
  conversational)
    API_TAG="$TARGET_SHA"; WORKER_TAG="$TARGET_SHA"
    pull_services=(api workers); replace_services=(api workers) ;;
  migration)
    API_TAG="$TARGET_SHA"; WORKER_TAG="$TARGET_SHA"; MIGRATE_TAG="$TARGET_SHA"
    pull_services=(api workers migrate); replace_services=(migrate api workers) ;;
esac
export API_TAG WORKER_TAG MIGRATE_TAG IMAGE_TAG="$TARGET_SHA"
COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)

disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]] && (( disk_used < DISK_MAX_PERCENT )) || {
  echo "disk gate failed: ${disk_used:-unknown}% (required <${DISK_MAX_PERCENT}%)" >&2
  exit 1
}
printf 'impact=%s\ntarget=%s\ncurrent=%s\napi_tag=%s\nworker_tag=%s\nmigrate_tag=%s\ndisk_percent=%s\n' \
  "$IMPACT" "$TARGET_SHA" "$CURRENT_SHA" "$API_TAG" "$WORKER_TAG" "$MIGRATE_TAG" "$disk_used"
printf 'pull_services=%s\nreplace_services=%s\n' "${pull_services[*]}" "${replace_services[*]}"
if [[ "$MODE" == "--dry-run" ]]; then
  exit 0
fi

python3 ops/vps/release_lifecycle.py prepare \
  --candidate-sha "$TARGET_SHA" --previous-sha "$CURRENT_SHA" \
  --impact-class "$IMPACT" \
  --pause-reason "incremental $IMPACT deployment" >/dev/null
stage_rank() {
  case "$1" in
    prepared) echo 0 ;; images_pulled) echo 1 ;; claims_paused) echo 2 ;;
    queue_drained) echo 3 ;; migration_complete) echo 4 ;;
    candidate_healthy) echo 5 ;; validator_complete) echo 6 ;;
    soak_complete) echo 7 ;; awaiting_resume_authorization) echo 8 ;;
    workers_resumed) echo 9 ;; verified) echo 10 ;; *) echo -1 ;;
  esac
}
current_stage="$(python3 ops/vps/release_lifecycle.py show --field stage)"
current_rank="$(stage_rank "$current_stage")"
(( current_rank >= 0 )) || { echo "unknown lifecycle stage: $current_stage" >&2; exit 1; }
if (( current_rank < 1 )); then
  "${COMPOSE[@]}" pull "${pull_services[@]}"
  python3 ops/vps/release_lifecycle.py advance --stage images_pulled \
    --gate "disk_percent=$disk_used" >/dev/null
  current_rank=1
fi

wait_for_api() {
  local api_bind deadline source active_service
  active_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
  [[ "$active_service" == "api-candidate" ]] || active_service=api
  api_bind="$("${COMPOSE_BG[@]}" port "$active_service" 8080)"
  deadline=$((SECONDS + 180))
  until curl --fail --silent --show-error "http://$api_bind/health/ready" >/dev/null; do
    (( SECONDS < deadline )) || return 1
    sleep 2
  done
  source="$("${COMPOSE_BG[@]}" exec -T "$active_service" sh -c 'cat /image-source-sha')"
  [[ "$source" == "$API_TAG" ]]
}

persist_components() {
  local temp previous_temp
  mkdir -p "$STATE_DIR"
  previous_temp="$(mktemp "$STATE_DIR/.previous-components.env.XXXXXX")"
  if [[ -s "$COMPONENTS_FILE" ]]; then
    cp "$COMPONENTS_FILE" "$previous_temp"
  else
    printf 'API_TAG=%s\nWORKER_TAG=%s\nMIGRATE_TAG=%s\n' \
      "$CURRENT_SHA" "$CURRENT_SHA" "$CURRENT_SHA" > "$previous_temp"
  fi
  chmod 0600 "$previous_temp"
  mv -f "$previous_temp" "$STATE_DIR/previous-components.env"
  temp="$(mktemp "$STATE_DIR/.components.env.XXXXXX")"
  printf 'API_TAG=%s\nWORKER_TAG=%s\nMIGRATE_TAG=%s\n' \
    "$API_TAG" "$WORKER_TAG" "$MIGRATE_TAG" > "$temp"
  chmod 0600 "$temp"
  mv -f "$temp" "$COMPONENTS_FILE"
  if [[ "$CURRENT_SHA" != "$TARGET_SHA" ]]; then
    printf '%s\n' "$CURRENT_SHA" > "$STATE_DIR/previous-tag"
  fi
  printf '%s\n' "$TARGET_SHA" > "$STATE_DIR/current-tag"
}

if [[ "$IMPACT" == "api" ]]; then
  if (( current_rank < 5 )); then
    bash ops/vps/deploy-api-blue-green.sh "$TARGET_SHA"
    wait_for_api
    persist_components
    python3 ops/vps/release_lifecycle.py advance --stage candidate_healthy \
      --gate api_ready=true --gate "api_source_sha=$API_TAG" >/dev/null
    current_rank=5
  fi
  if (( current_rank < 10 )); then
    python3 ops/vps/release_lifecycle.py advance --stage verified \
      --gate claims_pause=not_required --gate worker_restarted=false >/dev/null
  fi
  echo "incremental API deploy verified without touching workers"
  exit 0
fi

if (( current_rank < 2 )); then
  python3 ops/vps/release_lifecycle.py pause-claims \
    --reason "incremental $IMPACT deployment" >/dev/null
  current_rank=2
fi
if (( current_rank < 3 )); then
  bash ops/vps/drain-worker-claims.sh
  current_rank=3
fi
if [[ "$IMPACT" == "migration" ]] && (( current_rank < 4 )); then
  bash ops/vps/backup.sh
  "${COMPOSE[@]}" up -d db
  "${COMPOSE[@]}" up --no-deps --force-recreate db-bootstrap
  "${COMPOSE[@]}" up --no-deps --force-recreate migrate
  "${COMPOSE[@]}" up -d --no-deps --force-recreate rest
  python3 ops/vps/release_lifecycle.py advance --stage migration_complete >/dev/null
  current_rank=4
fi
if (( current_rank < 5 )); then
  if [[ "$IMPACT" =~ ^(conversational|migration)$ ]]; then
    bash ops/vps/deploy-api-blue-green.sh "$TARGET_SHA"
    wait_for_api
  fi
  "${COMPOSE[@]}" up -d --no-deps workers
  worker_source="$("${COMPOSE[@]}" exec -T workers sh -c 'cat /image-source-sha')"
  [[ "$worker_source" == "$WORKER_TAG" ]] || { echo "worker source SHA mismatch" >&2; exit 1; }
  persist_components
  python3 ops/vps/release_lifecycle.py advance --stage candidate_healthy \
    --gate api_ready=true --gate "api_source_sha=$API_TAG" \
    --gate "worker_source_sha=$WORKER_TAG" >/dev/null
  current_rank=5
fi

if [[ "$IMPACT" == "conversational" || "$IMPACT" == "migration" ]]; then
  echo "candidate healthy; run the internal WA Validator evidence step before resume"
  exit 0
fi
if (( current_rank < 6 )); then
  python3 ops/vps/release_lifecycle.py advance --stage validator_complete \
    --gate wa_validator=not_required_worker_only >/dev/null
  current_rank=6
fi
if (( current_rank < 7 )); then
  python3 ops/vps/release_lifecycle.py advance --stage soak_complete \
    --gate worker_claims_paused=true >/dev/null
  current_rank=7
fi
if (( current_rank < 8 )); then
  python3 ops/vps/release_lifecycle.py advance --stage awaiting_resume_authorization >/dev/null
fi
echo "worker candidate ready and awaiting explicit resume authorization"
