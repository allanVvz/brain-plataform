#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SHA="${1:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Expected a full Git SHA" >&2; exit 2; }
OUT_DIR="${RELEASE_OUT_DIR:-$ROOT_DIR/.release}"
STAGE="$OUT_DIR/stage-$SOURCE_SHA"
ARCHIVE="$OUT_DIR/brain-release-$SOURCE_SHA.tar.gz"
mkdir -p "$OUT_DIR"
rm -rf -- "$STAGE"
mkdir -p "$STAGE/infra" "$STAGE/api" "$STAGE/supabase" "$STAGE/docs"

cp "$ROOT_DIR/docker-compose.yml" "$STAGE/"
cp "$ROOT_DIR/infra/Caddyfile" "$ROOT_DIR/infra/kong.yml" "$STAGE/infra/"
cp -a "$ROOT_DIR/infra/grafana" "$STAGE/infra/"
cp -a "$ROOT_DIR/ops/vps" "$STAGE/ops"
cp -a "$ROOT_DIR/api/n8n-workflows" "$STAGE/api/"
cp -a "$ROOT_DIR/supabase/migrations" "$STAGE/supabase/"
cp -a "$ROOT_DIR/docs/sdr" "$STAGE/docs/"
printf '%s\n' "$SOURCE_SHA" > "$STAGE/SOURCE_SHA"
printf '%s\n' "${API_IMAGE_DIGEST:-unresolved}" > "$STAGE/API_IMAGE_DIGEST"
printf '%s\n' "${WORKER_IMAGE_DIGEST:-unresolved}" > "$STAGE/WORKER_IMAGE_DIGEST"
printf '%s\n' "${MIGRATE_IMAGE_DIGEST:-unresolved}" > "$STAGE/MIGRATE_IMAGE_DIGEST"
printf '%s\n' "${RUNTIME_BASE_IMAGE_DIGEST:-unresolved}" > "$STAGE/RUNTIME_BASE_IMAGE_DIGEST"
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -C "$STAGE" -czf "$ARCHIVE" .
(cd "$OUT_DIR" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
rm -rf -- "$STAGE"
printf '%s\n' "$ARCHIVE"
