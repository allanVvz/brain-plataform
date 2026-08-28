#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-180}"
DRAIN_POLL_SECONDS="${DRAIN_POLL_SECONDS:-2}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")

python3 ops/vps/release_lifecycle.py assert --stage claims_paused >/dev/null
[[ -s .deploy/control/claims-paused.json ]] || {
  echo "claims pause marker is missing" >&2
  exit 1
}

psql_scalar() {
  printf '%s\n' "$1" | "${COMPOSE[@]}" exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}

deadline=$((SECONDS + DRAIN_TIMEOUT_SECONDS))
while true; do
  critical="$(psql_scalar \
    "select count(*) from public.lead_buffer where status in ('processing','awaiting_proof');")"
  [[ "$critical" =~ ^[0-9]+$ ]] || {
    echo "invalid critical queue count: $critical" >&2
    exit 1
  }
  if (( critical == 0 )); then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "queue drain timed out with $critical processing/awaiting_proof rows" >&2
    exit 1
  fi
  sleep "$DRAIN_POLL_SECONDS"
done

pending="$(psql_scalar \
  "select count(*) from public.lead_buffer where direction='inbound' and status in ('received','buffered','retry') and payload->'conversation_commit' is null;")"
[[ "$pending" =~ ^[0-9]+$ ]] || {
  echo "invalid pending queue count: $pending" >&2
  exit 1
}
python3 ops/vps/release_lifecycle.py advance \
  --stage queue_drained \
  --pending-messages "$pending" \
  --gate "critical_buffer_rows=$critical" \
  --gate "eligible_inbound_rows=$pending" >/dev/null
printf 'queue_drained\tcritical=%s\tpending=%s\n' "$critical" "$pending"

