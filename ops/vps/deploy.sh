#!/usr/bin/env bash
set -Eeuo pipefail

# Full-stack compatibility path used by rollback/bootstrap only. Normal
# releases are orchestrated by deploy-incremental.sh and the idempotent
# release-{prepare,migrate,rollout-api,rollout-worker,verify,resume}.sh commands.

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

# `edge` is an external network shared with the QA stack (`brain-ai-qa`) so
# the Caddy started below can reach QA's api/kong. Create it once,
# idempotently, so a plain prod deploy never depends on QA being deployed
# first.
docker network inspect edge >/dev/null 2>&1 || docker network create edge
evolution_enabled="$(
  awk -F= '
    /^[[:space:]]*EVOLUTION_ENABLED[[:space:]]*=/ {
      value=tolower($2); gsub(/[[:space:]"\047]/, "", value); print value
    }
  ' "$ENV_FILE" | tail -n 1
)"
if [[ "$evolution_enabled" =~ ^(1|true|yes)$ ]]; then
  COMPOSE+=(--profile evolution)
  mkdir -p "$ROOT_DIR/.runtime/evolution"
  if [[ ! -s "$ROOT_DIR/.runtime/evolution/ca.pem" ]]; then
    cp /etc/ssl/certs/ca-certificates.crt "$ROOT_DIR/.runtime/evolution/ca.pem"
  fi
  chmod 0644 "$ROOT_DIR/.runtime/evolution/ca.pem"
fi
observability_enabled="$(
  awk -F= '
    /^[[:space:]]*OBSERVABILITY_ENABLED[[:space:]]*=/ {
      value=tolower($2); gsub(/[[:space:]"\047]/, "", value); print value
    }
  ' "$ENV_FILE" | tail -n 1
)"
if [[ "$observability_enabled" =~ ^(1|true|yes)$ ]]; then
  COMPOSE+=(--profile observability)
fi

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
  export API_TAG="$tag" WORKER_TAG="$tag" MIGRATE_TAG="$tag"
  mkdir -p "$STATE_DIR/caddy"
  cp infra/Caddyfile "$STATE_DIR/caddy/Caddyfile"
  printf '%s\n' api > "$STATE_DIR/api-active-slot"
  if ! "${COMPOSE[@]}" pull migrate api workers seed-admin; then
    [[ "$allow_local_images" == "true" ]] || return 1
    echo "Registry pull failed during rollback; validating immutable local images." >&2
    verify_local_images
  fi
  if [[ "$evolution_enabled" =~ ^(1|true|yes)$ ]]; then
    if ! "${COMPOSE[@]}" pull evolution-redis evolution-api; then
      [[ "$allow_local_images" == "true" ]] || return 1
      verify_local_images
    fi
  fi
  if [[ "$observability_enabled" =~ ^(1|true|yes)$ ]]; then
    if ! "${COMPOSE[@]}" pull grafana; then
      [[ "$allow_local_images" == "true" ]] || return 1
      verify_local_images
    fi
  fi
  # No sender may race the migration or the binding authority update.
  "${COMPOSE[@]}" stop workers
  "${COMPOSE[@]}" up -d db
  # db-bootstrap only ran once on this VPS's first boot -- migrate's own
  # `depends_on: db-bootstrap` is satisfied by that old exited container on
  # every later deploy (the --no-deps below skips re-checking it), so a
  # role added to its script later (e.g. grafana_reader) would otherwise
  # never get created here. Its script is fully idempotent (IF NOT EXISTS/
  # ALTER ROLE/GRANT all safe to repeat), so force-recreating it every
  # deploy is free and keeps role/grant state actually in sync with what's
  # declared in docker-compose.yml.
  "${COMPOSE[@]}" up --no-deps --force-recreate db-bootstrap
  "${COMPOSE[@]}" up --no-deps --force-recreate migrate
  "${COMPOSE[@]}" up -d --remove-orphans rest storage kong api caddy
  wait_for_api
  # Binding ownership/routing is operational content. Code deploys never
  # mutate persona bindings; use the reviewed reassignment procedure instead.
  "${COMPOSE[@]}" up -d seed-admin
  if [[ "${KEEP_WORKERS_PAUSED:-false}" == "true" ]]; then
    "${COMPOSE[@]}" stop workers
    echo "Workers remain paused for controlled production validation."
  else
    "${COMPOSE[@]}" up -d workers
  fi
  if [[ "$evolution_enabled" =~ ^(1|true|yes)$ ]]; then
    "${COMPOSE[@]}" up -d evolution-redis evolution-api
  fi
  if [[ "$observability_enabled" =~ ^(1|true|yes)$ ]]; then
    "${COMPOSE[@]}" up -d grafana
  fi
  wait_for_api
  if [[ "$evolution_enabled" =~ ^(1|true|yes)$ ]]; then
    local evolution_deadline=$((SECONDS + 360))
    local service cid status
    for service in evolution-redis evolution-api; do
      while true; do
        cid="$("${COMPOSE[@]}" ps -q "$service")"
        status="$(
          docker inspect -f \
            '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
            "$cid" 2>/dev/null || true
        )"
        [[ "$status" == "healthy" ]] && break
        if (( SECONDS >= evolution_deadline )); then
          "${COMPOSE[@]}" ps
          "${COMPOSE[@]}" logs --tail=100 "$service"
          return 1
        fi
        sleep 5
      done
    done
  fi
}

if deploy_tag "$TARGET_TAG" "${ALLOW_LOCAL_IMAGES:-false}"; then
  [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]] && printf '%s\n' "$previous" > "$STATE_DIR/previous-tag"
  printf '%s\n' "$TARGET_TAG" > "$STATE_DIR/current-tag"
  echo "Deployment healthy: $TARGET_TAG"
  exit 0
fi

if [[ -n "$previous" && "$previous" != "$TARGET_TAG" ]]; then
  echo "Deployment failed; rolling back containers to $previous" >&2
  deploy_tag "$previous" true
  printf '%s\n' "$previous" > "$STATE_DIR/current-tag"
  exit 1
fi
echo "Deployment failed and no previous healthy image tag is recorded." >&2
exit 1
