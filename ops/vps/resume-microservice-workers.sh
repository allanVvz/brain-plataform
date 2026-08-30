#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:---dry-run}"
ACTOR="${AUTHORIZATION_ACTOR:-unknown}"
REASON="${AUTHORIZATION_REASON:-}"
STATE_FILE="$ROOT_DIR/.deploy/microservices/slots.json"
MANIFEST="${RELEASE_MANIFEST:-$ROOT_DIR/ops/microservices/release-manifest.json}"
CONTROL_DIR="$ROOT_DIR/.deploy/control"
PAUSE_FILE="$CONTROL_DIR/claims-paused.json"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-40}"

[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "invalid mode" >&2; exit 2; }
[[ -n "$REASON" ]] || { echo "authorization reason is required" >&2; exit 2; }
cd "$ROOT_DIR"

manifest_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(data["services"][sys.argv[2]][sys.argv[3]])' "$MANIFEST" "$@"
}
export BRAIN_CONTRACTS_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["contracts_version"])' "$MANIFEST")"
export GATEWAY_SHA="$(manifest_value gateway sha)" GATEWAY_DIGEST="$(manifest_value gateway digest)"
export CONTROL_PLANE_SHA="$(manifest_value control-plane sha)" CONTROL_PLANE_DIGEST="$(manifest_value control-plane digest)"
export RUNTIME_SHA="$(manifest_value conversation-runtime sha)" RUNTIME_DIGEST="$(manifest_value conversation-runtime digest)"
export TRANSPORT_SHA="$(manifest_value transport sha)" TRANSPORT_DIGEST="$(manifest_value transport digest)"
export GATEWAY_IMAGE_BLUE="ghcr.io/allanvvz/brain-gateway@$GATEWAY_DIGEST" GATEWAY_IMAGE_GREEN="ghcr.io/allanvvz/brain-gateway@$GATEWAY_DIGEST"
export CONTROL_PLANE_IMAGE_BLUE="ghcr.io/allanvvz/brain-control-plane@$CONTROL_PLANE_DIGEST" CONTROL_PLANE_IMAGE_GREEN="ghcr.io/allanvvz/brain-control-plane@$CONTROL_PLANE_DIGEST"
export RUNTIME_IMAGE_BLUE="ghcr.io/allanvvz/brain-conversation-runtime@$RUNTIME_DIGEST" RUNTIME_IMAGE_GREEN="ghcr.io/allanvvz/brain-conversation-runtime@$RUNTIME_DIGEST"
export TRANSPORT_IMAGE_BLUE="ghcr.io/allanvvz/brain-transport@$TRANSPORT_DIGEST" TRANSPORT_IMAGE_GREEN="ghcr.io/allanvvz/brain-transport@$TRANSPORT_DIGEST"
export GATEWAY_ENV_FILE="${GATEWAY_ENV_FILE:-$ROOT_DIR/.env.microservices/gateway.env}"
export CONTROL_PLANE_ENV_FILE="${CONTROL_PLANE_ENV_FILE:-$ROOT_DIR/.env.microservices/control-plane.env}"
export RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-$ROOT_DIR/.env.microservices/runtime.env}"
export TRANSPORT_ENV_FILE="${TRANSPORT_ENV_FILE:-$ROOT_DIR/.env.microservices/transport.env}"
COMPOSE=(docker compose --env-file "$ROOT_DIR/.env.compose" -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/infra/microservices/docker-compose.blue-green.yml")

python3 - "$STATE_FILE" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
for service in ("gateway", "control-plane", "conversation-runtime", "transport"):
    if (state.get(service) or {}).get("active") not in {"blue", "green"}:
        raise SystemExit(f"{service} has no active microservice slot")
value = json.load(open(".deploy/control/claims-paused.json", encoding="utf-8"))
assert value.get("paused") is True, "global claims are not paused"
PY

slot_for() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]["active"])' "$STATE_FILE" "$1"
}

gateway_slot="$(slot_for gateway)"
control_slot="$(slot_for control-plane)"
runtime_slot="$(slot_for conversation-runtime)"
transport_slot="$(slot_for transport)"

api_names=(
  "brain-ai-gateway-${gateway_slot}-1"
  "brain-ai-control-plane-${control_slot}-1"
  "brain-ai-runtime-${runtime_slot}-1"
  "brain-ai-transport-${transport_slot}-1"
)
worker_services=(
  "control-plane-knowledge-${control_slot}"
  "control-plane-integrations-${control_slot}"
  "control-plane-validator-${control_slot}"
  "runtime-conversation-${runtime_slot}"
  "runtime-validator-${runtime_slot}"
  "transport-dispatch-${transport_slot}"
  "transport-media-${transport_slot}"
)

for name in "${api_names[@]}"; do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name")"
  [[ "$health" == "healthy" ]] || { echo "$name is not healthy: $health" >&2; exit 1; }
done

"${COMPOSE[@]}" config --quiet
for image in "$CONTROL_PLANE_IMAGE_BLUE" "$RUNTIME_IMAGE_BLUE" "$TRANSPORT_IMAGE_BLUE"; do
  docker image inspect "$image" >/dev/null
done

legacy_worker="$(docker ps -q --filter label=com.docker.compose.project=brain-ai --filter label=com.docker.compose.service=workers | head -n 1)"
[[ -z "$legacy_worker" ]] || { echo "legacy monolith worker is running" >&2; exit 1; }

disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]] && (( disk_used < DISK_MAX_PERCENT )) || {
  echo "disk gate failed: ${disk_used:-unknown}% required <${DISK_MAX_PERCENT}%" >&2
  exit 1
}

db_cid="$(docker ps -q --filter label=com.docker.compose.project=brain-ai --filter label=com.docker.compose.service=db | head -n 1)"
[[ -n "$db_cid" ]] || { echo "database container is not running" >&2; exit 1; }
psql_scalar() {
  printf '%s\n' "$1" | docker exec -i "$db_cid" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}

cas_conflicts="$(psql_scalar "select count(*) from public.system_events where created_at >= now()-interval '15 minutes' and (event_type='conversation_ledger_revision_cas' or payload::text like '%conversation_ledger_revision_cas%');")"
orphan_claims="$(psql_scalar "select count(*) from public.lead_buffer where status in ('processing','awaiting_proof') and coalesce(locked_at,updated_at) < now()-interval '5 minutes';")"
claimable_with_commit="$(psql_scalar "select count(*) from public.lead_buffer where direction='inbound' and status in ('received','buffered','retry') and payload->'conversation_commit' is not null;")"
[[ "$cas_conflicts" == 0 && "$orphan_claims" == 0 && "$claimable_with_commit" == 0 ]] || {
  echo "resume gates failed cas=$cas_conflicts orphan=$orphan_claims claimable_with_commit=$claimable_with_commit" >&2
  exit 1
}

echo "MICROSERVICE_RESUME_PREFLIGHT=passed disk=${disk_used}% workers=${#worker_services[@]} legacy_worker=stopped"
if [[ "$MODE" == "--dry-run" ]]; then
  exit 0
fi

mkdir -p "$CONTROL_DIR" "$ROOT_DIR/.deploy/microservices"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pause_evidence="$CONTROL_DIR/claims-paused.microservice-resume-${stamp}.json"
started=()
released=false
rollback() {
  local status="$?"
  if [[ "$status" != 0 ]]; then
    if (( ${#started[@]} )); then "${COMPOSE[@]}" stop -t 120 "${started[@]}" >/dev/null || true; fi
    if [[ "$released" == true && -f "$pause_evidence" ]]; then
      cp "$pause_evidence" "$PAUSE_FILE"
      chmod 0644 "$PAUSE_FILE"
    fi
    echo "MICROSERVICE_RESUME_ROLLBACK=applied" >&2
  fi
  exit "$status"
}
trap rollback EXIT

python3 - "$ROOT_DIR/.deploy/microservices/resume-authorization.json" "$ACTOR" "$REASON" "$stamp" <<'PY'
import json, os, sys, tempfile
path, actor, reason, stamp = sys.argv[1:]
payload = {"authorized": True, "actor": actor, "reason": reason, "at": stamp}
fd, temp = tempfile.mkstemp(prefix=".resume-authorization.", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
os.chmod(temp, 0o600)
os.replace(temp, path)
PY

mv "$PAUSE_FILE" "$pause_evidence"
released=true
"${COMPOSE[@]}" up -d --no-deps "${worker_services[@]}"
started=("${worker_services[@]}")
for service in "${worker_services[@]}"; do
  cid="$("${COMPOSE[@]}" ps -q "$service")"
  [[ -n "$cid" && "$(docker inspect -f '{{.State.Running}}' "$cid")" == true ]] || { echo "$service failed to remain running" >&2; exit 1; }
done

sleep "${RESUME_OBSERVE_SECONDS:-120}"
cas_after="$(psql_scalar "select count(*) from public.system_events where created_at >= now()-interval '5 minutes' and (event_type='conversation_ledger_revision_cas' or payload::text like '%conversation_ledger_revision_cas%');")"
orphan_after="$(psql_scalar "select count(*) from public.lead_buffer where status in ('processing','awaiting_proof') and coalesce(locked_at,updated_at) < now()-interval '5 minutes';")"
unproved_after="$(psql_scalar "select count(*) from public.lead_buffer b where b.direction='outbound' and b.created_at >= now()-interval '5 minutes' and coalesce(b.payload->>'sender_type','')='agent' and not exists (select 1 from public.conversation_turn_proofs p where p.outbound_id=b.id::text and coalesce((p.proof_result->>'valid')::boolean,false));")"
[[ "$cas_after" == 0 && "$orphan_after" == 0 && "$unproved_after" == 0 ]] || {
  echo "post-resume gates failed cas=$cas_after orphan=$orphan_after unproved=$unproved_after" >&2
  exit 1
}

python3 - "$ROOT_DIR/.deploy/microservices/resume-state.json" "$stamp" "$disk_used" <<'PY'
import json, os, sys, tempfile
path, stamp, disk = sys.argv[1:]
payload = {"status": "workers_resumed", "at": stamp, "disk_percent": int(disk), "legacy_worker": "stopped", "worker_groups": 7}
fd, temp = tempfile.mkstemp(prefix=".resume-state.", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
os.chmod(temp, 0o600)
os.replace(temp, path)
PY

trap - EXIT
echo "MICROSERVICE_WORKERS_RESUMED=passed groups=7 legacy_worker=stopped cas=0 orphan=0 unproved=0"
