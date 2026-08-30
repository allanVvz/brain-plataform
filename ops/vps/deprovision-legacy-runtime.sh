#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:---dry-run}"
STATE_FILE="$ROOT_DIR/.deploy/microservices/slots.json"
PUBLIC_UPSTREAM="$ROOT_DIR/.deploy/caddy/public-upstream.caddy"
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "invalid mode" >&2; exit 2; }
[[ "$(realpath "$ROOT_DIR")" == /opt/brain-ai ]] || { echo "unexpected production root" >&2; exit 2; }
cd "$ROOT_DIR"
[[ -s "$STATE_FILE" && -s "$PUBLIC_UPSTREAM" ]] || { echo "microservice cutover evidence missing" >&2; exit 1; }

python3 - "$STATE_FILE" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
for service in ("gateway", "control-plane", "conversation-runtime", "transport"):
    assert (state.get(service) or {}).get("active") in {"blue", "green"}, service
PY
gateway_slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["gateway"]["active"])' "$STATE_FILE")"
grep -Eq "reverse_proxy gateway-${gateway_slot}:8080" "$PUBLIC_UPSTREAM"
! grep -Eq 'reverse_proxy api:8080' "$PUBLIC_UPSTREAM"
python3 - <<'PY'
import json
from pathlib import Path
value = json.loads(Path(".deploy/control/claims-paused.json").read_text(encoding="utf-8"))
assert value.get("paused") is True
PY

for service in gateway control-plane conversation-runtime transport; do
  slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]["active"])' "$STATE_FILE" "$service")"
  compose_name="${service/conversation-runtime/runtime}"
  name="brain-ai-${compose_name}-${slot}-1"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name")"
  [[ "$health" == "healthy" ]] || { echo "$name is not healthy: $health" >&2; exit 1; }
  echo "PASS service=$service slot=$slot health=$health"
done

mapfile -t legacy_images < <(docker image ls --format '{{.Repository}} {{.ID}}' | awk '$1=="ghcr.io/allanvvz/brain-plataform/brain-api" || $1=="ghcr.io/allanvvz/brain-plataform/brain-workers" {print $2}' | sort -u)
mapfile -t legacy_containers < <(
  for image_id in "${legacy_images[@]}"; do
    [[ -n "$image_id" ]] && docker ps -aq --filter "ancestor=$image_id"
  done | sort -u
)
for cid in "${legacy_containers[@]}"; do
  [[ -n "$cid" ]] || continue
  name="$(docker inspect -f '{{.Name}}' "$cid")"
  status="$(docker inspect -f '{{.State.Status}}' "$cid")"
  image_ref="$(docker inspect -f '{{.Image}}' "$cid")"
  echo -e "LEGACY_CONTAINER\t${cid}\t${name}\timage=${image_ref}\tstatus=${status}"
  if [[ "$status" == "running" && "$name" != "/brain-ai-api-1" ]]; then
    echo "refusing to remove unexpected running legacy container: $name ($cid)" >&2
    exit 1
  fi
done
for image_id in "${legacy_images[@]}"; do
  [[ -n "$image_id" ]] || continue
  size="$(docker image inspect -f '{{.Size}}' "$image_id")"
  echo -e "LEGACY_IMAGE\t${image_id}\tbytes=${size}"
done
echo "LEGACY_DEPROVISION_PLAN mode=$MODE containers=${#legacy_containers[@]} images=${#legacy_images[@]} volumes=preserved"

if [[ "$MODE" == "--dry-run" ]]; then
  exit 0
fi
[[ "${LEGACY_DEPROVISION_AUTHORIZED:-}" == "true" ]] || { echo "authorization marker missing" >&2; exit 2; }
for cid in "${legacy_containers[@]}"; do
  [[ -n "$cid" ]] || continue
  name="$(docker inspect -f '{{.Name}}' "$cid")"
  status="$(docker inspect -f '{{.State.Status}}' "$cid")"
  if [[ "$status" == "running" ]]; then
    [[ "$name" == "/brain-ai-api-1" ]] || { echo "running-container safety check changed: $name" >&2; exit 1; }
    docker stop --time 30 "$cid"
  fi
  docker rm "$cid"
done
for image_id in "${legacy_images[@]}"; do
  [[ -n "$image_id" ]] && docker image rm "$image_id"
done
used="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
(( used < 40 )) || { echo "disk gate failed after legacy retirement: ${used}%" >&2; exit 1; }
echo "LEGACY_DEPROVISION_RESULT=passed disk_usage=${used}% volumes=preserved"
