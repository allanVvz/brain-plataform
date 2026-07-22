#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
STATE_DIR="$ROOT_DIR/.deploy"
TARGET_TAG="${1:?usage: deploy.sh <image-tag>}"
[[ "$TARGET_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo "Invalid Docker image tag: $TARGET_TAG" >&2; exit 2; }
mkdir -p "$STATE_DIR"

python3 "$ROOT_DIR/ops/vps/validate_env.py" "$ENV_FILE"
cd "$ROOT_DIR"
export IMAGE_TAG="$TARGET_TAG"
COMPOSE=(docker compose --env-file "$ENV_FILE")

previous=""
if [[ -f "$STATE_DIR/current-tag" ]]; then
  previous="$(tr -d '\r\n' < "$STATE_DIR/current-tag")"
fi

deploy_tag() {
  local tag="$1"
  export IMAGE_TAG="$tag"
  "${COMPOSE[@]}" pull migrate api workers seed-admin
  "${COMPOSE[@]}" up -d db
  "${COMPOSE[@]}" up --no-deps --force-recreate migrate
  "${COMPOSE[@]}" up -d --remove-orphans rest storage kong api workers seed-admin caddy
  local api_bind
  api_bind="$("${COMPOSE[@]}" port api 8080)"
  local deadline=$((SECONDS + 180))
  until curl --fail --silent --show-error "http://$api_bind/health/ready" >/dev/null; do
    if (( SECONDS >= deadline )); then
      "${COMPOSE[@]}" ps
      "${COMPOSE[@]}" logs --tail=100 api workers migrate
      return 1
    fi
    sleep 5
  done
}

if deploy_tag "$TARGET_TAG"; then
  [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]] && printf '%s\n' "$previous" > "$STATE_DIR/previous-tag"
  printf '%s\n' "$TARGET_TAG" > "$STATE_DIR/current-tag"
  echo "Deployment healthy: $TARGET_TAG"
  exit 0
fi

if [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]]; then
  echo "Deployment failed; rolling back containers to $previous" >&2
  deploy_tag "$previous"
  printf '%s\n' "$previous" > "$STATE_DIR/current-tag"
  exit 1
fi
echo "Deployment failed and no previous healthy image tag is recorded." >&2
exit 1
