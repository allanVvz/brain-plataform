#!/usr/bin/env bash
# Microservice rollout, collapsed into three commands.
#
# Production runs four microservice images in blue/green: gateway, control-plane,
# conversation-runtime, transport. Bringing them to a manifest normally means
# reconstructing, by hand, which services are behind, why a preflight refuses,
# and what has to be stopped first. This script answers that in one read-only
# call and then performs the two mechanical halves around the single step an
# operator has to authorise.
#
#   bash ops/vps/rollout-microservices.sh status    # read-only, safe, start here
#   bash ops/vps/rollout-microservices.sh prepare   # stop stale workers (needs pause)
#   bash ops/vps/rollout-microservices.sh finish    # recreate workers, clear pause
#
# The pause itself is deliberately NOT here. Pausing claims stops a live
# customer-facing agent, so it stays an explicit operator action:
#
#   bash ops/vps/pause-worker-claims.sh '<reason>' --safety-pause
#
# Between `prepare` and `finish`, deploy through the sanctioned workflows --
# `status` prints the exact dispatch lines for the services that are behind.
#
# Why `prepare` exists at all: validate-production-release.sh checks service
# containers and worker containers with different rules. A service may carry a
# pending digest and only warns (ALLOW_PENDING_MICROSERVICE_DIGESTS); a worker
# has no such escape and passes only while it is stopped and claims are paused.
# That asymmetry is what makes a runtime rollout look impossible until you know
# it.
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:-status}"
MANIFEST="$ROOT_DIR/ops/microservices/release-manifest.json"
SLOTS="$ROOT_DIR/.deploy/microservices/slots.json"
PAUSE_MARKER="$ROOT_DIR/.deploy/control/claims-paused.json"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/infra/microservices/docker-compose.blue-green.yml")

# Sidecar workers a service owns. They are the reason a rollout needs a pause at
# all: the service container tolerates a pending digest and only warns, while a
# worker has no such escape. This list was once two entries and that was wrong --
# stopping only those left transport-dispatch, the outbound WhatsApp sender,
# running on a stale digest, and a later manual stop of it was not restored by
# `finish` because `finish` trusted the same short list.
declare -A SERVICE_WORKERS=(
  [conversation-runtime]="runtime-conversation runtime-validator"
  [control-plane]="control-plane-knowledge control-plane-integrations control-plane-validator"
  [transport]="transport-dispatch transport-media"
  [gateway]=""
)

# What `prepare` stopped, so `finish` restores exactly that instead of guessing.
STOPPED_RECORD="$ROOT_DIR/.deploy/control/rollout-stopped.txt"

cd "$ROOT_DIR"

[[ -s "$MANIFEST" ]] || { echo "release manifest missing: $MANIFEST" >&2; exit 1; }
[[ -s "$SLOTS" ]] || { echo "microservice slot state missing: $SLOTS" >&2; exit 1; }

slot_of() {
  python3 -c 'import json,sys; print((json.load(open(sys.argv[1],encoding="utf-8")).get(sys.argv[2]) or {}).get("active") or "")' "$SLOTS" "$1"
}
expected_digest() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["services"][sys.argv[2]]["digest"])' "$MANIFEST" "$1"
}
manifest_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1],encoding="utf-8")); print(data[sys.argv[2]] if sys.argv[2] != "service" else data["services"][sys.argv[3]][sys.argv[4]])' "$MANIFEST" "$@"
}
configure_manifest_environment() {
  python3 "$ROOT_DIR/ops/microservices/validate-release-manifest.py" "$MANIFEST"
  export BRAIN_CONTRACTS_VERSION="$(manifest_value contracts_version)"
  export REQUIRED_SCHEMA_VERSION="$(manifest_value schema_version)"
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
  for required in "$ENV_FILE" "$GATEWAY_ENV_FILE" "$CONTROL_PLANE_ENV_FILE" "$RUNTIME_ENV_FILE" "$TRANSPORT_ENV_FILE"; do
    [[ -s "$required" ]] || { echo "missing required environment file: $required" >&2; return 1; }
  done
}
running_digest() {
  local cid
  cid="$(docker ps -q --filter "name=^/$1$")" || true
  [[ -n "$cid" ]] || { echo ""; return; }
  docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' \
    "$(docker inspect -f '{{.Image}}' "$cid")" 2>/dev/null | head -1 | sed 's/.*@//' | tr -d '\r\n'
}
paused() { python3 - "$PAUSE_MARKER" <<'PY'
import json, sys
from pathlib import Path
try:
    raise SystemExit(0 if json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("paused") is True else 1)
except (OSError, json.JSONDecodeError, AttributeError):
    raise SystemExit(1)
PY
}

behind=()
# Running workers whose digest does not match the manifest. The preflight
# fails on each of these unless it is stopped while claims are paused.
blocking=()
for service in gateway control-plane conversation-runtime transport; do
  slot="$(slot_of "$service")"
  compose_name="${service/conversation-runtime/runtime}"
  want="$(expected_digest "$service")"
  have="$(running_digest "brain-ai-${compose_name}-${slot}-1")"
  if [[ "$want" == "$have" ]]; then
    state="up to date"
  elif [[ -z "$have" ]]; then
    state="NOT RUNNING"
    behind+=("$service")
  else
    state="BEHIND"
    behind+=("$service")
  fi
  printf '%-22s slot=%-6s %s\n' "$service" "$slot" "$state"
  [[ "$state" == "up to date" ]] || printf '%-22s   want %s\n%-22s   have %s\n' "" "$want" "" "${have:-<none>}"

  # A worker is judged on its own digest, not on its service's state. The
  # preflight compares every worker against the manifest, and a worker mismatch
  # is a hard FAIL with no pending-digest escape, so a service can read "up to
  # date" while its own workers block its deploy. That is what happened to
  # control-plane on 2026-09-05: three workers on a digest nobody had noticed.
  for worker in ${SERVICE_WORKERS[$service]}; do
    name="brain-ai-${worker}-${slot}-1"
    [[ -n "$(docker ps -q --filter "name=^/${name}$")" ]] || continue
    if [[ "$(running_digest "$name")" != "$want" ]]; then
      blocking+=("$name")
    fi
  done
