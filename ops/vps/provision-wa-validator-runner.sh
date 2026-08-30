#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
MODE="${1:---dry-run}"
DIGEST="${2:?WA Validator image digest required}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-40}"
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" || "$MODE" == "--deprovision" ]] || { echo "invalid mode" >&2; exit 2; }
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "invalid digest" >&2; exit 2; }

cd "$ROOT_DIR"
disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [[ "$MODE" != "--deprovision" ]]; then
  [[ "$disk_used" =~ ^[0-9]+$ ]] && (( disk_used < DISK_MAX_PERCENT )) || {
    echo "disk gate failed: ${disk_used:-unknown}% required <${DISK_MAX_PERCENT}%" >&2
    exit 1
  }
fi

python3 - .deploy/microservices/slots.json <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
for service in ("gateway", "control-plane", "conversation-runtime", "transport"):
    if (state.get(service) or {}).get("active") not in {"blue", "green"}:
        raise SystemExit(f"{service} has no active slot")
PY

for service in gateway control-plane conversation-runtime transport; do
  slot="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]["active"])' .deploy/microservices/slots.json "$service")"
  compose_name="${service/conversation-runtime/runtime}"
  health="$(docker inspect -f '{{.State.Health.Status}}' "brain-ai-${compose_name}-${slot}-1")"
  [[ "$health" == healthy ]] || { echo "$service is not healthy" >&2; exit 1; }
done

export WA_VALIDATOR_IMAGE="ghcr.io/allanvvz/brain-wa-validator@$DIGEST"
COMPOSE=(docker compose --env-file "$ROOT_DIR/.env.compose" -f "$ROOT_DIR/docker-compose.yml")
"${COMPOSE[@]}" --profile wa-validator config --quiet

if [[ "$MODE" == "--deprovision" ]]; then
  marker="$(tr -d '\r\n' < .deploy/microservices/wa-validator-digest 2>/dev/null || true)"
  [[ "$marker" == "$DIGEST" ]] || {
    echo "WA Validator digest marker mismatch: ${marker:-missing}" >&2
    exit 1
  }
  cid="$("${COMPOSE[@]}" --profile wa-validator ps -aq wa-validator)"
  if [[ -n "$cid" ]]; then
    configured_image="$(docker inspect -f '{{.Config.Image}}' "$cid")"
    [[ "$configured_image" == "$WA_VALIDATOR_IMAGE" ]] || {
      echo "Refusing unexpected WA Validator image: $configured_image" >&2
      exit 1
    }
    "${COMPOSE[@]}" --profile wa-validator stop -t 120 wa-validator
    "${COMPOSE[@]}" --profile wa-validator rm -f wa-validator
  fi
  if docker image inspect "$WA_VALIDATOR_IMAGE" >/dev/null 2>&1; then
    docker image rm "$WA_VALIDATOR_IMAGE"
  fi
  stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'status=deprovisioned\ndigest=%s\nat=%s\n' "$DIGEST" "$stamp" \
    > .deploy/microservices/wa-validator-state
  chmod 0600 .deploy/microservices/wa-validator-state
  disk_after="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
  echo "WA_VALIDATOR_DEPROVISIONED=passed digest=$DIGEST disk_before=${disk_used}% disk_after=${disk_after}% volumes=preserved"
  exit 0
fi

echo "WA_VALIDATOR_PROVISION_PREFLIGHT=passed disk=${disk_used}% digest=$DIGEST"
if [[ "$MODE" == "--dry-run" ]]; then
  exit 0
fi

"${COMPOSE[@]}" --profile wa-validator pull wa-validator
"${COMPOSE[@]}" --profile wa-validator up -d --no-deps wa-validator
cid="$("${COMPOSE[@]}" --profile wa-validator ps -q wa-validator)"
[[ -n "$cid" ]] || { echo "WA Validator runner container missing after apply" >&2; exit 1; }
deadline=$((SECONDS + 180))
until [[ "$(docker inspect -f '{{.State.Health.Status}}' "$cid")" == healthy ]]; do
  (( SECONDS < deadline )) || { echo "WA Validator runner readiness timeout" >&2; exit 1; }
  sleep 3
done
mkdir -p .deploy/microservices
printf '%s\n' "$DIGEST" > .deploy/microservices/wa-validator-digest
chmod 0600 .deploy/microservices/wa-validator-digest
printf 'status=provisioned\ndigest=%s\nat=%s\n' "$DIGEST" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > .deploy/microservices/wa-validator-state
chmod 0600 .deploy/microservices/wa-validator-state
echo "WA_VALIDATOR_PROVISIONED=passed digest=$DIGEST health=healthy exposure=internal"
