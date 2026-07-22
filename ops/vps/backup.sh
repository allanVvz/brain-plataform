#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai}"
mkdir -p "$BACKUP_ROOT"
BACKUP_ROOT="$(realpath "$BACKUP_ROOT")"
case "$BACKUP_ROOT" in
  /|/var|/var/backups) echo "Refusing unsafe BACKUP_ROOT: $BACKUP_ROOT" >&2; exit 2 ;;
esac
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")

"${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DEST/postgres.dump"

volume_name() {
  local logical="$1"
  docker volume ls --quiet \
    --filter "label=com.docker.compose.project=brain-ai" \
    --filter "label=com.docker.compose.volume=$logical" | head -n 1
}
for logical in storage-data local-storage vault-data; do
  volume="$(volume_name "$logical")"
  [[ -n "$volume" ]] || { echo "Volume not found: $logical" >&2; exit 1; }
  docker run --rm -v "$volume:/source:ro" -v "$DEST:/backup" alpine:3.20 \
    tar -C /source -czf "/backup/$logical.tar.gz" .
done

sha256sum "$DEST"/* > "$DEST/SHA256SUMS"
ln -sfn "$DEST" "$BACKUP_ROOT/latest"
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +7 -name '20*T*Z' -exec rm -rf -- {} +
if [[ "$(date -u +%u)" == "7" ]]; then
  mkdir -p "$BACKUP_ROOT/weekly"
  cp -al "$DEST" "$BACKUP_ROOT/weekly/$STAMP"
  find "$BACKUP_ROOT/weekly" -mindepth 1 -maxdepth 1 -type d -mtime +28 -exec rm -rf -- {} +
fi
echo "Backup complete: $DEST"
