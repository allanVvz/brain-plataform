#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REASON="${1:?usage: pause-worker-claims.sh <reason> [--safety-pause]}"
MODE="${2:-}"
args=(pause-claims --reason "$REASON")
[[ "$MODE" == "--safety-pause" ]] && args+=(--safety-pause)
python3 "$ROOT_DIR/ops/vps/release_lifecycle.py" "${args[@]}"

