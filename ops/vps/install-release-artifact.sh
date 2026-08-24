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
mkdir -p "$ROOT_DIR/.deploy/caddy"
active_api_slot="$(tr -d '\r\n' < "$ROOT_DIR/.deploy/api-active-slot" 2>/dev/null || true)"
caddy_temp="$(mktemp "$ROOT_DIR/.deploy/caddy/.Caddyfile.XXXXXX")"
if [[ "$active_api_slot" == "api-candidate" ]]; then
  sed 's/reverse_proxy api:8080/reverse_proxy api-candidate:8080/g' \
    "$DEST/infra/Caddyfile" > "$caddy_temp"
else
  cp "$DEST/infra/Caddyfile" "$caddy_temp"
fi
chmod 0644 "$caddy_temp"
mv -f "$caddy_temp" "$ROOT_DIR/.deploy/caddy/Caddyfile"
printf '%s\n' "$EXPECTED_SHA" > "$ROOT_DIR/.deploy/release-source-sha"
printf '%s\n' "$DEST" > "$ROOT_DIR/.deploy/release-directory"
install_resolved_digest() {
  local source="$1" target="$2" value
  value="$(tr -d '\r\n' < "$source")"
  if [[ "$value" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    if [[ -s "$target" ]] && [[ "$(tr -d '\r\n' < "$target")" != "$value" ]]; then
      cp "$target" "$(dirname "$target")/previous-$(basename "$target")"
    fi
    printf '%s\n' "$value" > "$target"
  elif [[ ! -s "$target" ]]; then
    printf '%s\n' unresolved > "$target"
  fi
}
install_resolved_digest "$DEST/API_IMAGE_DIGEST" "$ROOT_DIR/.deploy/release-api-digest"
install_resolved_digest "$DEST/WORKER_IMAGE_DIGEST" "$ROOT_DIR/.deploy/release-worker-digest"
install_resolved_digest "$DEST/MIGRATE_IMAGE_DIGEST" "$ROOT_DIR/.deploy/release-migrate-digest"
install_resolved_digest "$DEST/RUNTIME_BASE_IMAGE_DIGEST" "$ROOT_DIR/.deploy/release-runtime-base-digest"
