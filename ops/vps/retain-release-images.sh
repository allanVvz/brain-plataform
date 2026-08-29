#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${BRAIN_RELEASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
MODE="${1:-${RETENTION_MODE:---dry-run}}"
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "expected --dry-run or --apply" >&2; exit 2; }
if [[ "$MODE" == "--apply" && "${CLEANUP_AUTHORIZED:-false}" != "true" ]]; then
  echo "cleanup apply requires CLEANUP_AUTHORIZED=true from a separately approved operation" >&2
  exit 2
fi
cd "$ROOT_DIR"

disk_percent() {
  df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/, "", $5); print $5}'
}

printf 'DISK_BEFORE\tpercent=%s\n' "$(disk_percent)"
printf 'CACHE_INVENTORY_BEGIN\n'
docker system df
docker image ls --filter dangling=true --no-trunc \
  --format 'DANGLING_IMAGE\t{{.ID}}\t{{.Size}}\tcreated={{.CreatedSince}}'
docker builder du 2>/dev/null || true
printf 'CACHE_INVENTORY_END\n'

declare -A keep=()
record_component() {
  local component="$1" value="$2"
  [[ "$value" =~ ^[0-9a-f]{40}$ ]] && keep["$component:$value"]=1
}
record_manifest() {
  local path="$1" key value
  [[ -s "$path" ]] || return 0
  while IFS='=' read -r key value; do
    case "$key" in
      API_TAG) record_component api "$value" ;;
      WORKER_TAG) record_component workers "$value" ;;
      MIGRATE_TAG) record_component migrate "$value" ;;
    esac
  done < "$path"
}
record_manifest .deploy/components.env
record_manifest .deploy/previous-components.env
current_release="$(tr -d '\r\n' < .deploy/current-tag 2>/dev/null || true)"
previous_release="$(tr -d '\r\n' < .deploy/previous-tag 2>/dev/null || true)"
record_component runtime-base "$current_release"
record_component runtime-base "$previous_release"
if [[ ! -s .deploy/components.env ]]; then
  for component in api workers migrate; do
    record_component "$component" "$current_release"
    record_component "$component" "$previous_release"
  done
fi

removed=0
preserved=0
while IFS=$'\t' read -r reference image_id; do
  [[ "$reference" =~ ^(.*/)?brain-(runtime-base|api|workers|migrate):([0-9a-f]{40})$ ]] || continue
  component="${BASH_REMATCH[2]}"
  tag="${BASH_REMATCH[3]}"
  if [[ -n "${keep[$component:$tag]:-}" ]]; then
    printf 'KEEP\t%s\t%s\n' "$reference" "$image_id"
    preserved=$((preserved + 1))
    continue
  fi
  mapfile -t containers < <(docker ps -a --filter "ancestor=$image_id" --format '{{.ID}}\t{{.Names}}\t{{.State}}\t{{.Status}}')
  container_count="${#containers[@]}"
  removable_containers=()
  preserve_in_use=false
  if (( container_count > 0 )); then
    for container in "${containers[@]}"; do
      IFS=$'\t' read -r container_id container_name container_state container_status <<< "$container"
      case "$container_state" in
        exited|dead|created)
          removable_containers+=("$container_id")
          printf 'STALE_CONTAINER\t%s\t%s\tstate=%s\tstatus=%s\timage=%s\n' \
            "$container_id" "$container_name" "$container_state" "$container_status" "$reference"
          ;;
        *)
          printf 'KEEP_CONTAINER\t%s\t%s\tstate=%s\tstatus=%s\timage=%s\n' \
            "$container_id" "$container_name" "$container_state" "$container_status" "$reference"
          preserve_in_use=true
          ;;
      esac
    done
  fi
  if [[ "$preserve_in_use" == "true" ]]; then
    printf 'KEEP_IN_USE\t%s\t%s\tcontainers=%s\n' "$reference" "$image_id" "$container_count"
    preserved=$((preserved + 1))
    continue
  fi
  printf '%s\t%s\t%s\n' "${MODE#--}" "$reference" "$image_id"
  if [[ "$MODE" == "--apply" ]]; then
    if (( ${#removable_containers[@]} > 0 )); then
      docker container rm "${removable_containers[@]}"
    fi
    docker image rm "$reference"
  fi
  removed=$((removed + 1))
done < <(docker image ls --no-trunc --format '{{.Repository}}:{{.Tag}}\t{{.ID}}')
if [[ "$MODE" == "--apply" ]]; then
  # These commands never prune volumes. Docker itself limits image pruning to
  # unreferenced dangling layers and builder pruning to unused build cache.
  docker image prune --force
  docker builder prune --force
fi
printf 'DISK_AFTER\tpercent=%s\n' "$(disk_percent)"
printf 'SUMMARY\tmode=%s\tcandidates=%s\tpreserved=%s\n' "$MODE" "$removed" "$preserved"
