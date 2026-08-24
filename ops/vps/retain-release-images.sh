#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${BRAIN_RELEASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
MODE="${1:---dry-run}"
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "expected --dry-run or --apply" >&2; exit 2; }
if [[ "$MODE" == "--apply" && "${CLEANUP_AUTHORIZED:-false}" != "true" ]]; then
  echo "cleanup apply requires CLEANUP_AUTHORIZED=true from a separately approved operation" >&2
  exit 2
fi
cd "$ROOT_DIR"

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
  container_count="$(docker ps -a --filter "ancestor=$image_id" --format '{{.ID}}' | wc -l | tr -d '[:space:]')"
  if (( container_count > 0 )); then
    printf 'KEEP_IN_USE\t%s\t%s\tcontainers=%s\n' "$reference" "$image_id" "$container_count"
    preserved=$((preserved + 1))
    continue
  fi
  printf '%s\t%s\t%s\n' "${MODE#--}" "$reference" "$image_id"
  if [[ "$MODE" == "--apply" ]]; then
    docker image rm "$reference"
  fi
  removed=$((removed + 1))
done < <(docker image ls --no-trunc --format '{{.Repository}}:{{.Tag}}\t{{.ID}}')
printf 'SUMMARY\tmode=%s\tcandidates=%s\tpreserved=%s\n' "$MODE" "$removed" "$preserved"
