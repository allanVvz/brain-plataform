#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$ROOT_DIR/.deploy"
TAG="${1:-}"
if [[ -z "$TAG" && -f "$STATE_DIR/previous-tag" ]]; then
  TAG="$(tr -d '\r\n' < "$STATE_DIR/previous-tag")"
fi
[[ -n "$TAG" ]] || { echo "No rollback tag supplied or recorded." >&2; exit 1; }
exec "$ROOT_DIR/ops/vps/deploy.sh" "$TAG"

