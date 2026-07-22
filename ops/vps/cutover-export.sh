#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
cd "$ROOT_DIR"
docker compose --env-file "$ENV_FILE" stop caddy api workers seed-admin
echo "Writes are stopped; creating the final consistent export."
bash "$ROOT_DIR/ops/vps/backup.sh"
echo "Source remains in maintenance mode. Re-enable only for rollback with docker compose --env-file .env.compose up -d."
