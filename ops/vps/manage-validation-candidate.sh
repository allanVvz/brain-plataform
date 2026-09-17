#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
ACTION="${1:?action required}"
PERSONA_SLUG="${2:?persona slug required}"
CANDIDATE_ID="${3:-}"
WORKFLOW_ID="${4:-}"

[[ "$ACTION" == "deprovision" ]] || { echo "n8n conversation candidate provisioning is retired" >&2; exit 2; }
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
