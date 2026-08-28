#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
CHECKPOINT_ROOT="${CHECKPOINT_ROOT:-/var/backups/brain-ai/release-checkpoints}"
LABEL="${1:-release}"
[[ "$LABEL" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$ ]] || exit 2
mkdir -p "$CHECKPOINT_ROOT"
CHECKPOINT_ROOT="$(realpath "$CHECKPOINT_ROOT")"
case "$CHECKPOINT_ROOT" in /|/var|/var/backups|/var/backups/brain-ai) exit 2 ;; esac
DEST="$CHECKPOINT_ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"
mkdir -m 0700 "$DEST"
COMPOSE=(docker compose --env-file "$ENV_FILE")
COMPOSE_BG=(docker compose --env-file "$ENV_FILE" --profile blue-green)
active_api_service="$(tr -d '\r\n' < .deploy/api-active-slot 2>/dev/null || true)"
[[ "$active_api_service" == "api-candidate" ]] || active_api_service=api
cd "$ROOT_DIR"

cp .deploy/release-source-sha "$DEST/source-sha.txt"
cp .deploy/release-directory "$DEST/release-directory.txt"
"${COMPOSE[@]}" config --images | sort -u > "$DEST/configured-images.txt"
for service in "$active_api_service" workers migrate; do
  cid="$("${COMPOSE_BG[@]}" ps -q "$service")"
  [[ -n "$cid" ]] || continue
  docker inspect --format '{{.Config.Image}} {{.Image}}' "$cid" >> "$DEST/running-image-digests.txt"
done
find supabase/migrations -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum > "$DEST/migration-checksums.txt"
find api/n8n-workflows -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum > "$DEST/workflow-checksums.txt"
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from lead_buffer where status in ('\''processing'\'', '\''awaiting_proof'\'');"' > "$DEST/critical-queue-count.txt"
find "$DEST" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$DEST/SHA256SUMS"
(cd "$DEST" && sha256sum --check SHA256SUMS)
echo "Release checkpoint complete: $DEST"
