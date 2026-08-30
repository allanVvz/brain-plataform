#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
MANIFEST="${1:?usage: deploy-microservice-blue-green.sh MANIFEST SERVICE [--apply|--rollback]}"
SERVICE="${2:?usage: deploy-microservice-blue-green.sh MANIFEST SERVICE [--apply|--rollback]}"
ACTION="${3:---dry-run}"
STATE_DIR="$ROOT_DIR/.deploy/microservices"
STATE_FILE="$STATE_DIR/slots.json"
CADDY_DIR="$ROOT_DIR/.deploy/caddy"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/infra/microservices/docker-compose.blue-green.yml")

case "$SERVICE" in
  gateway|control-plane|conversation-runtime|transport) ;;
  *) echo "unknown service: $SERVICE" >&2; exit 2 ;;
esac
case "$ACTION" in
  --dry-run|--apply|--rollback) ;;
  *) echo "unknown action: $ACTION" >&2; exit 2 ;;
esac

python3 "$ROOT_DIR/ops/microservices/validate-release-manifest.py" "$MANIFEST"

manifest_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(data[sys.argv[2]] if sys.argv[2] != "service" else data["services"][sys.argv[3]][sys.argv[4]])' "$MANIFEST" "$@"
}

export BRAIN_CONTRACTS_VERSION="$(manifest_value contracts_version)"
export GATEWAY_SHA="$(manifest_value service gateway sha)"
export GATEWAY_DIGEST="$(manifest_value service gateway digest)"
export CONTROL_PLANE_SHA="$(manifest_value service control-plane sha)"
export CONTROL_PLANE_DIGEST="$(manifest_value service control-plane digest)"
export RUNTIME_SHA="$(manifest_value service conversation-runtime sha)"
export RUNTIME_DIGEST="$(manifest_value service conversation-runtime digest)"
export TRANSPORT_SHA="$(manifest_value service transport sha)"
export TRANSPORT_DIGEST="$(manifest_value service transport digest)"

export GATEWAY_IMAGE_BLUE="ghcr.io/allanvvz/brain-gateway@$GATEWAY_DIGEST"
export GATEWAY_IMAGE_GREEN="$GATEWAY_IMAGE_BLUE"
export CONTROL_PLANE_IMAGE_BLUE="ghcr.io/allanvvz/brain-control-plane@$CONTROL_PLANE_DIGEST"
export CONTROL_PLANE_IMAGE_GREEN="$CONTROL_PLANE_IMAGE_BLUE"
export RUNTIME_IMAGE_BLUE="ghcr.io/allanvvz/brain-conversation-runtime@$RUNTIME_DIGEST"
export RUNTIME_IMAGE_GREEN="$RUNTIME_IMAGE_BLUE"
export TRANSPORT_IMAGE_BLUE="ghcr.io/allanvvz/brain-transport@$TRANSPORT_DIGEST"
export TRANSPORT_IMAGE_GREEN="$TRANSPORT_IMAGE_BLUE"
export GATEWAY_ENV_FILE="${GATEWAY_ENV_FILE:-$ROOT_DIR/.env.microservices/gateway.env}"
export CONTROL_PLANE_ENV_FILE="${CONTROL_PLANE_ENV_FILE:-$ROOT_DIR/.env.microservices/control-plane.env}"
export RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-$ROOT_DIR/.env.microservices/runtime.env}"
export TRANSPORT_ENV_FILE="${TRANSPORT_ENV_FILE:-$ROOT_DIR/.env.microservices/transport.env}"

compose_service="${SERVICE/conversation-runtime/runtime}"

read_state() {
  local field="$1"
  python3 -c 'import json,sys; p=sys.argv[1]; data=json.load(open(p, encoding="utf-8")) if __import__("os").path.exists(p) else {}; value=data.get(sys.argv[2], {}); print(value.get(sys.argv[3], "") if isinstance(value, dict) else (value if sys.argv[3] == "active" else ""))' "$STATE_FILE" "$SERVICE" "$field"
}

active="$(read_state active)"
previous="$(read_state previous)"
if [[ "$ACTION" == "--rollback" ]]; then
  [[ "$previous" =~ ^(blue|green)$ ]] || { echo "no rollback slot recorded for $SERVICE" >&2; exit 1; }
  target="$previous"
else
  [[ "$active" == "blue" ]] && target="green" || target="blue"
fi
target_service="$compose_service-$target"
case "$SERVICE" in
  gateway)
    target_services=("$target_service")
    ;;
  control-plane)
    target_services=("$target_service" "control-plane-knowledge-$target" "control-plane-integrations-$target" "control-plane-validator-$target")
    ;;
  conversation-runtime)
    target_services=("$target_service" "runtime-conversation-$target" "runtime-validator-$target")
    ;;
  transport)
    target_services=("$target_service" "transport-dispatch-$target" "transport-media-$target")
    ;;
esac

echo "service=$SERVICE action=$ACTION active=${active:-none} target=$target manifest=$(basename "$MANIFEST")"
if [[ "$ACTION" == "--dry-run" ]]; then
  "${COMPOSE[@]}" config --quiet
  exit 0
fi

for required in "$ENV_FILE" "$GATEWAY_ENV_FILE" "$CONTROL_PLANE_ENV_FILE" "$RUNTIME_ENV_FILE" "$TRANSPORT_ENV_FILE"; do
  [[ -s "$required" ]] || { echo "missing required environment file: $required" >&2; exit 1; }
done
mkdir -p "$STATE_DIR" "$CADDY_DIR"
if [[ ! -s "$STATE_FILE" ]]; then
  printf '%s\n' '{"gateway":{"active":"legacy","previous":null}}' > "$STATE_FILE"
