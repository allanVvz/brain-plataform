#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCHIVE="${1:?usage: install-release-artifact.sh <archive> <git-sha>}"
EXPECTED_SHA="${2:?usage: install-release-artifact.sh <archive> <git-sha>}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Expected a full Git SHA" >&2; exit 2; }
[[ -f "$ARCHIVE" && -f "$ARCHIVE.sha256" ]] || { echo "Release artifact or checksum missing" >&2; exit 2; }
(cd "$(dirname "$ARCHIVE")" && sha256sum --check "$(basename "$ARCHIVE").sha256")
if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Unsafe path in release artifact" >&2
  exit 2
fi
DEST="$ROOT_DIR/.releases/$EXPECTED_SHA"
mkdir -p "$DEST"
tar -C "$DEST" -xzf "$ARCHIVE"
(cd "$DEST" && sha256sum --check SHA256SUMS)
[[ "$(tr -d '\r\n' < "$DEST/SOURCE_SHA")" == "$EXPECTED_SHA" ]] || {
  echo "Release artifact SHA mismatch" >&2
  exit 2
}

cp "$DEST/docker-compose.yml" "$ROOT_DIR/docker-compose.yml"
cp "$DEST/infra/Caddyfile" "$ROOT_DIR/infra/Caddyfile"
cp "$DEST/infra/kong.yml" "$ROOT_DIR/infra/kong.yml"
cp -a "$DEST/infra/grafana/." "$ROOT_DIR/infra/grafana/"
cp -a "$DEST/ops/." "$ROOT_DIR/ops/vps/"
mkdir -p "$ROOT_DIR/api/n8n-workflows"
cp -a "$DEST/api/n8n-workflows/." "$ROOT_DIR/api/n8n-workflows/"
mkdir -p "$ROOT_DIR/.deploy"
printf '%s\n' "$EXPECTED_SHA" > "$ROOT_DIR/.deploy/release-source-sha"
printf '%s\n' "$DEST" > "$ROOT_DIR/.deploy/release-directory"
