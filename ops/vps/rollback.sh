#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$ROOT_DIR/.deploy"
TAG="${1:-}"
if [[ -z "$TAG" && -f "$STATE_DIR/previous-tag" ]]; then
  TAG="$(tr -d '\r\n' < "$STATE_DIR/previous-tag")"
fi
[[ -n "$TAG" ]] || { echo "No rollback tag supplied or recorded." >&2; exit 1; }
if [[ -s "$STATE_DIR/previous-components.env" \
      && -s "$STATE_DIR/previous-tag" \
      && "$TAG" == "$(tr -d '\r\n' < "$STATE_DIR/previous-tag")" ]]; then
  ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
  CURRENT_TAG="$(tr -d '\r\n' < "$STATE_DIR/current-tag")"
  [[ "$CURRENT_TAG" =~ ^[0-9a-f]{40}$ && "$TAG" =~ ^[0-9a-f]{40}$ ]] || exit 2
  current_components_temp="$(mktemp "$STATE_DIR/.rollback-current-components.XXXXXX")"
  cp "$STATE_DIR/components.env" "$current_components_temp"
  API_TAG=""; WORKER_TAG=""; MIGRATE_TAG=""
  while IFS='=' read -r key value; do
    [[ "$value" =~ ^[0-9a-f]{40}$ ]] || continue
    case "$key" in API_TAG) API_TAG="$value" ;; WORKER_TAG) WORKER_TAG="$value" ;; MIGRATE_TAG) MIGRATE_TAG="$value" ;; esac
  done < "$STATE_DIR/previous-components.env"
  [[ -n "$API_TAG" && -n "$WORKER_TAG" && -n "$MIGRATE_TAG" ]] || exit 2
  export API_TAG WORKER_TAG MIGRATE_TAG IMAGE_TAG="$TAG"
  COMPOSE=(docker compose --env-file "$ENV_FILE")
  python3 "$ROOT_DIR/ops/vps/release_lifecycle.py" prepare \
    --candidate-sha "$TAG" --previous-sha "$CURRENT_TAG" \
    --impact-class conversational --pause-reason "authorized component rollback" --force >/dev/null
  python3 "$ROOT_DIR/ops/vps/release_lifecycle.py" pause-claims \
    --reason "authorized component rollback" >/dev/null
  bash "$ROOT_DIR/ops/vps/drain-worker-claims.sh"
  "${COMPOSE[@]}" pull api workers migrate
  python3 "$ROOT_DIR/ops/vps/release_lifecycle.py" advance --stage migration_complete \
    --gate database_rollback=not_attempted >/dev/null
  bash "$ROOT_DIR/ops/vps/deploy-api-blue-green.sh" "$API_TAG"
  "${COMPOSE[@]}" up -d --no-deps workers
  mv -f "$STATE_DIR/previous-components.env" "$STATE_DIR/components.env"
  mv -f "$current_components_temp" "$STATE_DIR/previous-components.env"
  for component in api worker migrate runtime-base; do
    current_digest="$STATE_DIR/release-${component}-digest"
    previous_digest="$STATE_DIR/previous-release-${component}-digest"
    if [[ -s "$previous_digest" ]]; then
      digest_temp="$(mktemp "$STATE_DIR/.rollback-digest.XXXXXX")"
      cp "$current_digest" "$digest_temp"
      mv -f "$previous_digest" "$current_digest"
      mv -f "$digest_temp" "$previous_digest"
    fi
  done
  printf '%s\n' "$TAG" > "$STATE_DIR/current-tag"
  printf '%s\n' "$CURRENT_TAG" > "$STATE_DIR/previous-tag"
  printf '%s\n' "$TAG" > "$STATE_DIR/release-source-sha"
  if [[ -d "$ROOT_DIR/.releases/$TAG" ]]; then
    printf '%s\n' "$ROOT_DIR/.releases/$TAG" > "$STATE_DIR/release-directory"
  fi
  python3 "$ROOT_DIR/ops/vps/release_lifecycle.py" advance --stage candidate_healthy \
    --gate rollback_components_restored=true >/dev/null
  echo "Component rollback healthy; claims remain paused pending validator, soak and resume authorization."
  exit 0
fi
export ALLOW_LOCAL_IMAGES=true
exec "$ROOT_DIR/ops/vps/deploy.sh" "$TAG"
