#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
TARGET_SHA="${1:?usage: deploy-api-blue-green.sh <full-git-sha>}"
API_CUTOVER_SOAK_SECONDS="${API_CUTOVER_SOAK_SECONDS:-15}"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "full Git SHA required" >&2; exit 2; }
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)

active="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active" == "api" || "$active" == "api-candidate" ]] || active=api
if [[ "$active" == "api" ]]; then
  inactive=api-candidate
  export CANDIDATE_API_TAG="$TARGET_SHA"
else
  inactive=api
  export API_TAG="$TARGET_SHA"
fi

if [[ "$inactive" == "api-candidate" ]]; then
  "${COMPOSE_BG[@]}" up -d --no-deps api-candidate
  local_bind="$("${COMPOSE_BG[@]}" port api-candidate 8080)"
else
  "${COMPOSE[@]}" up -d --no-deps api
  local_bind="$("${COMPOSE[@]}" port api 8080)"
fi
deadline=$((SECONDS + 180))
until curl --fail --silent --show-error "http://$local_bind/health/ready" >/dev/null; do
  (( SECONDS < deadline )) || {
    echo "inactive API slot did not become ready: $inactive" >&2
    exit 1
  }
  sleep 2
done
inactive_cid="$("${COMPOSE_BG[@]}" ps -q "$inactive")"
inactive_sha="$(docker exec "$inactive_cid" sh -c 'tr -d "\r\n" < /image-source-sha')"
[[ "$inactive_sha" == "$TARGET_SHA" ]] || { echo "candidate API SHA mismatch" >&2; exit 1; }

mkdir -p .deploy/caddy
caddy_next="$(mktemp .deploy/caddy/.Caddyfile.next.XXXXXX)"
if [[ "$inactive" == "api-candidate" ]]; then
  sed 's/reverse_proxy api:8080/reverse_proxy api-candidate:8080/g' \
    infra/Caddyfile > "$caddy_next"
else
  cp infra/Caddyfile "$caddy_next"
fi
chmod 0644 "$caddy_next"
caddy_cid="$("${COMPOSE[@]}" ps -q caddy)"
[[ -n "$caddy_cid" ]] || { echo "Caddy is not running" >&2; exit 1; }
cutover_loaded=false
restore_previous_upstream() {
  local exit_code="$?"
  if [[ "$cutover_loaded" == "true" && -s .deploy/caddy/Caddyfile ]]; then
    docker cp .deploy/caddy/Caddyfile "$caddy_cid:/tmp/Caddyfile.rollback" || true
    docker exec "$caddy_cid" caddy reload \
      --config /tmp/Caddyfile.rollback --adapter caddyfile \
      --address 127.0.0.1:2019 || true
  fi
  if [[ "$inactive" == "api-candidate" ]]; then
    "${COMPOSE_BG[@]}" stop api-candidate >/dev/null 2>&1 || true
  else
    "${COMPOSE[@]}" stop api >/dev/null 2>&1 || true
  fi
  rm -f "$caddy_next"
  exit "$exit_code"
}
trap restore_previous_upstream ERR

# Releases before the blue-green lifecycle ran Caddy with `admin off`. The
# first rollout recreates only Caddy with the still-active upstream so the
# local-only admin endpoint becomes available. Subsequent rollouts reload
# gracefully without recreating the edge container.
if ! docker exec "$caddy_cid" caddy reload \
  --config /etc/caddy/Caddyfile --adapter caddyfile \
  --address 127.0.0.1:2019 >/dev/null 2>&1; then
  echo "bootstrapping local Caddy admin endpoint"
  "${COMPOSE[@]}" up -d --no-deps --force-recreate caddy
  caddy_cid="$("${COMPOSE[@]}" ps -q caddy)"
  admin_deadline=$((SECONDS + 60))
  until docker exec "$caddy_cid" caddy reload \
    --config /etc/caddy/Caddyfile --adapter caddyfile \
    --address 127.0.0.1:2019 >/dev/null 2>&1; do
    (( SECONDS < admin_deadline )) || {
      echo "Caddy local admin endpoint did not become ready" >&2
      exit 1
    }
    sleep 1
  done
fi
docker cp "$caddy_next" "$caddy_cid:/tmp/Caddyfile.next"
docker exec "$caddy_cid" caddy validate --config /tmp/Caddyfile.next --adapter caddyfile
docker exec "$caddy_cid" caddy reload --config /tmp/Caddyfile.next --adapter caddyfile \
  --address 127.0.0.1:2019
cutover_loaded=true

api_domain="$(awk -F= '
  /^[[:space:]]*API_DOMAIN[[:space:]]*=/ {
    value=$2; gsub(/[[:space:]"\047]/,"",value); print value
  }' "$ENV_FILE" | tail -n 1)"
[[ -n "$api_domain" ]] || { echo "API_DOMAIN is missing" >&2; exit 1; }
soak_deadline=$((SECONDS + API_CUTOVER_SOAK_SECONDS))
while (( SECONDS < soak_deadline )); do
  external_ready="$(curl --fail --silent --show-error "https://$api_domain/health/ready")"
  printf '%s' "$external_ready" | python3 -c \
    'import json,sys; value=json.load(sys.stdin); expected=sys.argv[1]; raise SystemExit(0 if value.get("source_sha")==expected else 1)' \
    "$TARGET_SHA"
  [[ "$(docker inspect -f '{{.State.Status}}' "$inactive_cid")" == "running" ]]
  sleep 2
done

if [[ "$active" == "api-candidate" ]]; then
  "${COMPOSE_BG[@]}" stop api-candidate
else
  "${COMPOSE[@]}" stop api
fi
mv -f "$caddy_next" .deploy/caddy/Caddyfile
printf '%s\n' "$inactive" > .deploy/api-active-slot
trap - ERR
printf 'api_cutover\tfrom=%s\tto=%s\tsha=%s\n' "$active" "$inactive" "$TARGET_SHA"
