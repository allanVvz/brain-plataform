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
python3 "$ROOT_DIR/ops/microservices/bootstrap-service-envs.py" --check

manifest_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(data[sys.argv[2]] if sys.argv[2] != "service" else data["services"][sys.argv[3]][sys.argv[4]])' "$MANIFEST" "$@"
}

service_value_or_global() {
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); s=d["services"][sys.argv[2]]; print(s.get(sys.argv[3]) or d[sys.argv[4]])' "$MANIFEST" "$SERVICE" "$1" "$2"
}

export BRAIN_CONTRACTS_VERSION="$(service_value_or_global contracts_version contracts_version)"
export BRAIN_CONTRACTS_SHA="$(service_value_or_global contracts_checksum contracts_checksum)"
export REQUIRED_SCHEMA_VERSION="$(manifest_value service "$SERVICE" required_schema_version)"
export CURRENT_SCHEMA_VERSION="$REQUIRED_SCHEMA_VERSION"
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

old_services=()
if [[ "$active" =~ ^(blue|green)$ && "$active" != "$target" ]]; then
  old_services=("$compose_service-$active")
  case "$SERVICE" in
    control-plane) old_services+=("control-plane-knowledge-$active" "control-plane-integrations-$active" "control-plane-validator-$active") ;;
    conversation-runtime) old_services+=("runtime-conversation-$active" "runtime-validator-$active") ;;
    transport) old_services+=("transport-dispatch-$active" "transport-media-$active") ;;
  esac
fi

