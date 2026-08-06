#!/usr/bin/env bash
set -Eeuo pipefail

# Deploys the QA stack (Compose project `brain-ai-qa`) from its own checkout,
# parallel to and independent from `ops/vps/deploy.sh` (prod). QA never runs
# caddy, n8n or Evolution — it shares those with prod and only brings up its
# own db/rest/storage/kong/api/workers. See
# docs/runbooks/QA_PRODUCTION_ISOLATION.md, section "QA persistente (mesma
# VPS)".

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
STATE_DIR="$ROOT_DIR/.deploy"
TARGET_TAG="${1:?usage: deploy-qa.sh <image-tag>}"
[[ "$TARGET_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo "Invalid Docker image tag: $TARGET_TAG" >&2; exit 2; }
mkdir -p "$STATE_DIR"

EXPECTED_COMPOSE_PROJECT_NAME="${EXPECTED_COMPOSE_PROJECT_NAME:-brain-ai-qa}" \
  python3 "$ROOT_DIR/ops/vps/validate_env.py" "$ENV_FILE"
cd "$ROOT_DIR"
export IMAGE_TAG="$TARGET_TAG"
COMPOSE=(docker compose --env-file "$ENV_FILE")

# Shared with prod's Caddy so it can reach this stack's api/kong. Prod's
# deploy.sh also creates this idempotently; guarded here too so QA can be
# deployed on a host that hasn't run a prod deploy since this network was
# introduced.
docker network inspect edge >/dev/null 2>&1 || docker network create edge

previous=""
if [[ -f "$STATE_DIR/current-tag" ]]; then
  previous="$(tr -d '\r\n' < "$STATE_DIR/current-tag")"
fi

verify_local_images() {
  local image
  while IFS= read -r image; do
    [[ -n "$image" ]] || continue
    docker image inspect "$image" >/dev/null
  done < <("${COMPOSE[@]}" config --images | sort -u)
}

wait_for_api() {
  local api_bind deadline
  api_bind="$("${COMPOSE[@]}" port api 8080)"
  deadline=$((SECONDS + 180))
  until curl --fail --silent --show-error "http://$api_bind/health/ready" >/dev/null; do
    if (( SECONDS >= deadline )); then
      "${COMPOSE[@]}" ps
      "${COMPOSE[@]}" logs --tail=100 api migrate
      return 1
    fi
    sleep 5
  done
}

deploy_tag() {
  local tag="$1"
  local allow_local_images="${2:-false}"
  export IMAGE_TAG="$tag"
  if ! "${COMPOSE[@]}" pull migrate api workers seed-admin; then
    [[ "$allow_local_images" == "true" ]] || return 1
    echo "Registry pull failed during rollback; validating immutable local images." >&2
    verify_local_images
  fi
  "${COMPOSE[@]}" stop workers
  "${COMPOSE[@]}" up -d db
  "${COMPOSE[@]}" up --no-deps --force-recreate migrate
  "${COMPOSE[@]}" up -d --remove-orphans rest storage kong api
  wait_for_api
  "${COMPOSE[@]}" up -d workers seed-admin
  wait_for_api
}

if deploy_tag "$TARGET_TAG" "${ALLOW_LOCAL_IMAGES:-false}"; then
  [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]] && printf '%s\n' "$previous" > "$STATE_DIR/previous-tag"
  printf '%s\n' "$TARGET_TAG" > "$STATE_DIR/current-tag"
  echo "QA deployment healthy: $TARGET_TAG"
  exit 0
fi

if [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]]; then
  echo "QA deployment failed; rolling back containers to $previous" >&2
  deploy_tag "$previous" true
  printf '%s\n' "$previous" > "$STATE_DIR/current-tag"
  exit 1
fi
echo "QA deployment failed and no previous healthy image tag is recorded." >&2
exit 1
