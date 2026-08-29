#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:---dry-run}"
PERSONA_SLUG="${2:?persona slug required}"
FLOW_ID="${3:?flow id required}"
INITIAL_STATE="${4:-cold}"
STATE_FILE="$ROOT_DIR/.deploy/microservices/slots.json"

[[ "$MODE" == "--dry-run" || "$MODE" == "--run" ]] || { echo "invalid mode" >&2; exit 2; }
[[ "$PERSONA_SLUG" =~ ^(aurora|tock-fatal)$ ]] || { echo "invalid persona slug" >&2; exit 2; }
[[ "$FLOW_ID" =~ ^[a-z0-9_]{2,100}$ ]] || { echo "invalid flow id" >&2; exit 2; }
[[ "$INITIAL_STATE" == "cold" || "$INITIAL_STATE" == "known_name" ]] || { echo "invalid initial state" >&2; exit 2; }

cd "$ROOT_DIR"
[[ -s "$STATE_FILE" ]] || { echo "microservice slot state missing" >&2; exit 1; }
python3 - "$STATE_FILE" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
for service in ("gateway", "control-plane", "conversation-runtime", "transport"):
    slot = (state.get(service) or {}).get("active")
    if slot not in {"blue", "green"}:
        raise SystemExit(f"{service} has no active microservice slot")
PY

slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["conversation-runtime"]["active"])' "$STATE_FILE")"
runtime_name="brain-ai-runtime-${slot}-1"
validator_name="brain-ai-runtime-validator-${slot}-1"

for service in gateway control-plane conversation-runtime transport; do
  service_slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]["active"])' "$STATE_FILE" "$service")"
  compose_name="${service/conversation-runtime/runtime}"
  name="brain-ai-${compose_name}-${service_slot}-1"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name")"
  [[ "$health" == "healthy" ]] || { echo "$name is not healthy: $health" >&2; exit 1; }
  echo "PASS service=$service slot=$service_slot health=$health"
done

python3 - <<'PY'
import json
from pathlib import Path
pause = Path(".deploy/control/claims-paused.json")
if pause.exists():
    value = json.loads(pause.read_text(encoding="utf-8"))
    assert value.get("paused") is True, "invalid global pause marker"
    print("PASS validator_operational_state=claims_paused")
else:
    state = json.loads(Path(".deploy/microservices/resume-state.json").read_text(encoding="utf-8"))
    assert state.get("status") == "workers_resumed", "neither claims pause nor verified resume state exists"
    assert state.get("legacy_worker") == "stopped", "legacy worker resume is forbidden"
    print("PASS validator_operational_state=workers_resumed")
PY

runner_cid="$(docker ps -aq --filter label=com.docker.compose.project=brain-ai --filter label=com.docker.compose.service=wa-validator | head -n 1)"
[[ -n "$runner_cid" ]] || { echo "WA Validator runner container does not exist" >&2; exit 1; }
runner_name="$(docker inspect -f '{{.Name}}' "$runner_cid" | sed 's#^/##')"
runner_was_running="$(docker inspect -f '{{.State.Running}}' "$runner_cid")"
echo "PASS validator_runner_exists=true runtime=$runtime_name worker=$validator_name"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "WA_VALIDATOR_DRY_RUN=passed"
  exit 0
fi

validator_was_running="$(docker inspect -f '{{.State.Running}}' "$validator_name")"
cleanup() {
  local status="$?"
  if [[ "$validator_was_running" != "true" ]]; then
    docker stop -t 120 "$validator_name" >/dev/null || true
  fi
  if [[ "$runner_was_running" != "true" ]]; then
    docker stop -t 120 "$runner_cid" >/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ "$runner_was_running" != "true" ]]; then
  docker start "$runner_cid" >/dev/null
fi
runner_deadline=$((SECONDS + 120))
until [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$runner_cid")" == "healthy" ]]; do
  (( SECONDS < runner_deadline )) || { echo "$runner_name did not become healthy" >&2; exit 1; }
  sleep 3
done

if [[ "$validator_was_running" != "true" ]]; then
  docker start "$validator_name" >/dev/null
fi
[[ "$(docker inspect -f '{{.State.Running}}' "$validator_name")" == "true" ]] || { echo "validator worker failed to start" >&2; exit 1; }

session_output="$(docker exec "$runtime_name" python -c 'import sys; from services import wa_validator_service as w; generated=w.generate_script(persona_slug=sys.argv[1], flow_id=sys.argv[2], target_contact="production-lifecycle", initial_state=sys.argv[3]); session_id=generated["session_id"]; w.enqueue_session_direct(session_id); print("WA_VALIDATOR_SESSION_ID=" + session_id)' "$PERSONA_SLUG" "$FLOW_ID" "$INITIAL_STATE")"
printf '%s\n' "$session_output"
session_id="$(printf '%s\n' "$session_output" | sed -n 's/^WA_VALIDATOR_SESSION_ID=//p' | tail -n 1)"
[[ "$session_id" =~ ^[A-Za-z0-9_-]{8,160}$ ]] || { echo "invalid validator session id" >&2; exit 1; }

deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
  summary="$(docker exec "$runtime_name" python -c 'import json,sys; from services import wa_validator_service as w; s=w.get_session(sys.argv[1]); print(json.dumps({"status":s.get("status"),"technical_pass":s.get("technical_pass"),"quality_pass":s.get("quality_pass"),"quality_scope":s.get("quality_scope"),"turn_count":len(((s.get("output") or {}).get("conversation") or [])),"error":s.get("error")}, ensure_ascii=True, sort_keys=True))' "$session_id")"
  printf 'WA_VALIDATOR_STATUS=%s\n' "$summary"
  status="$(printf '%s' "$summary" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status") or "")')"
  if [[ "$status" == "done" ]]; then
    printf '%s' "$summary" | python3 -c 'import json,sys; v=json.load(sys.stdin); raise SystemExit(0 if v.get("technical_pass") is True and v.get("quality_pass") is True and v.get("quality_scope")=="semantic_graph_v1" else 1)'
    echo "WA_VALIDATOR_RESULT=passed"
    exit 0
  fi
  [[ "$status" != "error" && "$status" != "failed" ]] || { echo "WA Validator failed: $summary" >&2; exit 1; }
  sleep 5
done
echo "WA Validator timed out: $session_id" >&2
exit 1
