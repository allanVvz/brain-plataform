#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
MODE="${1:?usage: complete-production-validation.sh record-validator <session-id>}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")

psql_scalar() {
  printf '%s\n' "$1" | "${COMPOSE[@]}" exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq'
}

case "$MODE" in
  record-validator)
    SESSION_ID="${2:?validator session id required}"
    [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]{8,160}$ ]] || { echo "invalid validator session id" >&2; exit 2; }
    result="$(psql_scalar "
select concat_ws('|',data->>'status',data->'output'->>'technical_pass',
  data->'output'->>'quality_pass',coalesce(data->'output'->>'quality_scope',''))
from public.wa_validator_sessions where id='$SESSION_ID';")"
    [[ "$result" == "done|true|true|semantic_graph_v1" ]] || {
      echo "WA Validator semantic evidence did not pass: ${result:-missing}" >&2
      exit 1
    }
    critical="$(psql_scalar "select count(*) from public.lead_buffer where status in ('processing','awaiting_proof');")"
    [[ "$critical" == "0" ]] || { echo "critical queue is not drained" >&2; exit 1; }
    python3 ops/vps/release_lifecycle.py record-gate \
      --gate "wa_validator_session=$SESSION_ID" \
      --gate wa_validator_semantic_pass=true \
      --gate outbound_real=forbidden_direct_mode >/dev/null
    echo "optional validator evidence recorded; release lifecycle unchanged"
    ;;
  *) echo "unknown validation mode: $MODE" >&2; exit 2 ;;
esac
