#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_DIR="${1:-}"
CONFIRM="${2:-}"
[[ "$CONFIRM" == "--confirm-destructive-restore" ]] || { echo "usage: restore.sh <backup-dir> --confirm-destructive-restore" >&2; exit 2; }
BACKUP_DIR="$(realpath "$BACKUP_DIR")"
[[ -d "$BACKUP_DIR" && -f "$BACKUP_DIR/postgres.dump" && -f "$BACKUP_DIR/SHA256SUMS" ]] || { echo "Invalid backup directory" >&2; exit 2; }
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" stop caddy api workers seed-admin kong rest storage
"${COMPOSE[@]}" up -d db
"${COMPOSE[@]}" create storage api workers
cat "$BACKUP_DIR/postgres.dump" | "${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner'

volume_name() {
  docker volume ls --quiet --filter "label=com.docker.compose.project=brain-ai" --filter "label=com.docker.compose.volume=$1" | head -n 1
}
for logical in storage-data local-storage vault-data; do
  archive="$BACKUP_DIR/$logical.tar.gz"
  [[ -f "$archive" ]] || { echo "Missing $archive" >&2; exit 1; }
  volume="$(volume_name "$logical")"
  [[ -n "$volume" ]] || { echo "Volume not found: $logical" >&2; exit 1; }
  docker run --rm -v "$volume:/target" -v "$BACKUP_DIR:/backup:ro" alpine:3.20 \
    sh -c "find /target -mindepth 1 -delete && tar -C /target -xzf /backup/$logical.tar.gz"
done
"${COMPOSE[@]}" up --no-deps --force-recreate migrate
"${COMPOSE[@]}" up -d rest storage kong api workers seed-admin caddy
echo "Restore complete. Run ops/vps/audit.sh and application acceptance tests."
