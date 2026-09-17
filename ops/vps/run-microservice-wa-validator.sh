#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:---dry-run}"
PERSONA_SLUG="${2:?persona slug required}"
FLOW_ID="${3:?flow id required}"
INITIAL_STATE="${4:-cold}"
SESSION_ID="${5:-}"
CANDIDATE_WEBHOOK_URL="${6:-}"
STATE_FILE="$ROOT_DIR/.deploy/microservices/slots.json"
MANIFEST="$ROOT_DIR/ops/microservices/release-manifest.json"

[[ "$MODE" == "--dry-run" || "$MODE" == "--run" || "$MODE" == "--run-source" || "$MODE" == "--inspect" ]] || { echo "invalid mode" >&2; exit 2; }
[[ "$PERSONA_SLUG" =~ ^(aurora|tock-fatal|vz-lupas)$ ]] || { echo "invalid persona slug" >&2; exit 2; }
[[ "$FLOW_ID" =~ ^[a-z0-9_]{2,100}$ ]] || { echo "invalid flow id" >&2; exit 2; }
[[ "$INITIAL_STATE" == "cold" || "$INITIAL_STATE" == "known_name" ]] || { echo "invalid initial state" >&2; exit 2; }
if [[ "$MODE" == "--inspect" ]]; then
  [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]{8,160}$ ]] || { echo "valid session id required for inspect" >&2; exit 2; }
fi

cd "$ROOT_DIR"
[[ -s "$STATE_FILE" ]] || { echo "microservice slot state missing" >&2; exit 1; }
[[ -s "$MANIFEST" ]] || { echo "microservice release manifest missing" >&2; exit 1; }
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
validator_service="runtime-validator-${slot}"

