#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_MODE="${1:?usage: release-migrate.sh <evidence_only|fresh_required>}"
[[ "$BACKUP_MODE" == "evidence_only" || "$BACKUP_MODE" == "fresh_required" ]] || { echo "invalid backup mode" >&2; exit 2; }
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
if [[ "$BACKUP_MODE" == "fresh_required" ]]; then
  bash ops/vps/backup.sh
else
  echo "compatible migration: using scheduled backup evidence"
fi
"${COMPOSE[@]}" up -d db
"${COMPOSE[@]}" up --no-deps --force-recreate db-bootstrap
"${COMPOSE[@]}" up --no-deps --force-recreate migrate
"${COMPOSE[@]}" up -d --no-deps --force-recreate rest
