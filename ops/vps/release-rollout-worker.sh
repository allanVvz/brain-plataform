#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
EXPECTED_SHA="${1:?usage: release-rollout-worker.sh <full-git-sha>}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "full Git SHA required" >&2; exit 2; }
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" up -d --no-deps workers
worker_source="$("${COMPOSE[@]}" exec -T workers sh -c 'cat /image-source-sha')"
[[ "$worker_source" == "$EXPECTED_SHA" ]] || { echo "worker source SHA mismatch" >&2; exit 1; }