manifest_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(data[sys.argv[2]] if sys.argv[2] != "service" else data["services"][sys.argv[3]][sys.argv[4]])' "$MANIFEST" "$@"
}
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
export GATEWAY_ENV_FILE="$ROOT_DIR/.env.microservices/gateway.env"
export CONTROL_PLANE_ENV_FILE="$ROOT_DIR/.env.microservices/control-plane.env"
export RUNTIME_ENV_FILE="$ROOT_DIR/.env.microservices/runtime.env"
export TRANSPORT_ENV_FILE="$ROOT_DIR/.env.microservices/transport.env"
COMPOSE=(docker compose --env-file "$ROOT_DIR/.env.compose" -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/infra/microservices/docker-compose.blue-green.yml")

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

if [[ "$MODE" == "--inspect" ]]; then
  docker exec -i "$runtime_name" python - "$SESSION_ID" <<'PY'
import json
import sys
from services import wa_validator_service as validator

session = validator.get_session(sys.argv[1])
output = session.get("output") or {}
conversation = output.get("conversation") or []
keep = (
    "role", "text", "intent", "route", "handoff", "message_id",
    "pipeline_contract", "graph_version", "graph_checksum", "journey_state",
    "turn_audit", "semantic_audit", "failure_diagnostic",
)
turns = [{key: turn.get(key) for key in keep if key in turn} for turn in conversation]
bot_turns = [turn for turn in conversation if turn.get("role") == "bot" and turn.get("turn_audit")]
audits = [turn.get("turn_audit") or {} for turn in bot_turns]
semantic_audits = [turn.get("semantic_audit") or {} for turn in bot_turns]
summary = {
    "bot_turn_count": len(bot_turns),
    "graph_versions": sorted({turn.get("graph_version") for turn in bot_turns if turn.get("graph_version") is not None}),
    "graph_checksums": sorted({turn.get("graph_checksum") for turn in bot_turns if turn.get("graph_checksum")}),
    "decision_counts": [audit.get("decision_count") for audit in audits],
    "proof_counts": [audit.get("proof_count") for audit in audits],
    "valid_proof_counts": [audit.get("valid_proof_count") for audit in audits],
    "commit_states": [audit.get("commit_state") for audit in audits],
    "outbound_counts": [audit.get("outbound_count") for audit in audits],
    "model_calls": [audit.get("model_calls") for audit in audits],
    "repair_calls": [audit.get("repair_calls") for audit in audits],
    "semantic_passes": [audit.get("passed") for audit in semantic_audits],
    "qualification_complete_turns": sum(audit.get("qualification_complete") is True for audit in semantic_audits),
    "handoff_turns": sum(turn.get("handoff") is True for turn in bot_turns),
}
summary["turn_invariants_pass"] = bool(bot_turns) and all(
    audit.get("decision_count") == 1
    and audit.get("proof_count") == 1
    and audit.get("valid_proof_count") == 1
    and audit.get("commit_state") == "completed"
    and int(audit.get("outbound_count") or 0) <= 1
    and audit.get("model_calls") == 2
    and audit.get("repair_calls") == 0
    for audit in audits
)
result = {
    "id": session.get("id"),
    "persona_slug": session.get("persona_slug"),
    "publication_id": session.get("publication_id"),
    "status": session.get("status"),
    "error": session.get("error"),
    "technical_pass": output.get("technical_pass", session.get("technical_pass")),
    "quality_pass": output.get("quality_pass", session.get("quality_pass")),
    "quality_scope": output.get("quality_scope", session.get("quality_scope")),
    "turns": turns,
}
print("WA_VALIDATOR_AUDIT=" + json.dumps(summary, ensure_ascii=True, sort_keys=True))
print("WA_VALIDATOR_INSPECTION=" + json.dumps(result, ensure_ascii=True, sort_keys=True))
PY
  echo "WA_VALIDATOR_INSPECT_RESULT=passed"
  exit 0
fi

runner_cid="$(docker ps -aq --filter label=com.docker.compose.project=brain-ai --filter label=com.docker.compose.service=wa-validator | head -n 1)"
[[ -n "$runner_cid" ]] || { echo "WA Validator runner container does not exist" >&2; exit 1; }
runner_name="$(docker inspect -f '{{.Name}}' "$runner_cid" | sed 's#^/##')"
runner_was_running="$(docker inspect -f '{{.State.Running}}' "$runner_cid")"
echo "PASS validator_runner_exists=true runtime=$runtime_name worker=$validator_name"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "WA_VALIDATOR_DRY_RUN=passed"
  exit 0
fi

validator_cid="$(docker ps -aq --filter "name=^/${validator_name}$" | head -n 1)"
validator_was_running=false
source_validator_created=false
if [[ -n "$validator_cid" ]]; then
  validator_was_running="$(docker inspect -f '{{.State.Running}}' "$validator_cid")"
fi
cleanup() {
  local status="$?"
  if [[ "$MODE" == "--run-source" && "$source_validator_created" == "true" ]]; then
    docker rm -f "$validator_name" >/dev/null 2>&1 || true
  elif [[ "$validator_was_running" != "true" ]]; then
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

if [[ "$MODE" == "--run-source" ]]; then
  [[ "$validator_was_running" != "true" ]] || { echo "source validator requires an idle validator worker" >&2; exit 1; }
  source_service="$ROOT_DIR/apps/conversation-runtime/api/services/wa_validator_service.py"
  source_profile="$ROOT_DIR/apps/conversation-runtime/api/evaluation/wa_validator_customer_profiles.json"
  [[ -s "$source_service" && -s "$source_profile" ]] || { echo "source validator files missing" >&2; exit 1; }
  "${COMPOSE[@]}" create --no-build "$validator_service" >/dev/null
  source_validator_created=true
  docker cp "$source_service" "$validator_name:/app/services/wa_validator_service.py"
  docker cp "$source_profile" "$validator_name:/app/evaluation/wa_validator_customer_profiles.json"
  docker start "$validator_name" >/dev/null
elif [[ "$validator_was_running" != "true" ]]; then
  "${COMPOSE[@]}" up -d --no-deps "$validator_service" >/dev/null
fi
[[ "$(docker inspect -f '{{.State.Running}}' "$validator_name")" == "true" ]] || { echo "validator worker failed to start" >&2; exit 1; }

session_container="$runtime_name"
[[ "$MODE" == "--run-source" ]] && session_container="$validator_name"
session_output="$(docker exec "$session_container" python -c 'import sys; from services import wa_validator_service as w; generated=w.generate_script(persona_slug=sys.argv[1], flow_id=sys.argv[2], target_contact="production-lifecycle", initial_state=sys.argv[3]); session_id=generated["session_id"]; w.enqueue_session_direct(session_id); print("WA_VALIDATOR_SESSION_ID=" + session_id)' "$PERSONA_SLUG" "$FLOW_ID" "$INITIAL_STATE")"
printf '%s\n' "$session_output"
session_id="$(printf '%s\n' "$session_output" | sed -n 's/^WA_VALIDATOR_SESSION_ID=//p' | tail -n 1)"
[[ "$session_id" =~ ^[A-Za-z0-9_-]{8,160}$ ]] || { echo "invalid validator session id" >&2; exit 1; }

deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
  summary="$(docker exec "$session_container" python -c 'import json,sys; from services import wa_validator_service as w; s=w.get_session(sys.argv[1]); o=s.get("output") or {}; print(json.dumps({"status":s.get("status"),"technical_pass":o.get("technical_pass",s.get("technical_pass")),"quality_pass":o.get("quality_pass",s.get("quality_pass")),"quality_scope":o.get("quality_scope",s.get("quality_scope")),"turn_count":len(o.get("conversation") or []),"error":s.get("error")}, ensure_ascii=True, sort_keys=True))' "$session_id")"
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