done

if paused; then pause_state="paused"; else pause_state="NOT paused"; fi
printf '\nclaims: %s\n' "$pause_state"

case "$MODE" in
  status)
    if [[ ${#blocking[@]} -gt 0 ]]; then
      printf '\nworkers that fail the preflight until stopped (%d):\n' "${#blocking[@]}"
      printf '  %s\n' "${blocking[@]}"
    fi
    if [[ ${#behind[@]} -eq 0 && ${#blocking[@]} -eq 0 ]]; then
      echo "nothing to roll out."
      exit 0
    fi
    echo
    echo "to roll out:"
    if ! paused; then
      echo "  1. an operator authorises the pause (this script never does it):"
      echo "     bash ops/vps/pause-worker-claims.sh 'rollout' --safety-pause"
      echo "  2. bash ops/vps/rollout-microservices.sh prepare"
    else
      echo "  1. bash ops/vps/rollout-microservices.sh prepare"
    fi
    echo "  next, dispatch one workflow per service that is behind:"
    for service in "${behind[@]}"; do
      case "$service" in
        control-plane) wf="Deploy control plane" ;;
        conversation-runtime) wf="Deploy runtime" ;;
        transport) wf="Deploy transport" ;;
        gateway) wf="Deploy gateway" ;;
      esac
      printf '     gh workflow run "%s" --ref main -f manifest_sha=<sha> -f action=deploy\n' "$wf"
    done
    echo "  finally: bash ops/vps/rollout-microservices.sh finish"
    ;;

  prepare)
    paused || {
      echo >&2
      echo "refusing: claims are not paused." >&2
      echo "Stopping these workers while they claim work would drop a turn in flight." >&2
      echo "An operator must authorise the pause first:" >&2
      echo "  bash ops/vps/pause-worker-claims.sh 'rollout' --safety-pause" >&2
      exit 1
    }
    mkdir -p "$(dirname "$STOPPED_RECORD")"
    : > "$STOPPED_RECORD"
    # Exactly the workers the preflight would reject. Stopping one already on
    # the manifest digest buys nothing and lengthens the outage; leaving one
    # that is off-digest fails the deploy after the pause is already in place.
    for name in ${blocking[@]+"${blocking[@]}"}; do
      docker stop "$name" >/dev/null && echo "$name" >> "$STOPPED_RECORD" && echo "stopped $name"
    done
    if [[ ! -s "$STOPPED_RECORD" ]]; then
      echo "no worker needed stopping."
    fi
    echo "recorded in $STOPPED_RECORD; 'finish' restarts exactly these."
    ;;

  finish)
    paused || {
      echo "refusing: claims are not paused; workers must be recreated before the pause is released." >&2
      exit 1
    }
    configure_manifest_environment

    # The mirror of the rule above: a worker left running on a slot that is no
    # longer active consumes the same queue on a stale image.
    for service in gateway control-plane conversation-runtime transport; do
      slot="$(slot_of "$service")"
      idle="green"; [[ "$slot" == "green" ]] && idle="blue"
      for worker in ${SERVICE_WORKERS[$service]}; do
        name="brain-ai-${worker}-${idle}-1"
        if [[ -n "$(docker ps -q --filter "name=^/${name}$")" ]]; then
          docker stop "$name" >/dev/null && echo "stopped $name (retired slot still on the queue)"
        fi
      done
    done

    # A slot flip changes the active side after `prepare`.  Never `docker start`
    # a previously stopped worker here: it retains the old image.  Recreate every
    # active worker from the manifest while claims remain paused, then prove its
    # immutable image digest before removing the pause marker.
    active_workers=()
    for service in control-plane conversation-runtime transport; do
      slot="$(slot_of "$service")"
      for worker in ${SERVICE_WORKERS[$service]}; do
        active_workers+=("${worker}-${slot}")
      done
    done
    "${COMPOSE[@]}" pull "${active_workers[@]}"
    "${COMPOSE[@]}" up -d --no-deps --force-recreate "${active_workers[@]}"
    for service in control-plane conversation-runtime transport; do
      slot="$(slot_of "$service")"
      want="$(expected_digest "$service")"
      for worker in ${SERVICE_WORKERS[$service]}; do
        name="brain-ai-${worker}-${slot}-1"
        [[ -n "$(docker ps -q --filter "name=^/${name}$")" ]] || {
          echo "worker did not start on the active slot: $name" >&2
          exit 1
        }
        [[ "$(running_digest "$name")" == "$want" ]] || {
          echo "worker digest mismatch after recreate: $name" >&2
          exit 1
        }
      done
    done
    rm -f "$STOPPED_RECORD"

    if [[ -e "$PAUSE_MARKER" ]]; then
      rm -f "$PAUSE_MARKER" && echo "cleared $PAUSE_MARKER"
    fi
    echo "recreated ${#active_workers[@]} active-slot workers; re-run 'status' to confirm every service matches the manifest."
    ;;

  *)
    echo "usage: rollout-microservices.sh [status|prepare|finish]" >&2
    exit 2
    ;;
esac
