#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai/releases}"
LABEL="${1:-pre-aurora}"
VERCEL_DEPLOYMENT_ID="${VERCEL_DEPLOYMENT_ID:-dpl_28HXRjZ42wv1zfjC8nrqqoYsdFZ6}"
BACKUP_INCLUDE_UNTRACKED_SOURCE="${BACKUP_INCLUDE_UNTRACKED_SOURCE:-false}"

[[ "$LABEL" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$ ]] || {
  echo "Invalid backup label: $LABEL" >&2
  exit 2
}
umask 077
mkdir -p "$BACKUP_ROOT"
BACKUP_ROOT="$(realpath "$BACKUP_ROOT")"
case "$BACKUP_ROOT" in
  /|/var|/var/backups|/var/backups/brain-ai)
    echo "Refusing unsafe BACKUP_ROOT: $BACKUP_ROOT" >&2
    exit 2
    ;;
esac

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP-$LABEL"
mkdir -m 0700 "$DEST"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")

env_value() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(
    awk -F= -v wanted="$key" '
      $1 == wanted {
        sub(/^[^=]*=/, "")
        gsub(/^[[:space:]]+|[[:space:]]+$/, "")
        print
      }
    ' "$ENV_FILE" | tail -n 1
  )"
  printf '%s\n' "${value:-$fallback}"
}

echo "Creating verified release backup at $DEST"
"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$DEST/postgres.dump"
"${COMPOSE[@]}" exec -T db pg_restore --list \
  < "$DEST/postgres.dump" > "$DEST/postgres.restore-list.txt"
grep -q 'TABLE DATA' "$DEST/postgres.restore-list.txt"

evolution_database_exists="$(
  "${COMPOSE[@]}" exec -T db sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d postgres -Atc "select 1 from pg_database where datname='\''evolution'\''"'
)"
if [[ "$evolution_database_exists" == "1" ]]; then
  "${COMPOSE[@]}" exec -T db sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d evolution -Fc' \
    > "$DEST/evolution-postgres.dump"
  "${COMPOSE[@]}" exec -T db pg_restore --list \
    < "$DEST/evolution-postgres.dump" > "$DEST/evolution-postgres.restore-list.txt"
elif [[ "$LABEL" == post-aurora* ]]; then
  echo "Evolution database is required for a post-Aurora backup." >&2
  exit 1
fi

volume_name() {
  local logical="$1"
  docker volume ls --quiet \
    --filter "label=com.docker.compose.project=brain-ai" \
    --filter "label=com.docker.compose.volume=$logical" | head -n 1
}

required_volumes=(storage-data local-storage vault-data n8n-data)
optional_volumes=(evolution-redis-data evolution-instances)
if [[ "$LABEL" == post-aurora* ]]; then
  required_volumes+=("${optional_volumes[@]}")
  optional_volumes=()
fi

for logical in "${required_volumes[@]}"; do
  volume="$(volume_name "$logical")"
  [[ -n "$volume" ]] || {
    echo "Required Docker volume not found: $logical" >&2
    exit 1
  }
  docker run --rm \
    -v "$volume:/source:ro" \
    -v "$DEST:/backup" \
    alpine:3.20 \
    tar -C /source -czf "/backup/$logical.tar.gz" .
done
for logical in "${optional_volumes[@]}"; do
  volume="$(volume_name "$logical")"
  [[ -n "$volume" ]] || continue
  docker run --rm \
    -v "$volume:/source:ro" \
    -v "$DEST:/backup" \
    alpine:3.20 \
    tar -C /source -czf "/backup/$logical.tar.gz" .
done

git rev-parse HEAD > "$DEST/source-head.txt"
git status --short > "$DEST/source-status.txt"
git diff --binary > "$DEST/source-working-tree.patch"
git archive --format=tar.gz --output="$DEST/source-head.tar.gz" HEAD
git ls-files --others --exclude-standard -z > "$DEST/untracked-files.list0"
if [[ "$BACKUP_INCLUDE_UNTRACKED_SOURCE" =~ ^(1|true|yes)$ && -s "$DEST/untracked-files.list0" ]]; then
  tar --null -T "$DEST/untracked-files.list0" -czf "$DEST/source-untracked.tar.gz"
elif [[ -s "$DEST/untracked-files.list0" ]]; then
  cat > "$DEST/source-untracked-not-archived.txt" <<'EOF'
Untracked source was inventoried but not archived. Production deploys use
immutable GHCR images and synchronized manifests; the VPS worktree contains
historical .releases/.rollbacks copies that recursively inflated every backup.
Set BACKUP_INCLUDE_UNTRACKED_SOURCE=true only for a one-off forensic capture.
EOF
fi

cp "$ENV_FILE" "$DEST/env.compose.root-only"
chmod 0600 "$DEST/env.compose.root-only"

"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    select payload->'\''graph_json'\''
    from system_events
    where event_type='\''graph_document_published'\''
      and payload->>'\''persona_slug'\''='\''baita-conveniencia'\''
    order by (payload->>'\''version'\'')::integer desc, created_at desc
    limit 1
  "' > "$DEST/baita-graph-v9.json"
