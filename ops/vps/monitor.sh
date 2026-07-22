#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
cd "$ROOT_DIR"
failed=0
for service in db rest storage kong api workers caddy; do
  cid="$(docker compose --env-file "$ENV_FILE" ps -q "$service")"
  if [[ -z "$cid" || "$(docker inspect -f '{{.State.Status}}' "$cid")" != "running" ]]; then
    echo "CRITICAL: $service is not running"; failed=1
  elif [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")" == "unhealthy" ]]; then
    echo "CRITICAL: $service is unhealthy"; failed=1
  fi
done
disk_used="$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
(( disk_used < 85 )) || { echo "CRITICAL: disk usage is ${disk_used}%"; failed=1; }
memory_used="$(free | awk '/Mem:/ {printf("%.0f", $3/$2*100)}')"
(( memory_used < 90 )) || { echo "WARNING: memory usage is ${memory_used}%"; failed=1; }
latest="$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -name postgres.dump -mmin -1560 -print -quit 2>/dev/null || true)"
[[ -n "$latest" ]] || { echo "CRITICAL: no successful database backup in the last 26 hours"; failed=1; }
exit "$failed"

