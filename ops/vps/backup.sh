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

"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --format=custom' \
  > "$DEST/postgres-data.dump"
"${COMPOSE[@]}" exec -T db pg_restore --list \
  < "$DEST/postgres-data.dump" > "$DEST/postgres-data.restore-list.txt"
grep -q 'TABLE DATA' "$DEST/postgres-data.restore-list.txt"
printf '%s\n' "data-only" > "$DEST/BACKUP_KIND"
find "$DEST" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$DEST/SHA256SUMS"
(cd "$DEST" && sha256sum --check SHA256SUMS)
ln -sfn "$DEST" "$BACKUP_ROOT/latest"
# Retention is intentionally not destructive here. summarize-release-backups.sh
# produces the exact dry-run inventory; deletion requires separate approval.
echo "Backup complete: $DEST"