"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    select coalesce(payload->>'\''checksum'\'','\'''\'')
    from system_events
    where event_type='\''graph_document_published'\''
      and payload->>'\''persona_slug'\''='\''baita-conveniencia'\''
    order by (payload->>'\''version'\'')::integer desc, created_at desc
    limit 1
  "' > "$DEST/baita-graph-checksum.txt"
"${COMPOSE[@]}" exec -T db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    select payload->>'\''version'\''
    from system_events
    where event_type='\''graph_document_published'\''
      and payload->>'\''persona_slug'\''='\''baita-conveniencia'\''
    order by (payload->>'\''version'\'')::integer desc, created_at desc
    limit 1
  "' > "$DEST/baita-graph-version.txt"
grep -qx '9' "$DEST/baita-graph-version.txt"
grep -Eq '^[0-9a-f]{16,64}$' "$DEST/baita-graph-checksum.txt"
test -s "$DEST/baita-graph-v9.json"
meta_persona_slug="$(env_value WHATSAPP_META_PERSONA_SLUG baita-conveniencia)"
[[ "$meta_persona_slug" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || {
  echo "Invalid WHATSAPP_META_PERSONA_SLUG: $meta_persona_slug" >&2
  exit 2
}
"${COMPOSE[@]}" exec -T \
  -e BACKUP_META_PERSONA_SLUG="$meta_persona_slug" \
  db sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    select jsonb_pretty(jsonb_build_object(
      '\''provider'\'', coalesce(
        to_jsonb(wb)->>'\''provider'\'',
        case
          when nullif(to_jsonb(wb)->>'\''whatsapp_phone_number_id'\'', '\'''\'') is not null
          then '\''meta_cloud'\''
        end
      ),
      '\''active'\'', (to_jsonb(wb)->>'\''active'\'')::boolean,
      '\''connection_status'\'', coalesce(
        to_jsonb(wb)->>'\''connection_status'\'',
        case
          when (to_jsonb(wb)->>'\''active'\'')::boolean then '\''connected'\''
        end
      ),
      '\''provider_instance_key'\'', '\''[REDACTED]'\'',
      '\''whatsapp_phone_number_id'\'', '\''[REDACTED]'\'',
      '\''provider_secret_ciphertext'\'', '\''[REDACTED]'\'',
      '\''metadata'\'', jsonb_build_object(
        '\''mode'\'', (to_jsonb(wb)->'\''metadata'\'')->'\''mode'\'',
        '\''decision_owner'\'', (to_jsonb(wb)->'\''metadata'\'')->'\''decision_owner'\''
      )
    ))
    from workflow_bindings wb
    join personas p on p.id=wb.persona_id
    where p.slug='\''$BACKUP_META_PERSONA_SLUG'\''
      and (to_jsonb(wb)->>'\''active'\'')::boolean=true
    order by (to_jsonb(wb)->>'\''updated_at'\'') desc nulls last
    limit 1
  "' > "$DEST/meta-binding-redacted.json"
grep -q '"provider": "meta_cloud"' "$DEST/meta-binding-redacted.json"
printf '%s\n' "$meta_persona_slug" > "$DEST/meta-binding-persona-slug.txt"

printf '%s\n' "$VERCEL_DEPLOYMENT_ID" > "$DEST/vercel-production-deployment-id.txt"
"${COMPOSE[@]}" ps --all > "$DEST/docker-compose-ps.txt"
docker ps --all --no-trunc > "$DEST/docker-ps.txt"
docker image ls --digests --no-trunc > "$DEST/docker-images.txt"
docker volume ls > "$DEST/docker-volumes.txt"

api_image="$(env_value API_IMAGE brain-api)"
migrate_image="$(env_value MIGRATE_IMAGE brain-migrate)"
pre_release_tag="pre-aurora-$STAMP"
for service in api migrate; do
  cid="$("${COMPOSE[@]}" ps -aq "$service" | head -n 1)"
  [[ -n "$cid" ]] || continue
  image_id="$(docker inspect -f '{{.Image}}' "$cid")"
  if [[ "$service" == "api" ]]; then
    rollback_tag="$api_image:$pre_release_tag"
  else
    rollback_tag="$migrate_image:$pre_release_tag"
  fi
  docker tag "$image_id" "$rollback_tag"
  docker save -o "$DEST/$service-image.tar" "$rollback_tag"
  printf '%s %s\n' "$rollback_tag" "$image_id" >> "$DEST/rollback-image-tags.txt"
done
printf '%s\n' "$pre_release_tag" > "$DEST/pre-release-tag.txt"
mkdir -p "$ROOT_DIR/.deploy"
if [[ ! -s "$ROOT_DIR/.deploy/current-tag" ]]; then
  printf '%s\n' "$pre_release_tag" > "$ROOT_DIR/.deploy/current-tag"
fi

du -sb "$DEST" > "$DEST/BACKUP_SIZE_BYTES"
find "$DEST" -type f ! -name SHA256SUMS -print0 \
  | sort -z \
  | xargs -0 sha256sum > "$DEST/SHA256SUMS"
(
  cd "$DEST"
  sha256sum --check SHA256SUMS
)
chmod -R go-rwx "$DEST"
echo "Release backup verified: $DEST"
