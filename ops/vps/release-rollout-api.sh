#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_SHA="${1:?usage: release-rollout-api.sh <full-git-sha>}"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "full Git SHA required" >&2; exit 2; }
cd "$ROOT_DIR"
bash ops/vps/deploy-api-blue-green.sh "$TARGET_SHA"