activated=false
mutation_started=false
candidate_started=false
routes_staged=false
state_backup="$STATE_DIR/slots.previous-${SERVICE}.json"
public_route_backup="$STATE_DIR/public-upstream.previous-${SERVICE}.caddy"
internal_route_backup="$STATE_DIR/internal-upstreams.previous-${SERVICE}.caddy"
release_key="$(manifest_value service "$SERVICE" sha)-$(manifest_value service "$SERVICE" digest)"
release_record="$STATE_DIR/releases/$SERVICE/$release_key.json"
rollback_on_error() {
  local code=$?
  trap - ERR
  set +e
  if [[ "$mutation_started" == "true" ]]; then
    echo "deployment failed after cutover; restoring service=$SERVICE slot=$active" >&2
    if [[ "$routes_staged" == "true" ]]; then
      cp "$public_route_backup" "$CADDY_DIR/public-upstream.caddy"
      cp "$internal_route_backup" "$CADDY_DIR/internal-upstreams.caddy"
      cp "$state_backup" "$STATE_FILE"
      "${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
    fi
    if [[ ${#old_services[@]} -gt 0 ]]; then
      "${COMPOSE[@]}" start "${old_services[@]}"
    fi
    "${COMPOSE[@]}" stop -t 45 "${target_services[@]}"
  elif [[ "$candidate_started" == "true" ]]; then
    # A failed isolated candidate never received traffic, but it must not be
    # left running and mistaken for a promotable slot on the next release.
    "${COMPOSE[@]}" stop -t 45 "$target_service"
  fi
  exit "$code"
}
trap rollback_on_error ERR

echo "service=$SERVICE action=$ACTION active=${active:-none} target=$target manifest=$(basename "$MANIFEST")"
if [[ "$ACTION" == "--dry-run" ]]; then
  "${COMPOSE[@]}" config --quiet
  exit 0
fi

if [[ "$ACTION" == "--apply" && -s "$release_record" ]]; then
  echo "release already promoted service=$SERVICE key=$release_key"
  exit 0
fi

for required in "$ENV_FILE" "$GATEWAY_ENV_FILE" "$CONTROL_PLANE_ENV_FILE" "$RUNTIME_ENV_FILE" "$TRANSPORT_ENV_FILE"; do
  [[ -s "$required" ]] || { echo "missing required environment file: $required" >&2; exit 1; }
done
if [[ "$ACTION" == "--apply" ]]; then
  # Re-render least-privilege envs from the approved production source before
  # the candidate starts. This prevents a compatible code release from using
  # stale service allowlists while preserving the existing internal secret.
  python3 "$ROOT_DIR/ops/microservices/bootstrap-service-envs.py"
fi
mkdir -p "$STATE_DIR" "$CADDY_DIR"
if [[ ! -s "$STATE_FILE" ]]; then
  printf '%s\n' '{"gateway":{"active":"legacy","previous":null}}' > "$STATE_FILE"
fi

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
  # A rollback restores the HTTP service immediately, but it must not wake
  # queue consumers while a release-wide safety pause is in effect.  The old
  # behaviour started every sidecar here, defeating the pause during a
  # recovery.
  if [[ -s "$ROOT_DIR/.deploy/control/claims-paused.json" && ${#target_services[@]} -gt 1 ]]; then
    "${COMPOSE[@]}" start "$target_service"
    "${COMPOSE[@]}" stop -t 120 "${target_services[@]:1}" >/dev/null 2>&1 || true
    workers_paused=true
  else
    "${COMPOSE[@]}" start "${target_services[@]}"
    workers_paused=false
  fi
else
  pull_candidate_images
  # A candidate is isolated: only its HTTP API starts before validation.
  # Queue consumers move once, immediately before the route cutover.
  "${COMPOSE[@]}" up -d --no-deps --force-recreate "$target_service"
  candidate_started=true
  workers_paused=false
fi

deadline=$((SECONDS + 180))
until [[ "$("${COMPOSE[@]}" ps --format json "$target_service" | python3 -c 'import json,sys; rows=[json.loads(x) for x in sys.stdin if x.strip()]; print(rows[0].get("Health", "") if rows else "")')" == "healthy" ]]; do
  (( SECONDS < deadline )) || { echo "readiness timeout for $target_service" >&2; exit 1; }
  sleep 3
done

expected_sha="$(manifest_value service "$SERVICE" sha)"
# Docker's healthcheck is the candidate's real readiness probe. Do not issue a
# second HTTP probe here: it duplicates the contract and may travel through a
# container-specific auth path even though the healthcheck already proved the
# listener and database readiness. Verify immutable provenance in-process.
if [[ "$ACTION" == "--rollback" ]]; then
  "${COMPOSE[@]}" exec -T "$target_service" python -c \
    'import os,re; assert re.fullmatch(r"[0-9a-f]{40}", os.environ["SOURCE_SHA"])'
else
  "${COMPOSE[@]}" exec -T "$target_service" python -c \
    'import os,sys; assert os.environ["SOURCE_SHA"] == sys.argv[1]' \
    "$expected_sha"
fi

if [[ "$ACTION" == "--apply" && "$SERVICE" == "conversation-runtime" ]]; then
  # Candidate-only contract smoke: execute the exact image through its private
  # application surface before any worker starts or public route changes. The
  # HTTP listener has already been proven by the container healthcheck above.
  "${COMPOSE[@]}" exec -T "$target_service" python -c \
    'from main import app; p=app.openapi()["paths"]; required={"/internal/v1/conversations/resolve-understanding","/internal/v1/conversations/execute-agentic"}; assert required <= set(p), sorted(required-set(p))'
fi

# Move only this service's consumers. The old consumers receive at most the
# documented 45 second drain; no global claim pause is used.
# Candidates remain parallel. Only the shared route/state promotion is locked,
# preventing two services from overwriting each other's slot update.
exec 9>"$STATE_DIR/cutover.lock"
flock -w 120 9
mutation_started=true
if [[ ${#old_services[@]} -gt 1 ]]; then
  "${COMPOSE[@]}" stop -t 45 "${old_services[@]:1}"
fi
if [[ ${#target_services[@]} -gt 1 ]]; then
  "${COMPOSE[@]}" up -d --no-deps --force-recreate "${target_services[@]:1}"
  for candidate_service in "${target_services[@]:1}"; do
    [[ "$("${COMPOSE[@]}" ps --status running --services "$candidate_service")" == "$candidate_service" ]] || {
      echo "worker group failed to start: $candidate_service" >&2
      exit 1
    }
  done
fi

# Candidate state is per service.  A shared filename allowed simultaneous
# deploy workflows to move each other's candidate and strand routing on an
# empty slot.
candidate="$STATE_DIR/slots.${SERVICE}.candidate.json"
python3 - "$STATE_FILE" "$candidate" "$SERVICE" "$target" "$active" <<'PY'
import json, sys
source, target_path, service, target_slot, old_slot = sys.argv[1:]
data = json.load(open(source, encoding="utf-8"))
data[service] = {"active": target_slot, "previous": old_slot or None}
with open(target_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

rendered="$STATE_DIR/caddy-candidate-${SERVICE}"
python3 "$ROOT_DIR/ops/microservices/render-active-routes.py" "$candidate" "$rendered"
cp "$CADDY_DIR/public-upstream.caddy" "$public_route_backup" 2>/dev/null || true
cp "$CADDY_DIR/internal-upstreams.caddy" "$internal_route_backup" 2>/dev/null || true
cp "$STATE_FILE" "$state_backup"
cp "$rendered/public-upstream.caddy" "$CADDY_DIR/public-upstream.caddy"
cp "$rendered/internal-upstreams.caddy" "$CADDY_DIR/internal-upstreams.caddy"
routes_staged=true

if ! "${COMPOSE[@]}" exec -T caddy caddy validate --config /etc/caddy/Caddyfile; then
  cp "$public_route_backup" "$CADDY_DIR/public-upstream.caddy" 2>/dev/null || true
  cp "$internal_route_backup" "$CADDY_DIR/internal-upstreams.caddy" 2>/dev/null || true
  exit 1
fi
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
activated=true
mv "$candidate" "$STATE_FILE"

if [[ ${#old_services[@]} -gt 0 ]]; then
  "${COMPOSE[@]}" stop -t 45 "${old_services[0]}"
fi
if [[ "$ACTION" == "--apply" ]]; then
  mkdir -p "$(dirname "$release_record")"
  printf '%s\n' "{\"service\":\"$SERVICE\",\"sha\":\"$expected_sha\",\"digest\":\"$(manifest_value service "$SERVICE" digest)\",\"slot\":\"$target\"}" > "$release_record"
else
  rm -f "$release_record"
fi
flock -u 9
trap - ERR
echo "activated service=$SERVICE slot=$target; previous=${active:-none} workers_paused=${workers_paused:-false}"
