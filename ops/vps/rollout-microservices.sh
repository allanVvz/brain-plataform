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
#   bash ops/vps/rollout-microservices.sh finish    # restart workers, clear pause
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

# Workers held to the strict digest rule. They are the reason a rollout needs a
# pause at all; the service containers themselves tolerate a pending digest.
STRICT_WORKERS=(runtime-conversation runtime-validator)

cd "$ROOT_DIR"

[[ -s "$MANIFEST" ]] || { echo "release manifest missing: $MANIFEST" >&2; exit 1; }
[[ -s "$SLOTS" ]] || { echo "microservice slot state missing: $SLOTS" >&2; exit 1; }

slot_of() {
  python3 -c 'import json,sys; print((json.load(open(sys.argv[1],encoding="utf-8")).get(sys.argv[2]) or {}).get("active") or "")' "$SLOTS" "$1"
}
expected_digest() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["services"][sys.argv[2]]["digest"])' "$MANIFEST" "$1"
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
done

if paused; then pause_state="paused"; else pause_state="NOT paused"; fi
printf '\nclaims: %s\n' "$pause_state"

case "$MODE" in
  status)
    if [[ ${#behind[@]} -eq 0 ]]; then
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
    for worker in "${STRICT_WORKERS[@]}"; do
      for slot in blue green; do
        name="brain-ai-${worker}-${slot}-1"
        if [[ -n "$(docker ps -q --filter "name=^/${name}$")" ]]; then
          docker stop "$name" >/dev/null && echo "stopped $name"
        fi
      done
    done
    echo "workers stopped; the preflight will now accept a pending worker digest."
    ;;

  finish)
    for worker in "${STRICT_WORKERS[@]}"; do
      for slot in blue green; do
        name="brain-ai-${worker}-${slot}-1"
        if [[ -n "$(docker ps -aq --filter "name=^/${name}$")" && -z "$(docker ps -q --filter "name=^/${name}$")" ]]; then
          docker start "$name" >/dev/null && echo "started $name"
        fi
      done
    done
    if [[ -e "$PAUSE_MARKER" ]]; then
      rm -f "$PAUSE_MARKER" && echo "cleared $PAUSE_MARKER"
    fi
    echo "rollout finished; re-run 'status' to confirm every service matches the manifest."
    ;;

  *)
    echo "usage: rollout-microservices.sh [status|prepare|finish]" >&2
    exit 2
    ;;
esac
