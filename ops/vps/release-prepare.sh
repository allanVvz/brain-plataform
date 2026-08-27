#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
# Arguments are the typed lifecycle prepare contract. Keeping this as a small
# idempotent command makes preparation independently invocable and testable.
python3 ops/vps/release_lifecycle.py prepare "$@"
