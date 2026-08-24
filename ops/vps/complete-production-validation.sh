#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
MODE="${1:?usage: complete-production-validation.sh record-validator <session-id> | complete-soak}"
SOAK_MIN_SECONDS="${SOAK_MIN_SECONDS:-1800}"
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
    lifecycle_stage="$(python3 ops/vps/release_lifecycle.py show --field stage)"
    if [[ "$lifecycle_stage" == "validator_complete" ]]; then
      recorded="$(python3 ops/vps/release_lifecycle.py show --field gates.wa_validator_session 2>/dev/null || true)"
      [[ "$recorded" == "$SESSION_ID" ]] || { echo "another validator session is already recorded" >&2; exit 1; }
      echo "validator evidence already recorded; soak continues"
      exit 0
    fi
    python3 ops/vps/release_lifecycle.py assert --stage candidate_healthy >/dev/null
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
    python3 ops/vps/release_lifecycle.py advance --stage validator_complete \
      --gate "wa_validator_session=$SESSION_ID" \
      --gate wa_validator_semantic_pass=true \
      --gate outbound_real=forbidden_direct_mode >/dev/null
    echo "validator evidence recorded; durable soak window started"
    ;;
  complete-soak)
    lifecycle_stage="$(python3 ops/vps/release_lifecycle.py show --field stage)"
    if [[ "$lifecycle_stage" == "awaiting_resume_authorization" ]]; then
      echo "soak was already completed; release awaits resume authorization"
      exit 0
    fi
    python3 ops/vps/release_lifecycle.py assert --stage validator_complete >/dev/null
    entered="$(python3 ops/vps/release_lifecycle.py show --field stage_entered_at)"
    age="$(python3 - "$entered" <<'PY'
import datetime as dt, sys
stamp=dt.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00'))
print(max(0,int((dt.datetime.now(dt.timezone.utc)-stamp).total_seconds())))
PY
)"
    (( age >= SOAK_MIN_SECONDS )) || {
      echo "soak incomplete: age=${age}s required=${SOAK_MIN_SECONDS}s" >&2
      exit 1
    }
    target="$(python3 ops/vps/release_lifecycle.py show --field candidate_sha)"
    EXPECTED_RELEASE_SHA="$target" bash ops/vps/validate-production-release.sh >/dev/null
    python3 ops/vps/release_lifecycle.py advance --stage soak_complete \
      --gate "soak_seconds=$age" >/dev/null
    python3 ops/vps/release_lifecycle.py advance \
      --stage awaiting_resume_authorization >/dev/null
    echo "soak complete; release awaits explicit resume authorization"
    ;;
  *) echo "unknown validation mode: $MODE" >&2; exit 2 ;;
esac
