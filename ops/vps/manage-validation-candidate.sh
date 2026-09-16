#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
ACTION="${1:?action required}"
PERSONA_SLUG="${2:?persona slug required}"
CANDIDATE_ID="${3:-}"
WORKFLOW_ID="${4:-}"

[[ "$ACTION" == "provision" || "$ACTION" == "deprovision" ]] || { echo "invalid action" >&2; exit 2; }
[[ "$PERSONA_SLUG" =~ ^[a-z0-9-]{2,80}$ ]] || { echo "invalid persona slug" >&2; exit 2; }
[[ -z "$CANDIDATE_ID" || "$CANDIDATE_ID" =~ ^[a-z0-9-]{8,80}$ ]] || { echo "invalid candidate id" >&2; exit 2; }
[[ -z "$WORKFLOW_ID" || "$WORKFLOW_ID" =~ ^[A-Za-z0-9_-]{1,160}$ ]] || { echo "invalid workflow id" >&2; exit 2; }

cd "$ROOT_DIR"
state_file="$ROOT_DIR/.deploy/microservices/slots.json"
[[ -s "$state_file" ]] || { echo "microservice slot state missing" >&2; exit 1; }
slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["control-plane"]["active"])' "$state_file")"
control_name="brain-ai-control-plane-${slot}-1"

if [[ "$ACTION" == "deprovision" ]]; then
  [[ -n "$WORKFLOW_ID" ]] || { echo "workflow id required for deprovision" >&2; exit 2; }
  docker exec "$control_name" python -c 'import sys; from services import n8n_client; workflow_id=sys.argv[1]; n8n_client.deactivate_workflow(workflow_id); print("VALIDATION_CANDIDATE_DEPROVISIONED=" + workflow_id)' "$WORKFLOW_ID"
  exit 0
fi

[[ -n "$CANDIDATE_ID" ]] || { echo "candidate id required for provision" >&2; exit 2; }
docker exec "$control_name" python -c 'import json,sys; from scripts import resync_graph_agent_workflows as r; from services import conversation_workflow_service as w, supabase_client; slug,candidate_id=sys.argv[1:]; persona=supabase_client.get_persona(slug); assert persona, "persona not found"; binding=r._binding(persona, require_active=False); connection=supabase_client.get_persona_integration_connection(str(persona["id"]), "deepseek") or {}; config=r._resolved_config(persona, connection, binding); result=w.provision_validation_candidate(persona, config, candidate_id=candidate_id); metadata=binding.get("metadata") or {}; live=str(metadata.get("conversation_webhook_url") or metadata.get("webhook_url") or "").rstrip("/"); assert "/webhook/" in live, "active binding has no n8n production webhook URL"; candidate_url=live.split("/webhook/",1)[0] + "/webhook/" + result["webhook_path"]; print("VALIDATION_CANDIDATE=" + json.dumps({**result, "candidate_webhook_url":candidate_url}, ensure_ascii=True, sort_keys=True))' "$PERSONA_SLUG" "$CANDIDATE_ID"