fi

# The split services depend on the private :8090 listener. Older production
# releases can have a valid active Caddyfile that predates that listener even
# though the generated internal-upstreams file is already current. Install the
# approved base config atomically before waiting on gateway readiness, while
# preserving the current public-upstream file (and therefore legacy traffic).
install_active_caddy_config() {
  local approved="$ROOT_DIR/infra/Caddyfile"
  local active="$CADDY_DIR/Caddyfile"
  local previous="$STATE_DIR/Caddyfile.previous"
  local candidate

  [[ -s "$approved" ]] || { echo "missing approved Caddyfile: $approved" >&2; return 1; }
  [[ -s "$active" ]] || { echo "missing active Caddyfile: $active" >&2; return 1; }
  cmp -s "$approved" "$active" && return 0

  cp "$active" "$previous"
  candidate="$(mktemp "$CADDY_DIR/.Caddyfile.microservice.XXXXXX")"
  cp "$approved" "$candidate"
  chmod 0644 "$candidate"
  mv -f "$candidate" "$active"

  if ! "${COMPOSE[@]}" exec -T caddy caddy validate --config /etc/caddy/Caddyfile; then
    cp "$previous" "$active"
    return 1
  fi
  if ! "${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile; then
    cp "$previous" "$active"
    "${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile || true
    return 1
  fi
  echo "installed approved Caddy base config; public upstream unchanged"
}

install_active_caddy_config

pull_candidate_images() {
  local pull_attempt
  for pull_attempt in 1 2 3 4; do
    if "${COMPOSE[@]}" pull "${target_services[@]}"; then
      return 0
    fi
    if (( pull_attempt == 4 )); then
      echo "image pull failed after ${pull_attempt} attempts" >&2
      return 1
    fi
    echo "image pull attempt ${pull_attempt} failed; retrying" >&2
    sleep $((pull_attempt * 5))
  done
}

if [[ "$ACTION" == "--rollback" ]]; then
  "${COMPOSE[@]}" start "${target_services[@]}"
else
  pull_candidate_images
  if [[ -s "$ROOT_DIR/.deploy/control/claims-paused.json" && ${#target_services[@]} -gt 1 ]]; then
    "${COMPOSE[@]}" up -d --no-deps --force-recreate "$target_service"
    "${COMPOSE[@]}" stop -t 120 "${target_services[@]:1}" >/dev/null 2>&1 || true
    workers_paused=true
  else
    "${COMPOSE[@]}" up -d --no-deps --force-recreate "${target_services[@]}"
    workers_paused=false
  fi
fi

deadline=$((SECONDS + 180))
until [[ "$("${COMPOSE[@]}" ps --format json "$target_service" | python3 -c 'import json,sys; rows=[json.loads(x) for x in sys.stdin if x.strip()]; print(rows[0].get("Health", "") if rows else "")')" == "healthy" ]]; do
  (( SECONDS < deadline )) || { echo "readiness timeout for $target_service" >&2; exit 1; }
  sleep 3
done
if [[ "${workers_paused:-false}" != "true" ]]; then
  for candidate_service in "${target_services[@]:1}"; do
    [[ "$("${COMPOSE[@]}" ps --status running --services "$candidate_service")" == "$candidate_service" ]] || {
      echo "worker group failed to remain running: $candidate_service" >&2
      exit 1
    }
  done
fi

candidate="$STATE_DIR/slots.candidate.json"
python3 - "$STATE_FILE" "$candidate" "$SERVICE" "$target" "$active" <<'PY'
import json, sys
source, target_path, service, target_slot, old_slot = sys.argv[1:]
data = json.load(open(source, encoding="utf-8"))
data[service] = {"active": target_slot, "previous": old_slot or None}
with open(target_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

rendered="$STATE_DIR/caddy-candidate"
python3 "$ROOT_DIR/ops/microservices/render-active-routes.py" "$candidate" "$rendered"
cp "$CADDY_DIR/public-upstream.caddy" "$STATE_DIR/public-upstream.previous.caddy" 2>/dev/null || true
cp "$CADDY_DIR/internal-upstreams.caddy" "$STATE_DIR/internal-upstreams.previous.caddy" 2>/dev/null || true
cp "$rendered/public-upstream.caddy" "$CADDY_DIR/public-upstream.caddy"
cp "$rendered/internal-upstreams.caddy" "$CADDY_DIR/internal-upstreams.caddy"

if ! "${COMPOSE[@]}" exec -T caddy caddy validate --config /etc/caddy/Caddyfile; then
  cp "$STATE_DIR/public-upstream.previous.caddy" "$CADDY_DIR/public-upstream.caddy" 2>/dev/null || true
  cp "$STATE_DIR/internal-upstreams.previous.caddy" "$CADDY_DIR/internal-upstreams.caddy" 2>/dev/null || true
  exit 1
fi
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
mv "$candidate" "$STATE_FILE"

if [[ "$active" =~ ^(blue|green)$ && "$active" != "$target" ]]; then
  old_services=("$compose_service-$active")
  case "$SERVICE" in
    control-plane) old_services+=("control-plane-knowledge-$active" "control-plane-integrations-$active" "control-plane-validator-$active") ;;
    conversation-runtime) old_services+=("runtime-conversation-$active" "runtime-validator-$active") ;;
    transport) old_services+=("transport-dispatch-$active" "transport-media-$active") ;;
  esac
  "${COMPOSE[@]}" stop -t 120 "${old_services[@]}"
fi
echo "activated service=$SERVICE slot=$target; previous=${active:-none} workers_paused=${workers_paused:-false}"
