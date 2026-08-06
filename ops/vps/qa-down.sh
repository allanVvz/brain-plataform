#!/usr/bin/env bash
set -Eeuo pipefail

# Stops the whole QA stack: containers removed, only the named volumes
# (Postgres data, storage, etc.) stay on disk. Zero CPU/RAM usage on the VPS
# until the next `deploy-qa.sh` run brings it back up. This is the "QA is
# off" state the deploy-qa.yml workflow's `action: down` calls.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
cd "$ROOT_DIR"
docker compose --env-file "$ENV_FILE" down --remove-orphans
echo "QA stack stopped."
