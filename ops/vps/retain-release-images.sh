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
printf 'RELEASE_ROOT_INVENTORY_BEGIN\n'
du -x -d 1 "$ROOT_DIR" 2>/dev/null | sort -n || true
if [[ -d "$ROOT_DIR/.releases" ]]; then
  printf 'RELEASE_DETAIL_INVENTORY_BEGIN\n'
  du -x -d 1 "$ROOT_DIR/.releases" 2>/dev/null | sort -n || true
  find "$ROOT_DIR/.releases" -mindepth 1 -maxdepth 1 -type f \
    -printf 'RELEASE_FILE\t%p\tbytes=%s\n' 2>/dev/null | sort || true
  printf 'RELEASE_DETAIL_INVENTORY_END\n'
fi
printf 'RELEASE_ROOT_INVENTORY_END\n'
printf 'FILESYSTEM_INVENTORY_BEGIN\n'
for inventory_root in /var /var/lib /var/log /var/cache /var/cache/apt /var/backups /var/backups/brain-ai /tmp /opt; do
  [[ -d "$inventory_root" ]] || continue
  printf 'FILESYSTEM_ROOT\t%s\n' "$inventory_root"
  du -x -d 1 "$inventory_root" 2>/dev/null | sort -n || true
done
for inventory_files_root in /var/backups/brain-ai /var/cache/apt /tmp; do
  [[ -d "$inventory_files_root" ]] || continue
  find "$inventory_files_root" -mindepth 1 -maxdepth 1 -type f \
    -printf 'FILESYSTEM_FILE\t%p\tbytes=%s\tmodified=%TY-%Tm-%TdT%TH:%TM:%TSZ\n' 2>/dev/null | sort || true
done
printf 'FILESYSTEM_INVENTORY_END\n'
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

retain_release_history() {
  local release_root="$ROOT_DIR/.releases"
  local artifact_root="$ROOT_DIR/.release"
  local current_tag previous_tag current_directory
  current_tag="$(tr -d '\r\n' < "$ROOT_DIR/.deploy/current-tag" 2>/dev/null || true)"
  previous_tag="$(tr -d '\r\n' < "$ROOT_DIR/.deploy/previous-tag" 2>/dev/null || true)"
  current_directory="$(tr -d '\r\n' < "$ROOT_DIR/.deploy/release-directory" 2>/dev/null || true)"
  if [[ -n "$current_directory" ]]; then
    current_directory="$(realpath "$current_directory" 2>/dev/null || true)"
  fi

  if [[ -d "$release_root" ]]; then
    release_root="$(realpath "$release_root")"
    [[ "$release_root" == "$ROOT_DIR/.releases" ]] || {
      echo "Refusing unexpected release root: $release_root" >&2
      exit 2
    }
    declare -A release_keep=() release_weeks=() release_months=()
    local release_week_count=0 release_month_count=0
    mapfile -t release_entries < <(find "$release_root" -mindepth 1 -maxdepth 1 -type d \
      -printf '%T@\t%p\n' | awk -F '\t' '$2 ~ /\/[0-9a-f]{40}$/' | sort -rn)
    local index entry epoch directory week month bytes resolved reason
    local release_candidates=0 release_bytes=0
    for index in "${!release_entries[@]}"; do
      entry="${release_entries[$index]}"
      epoch="${entry%%$'\t'*}"
      directory="${entry#*$'\t'}"
      reason=""
      if (( index < 3 )); then reason="recent"; fi
      week="$(date -u -d "@${epoch%.*}" +%G-W%V)"
      month="$(date -u -d "@${epoch%.*}" +%Y%m)"
      if (( release_week_count < 2 )) && [[ -z "${release_weeks[$week]:-}" ]]; then
        release_weeks["$week"]=1
        release_week_count=$((release_week_count + 1))
        reason="${reason:+$reason,}weekly"
      fi
      if (( release_month_count < 3 )) && [[ -z "${release_months[$month]:-}" ]]; then
        release_months["$month"]=1
        release_month_count=$((release_month_count + 1))
        reason="${reason:+$reason,}monthly"
      fi
      [[ "$(basename "$directory")" == "$current_tag" ]] && reason="${reason:+$reason,}current"
      [[ "$(basename "$directory")" == "$previous_tag" ]] && reason="${reason:+$reason,}previous"
      [[ "$directory" == "$current_directory" ]] && reason="${reason:+$reason,}release_directory"
      [[ -e "$directory/.keep" ]] && reason="${reason:+$reason,}keep_marker"
      bytes="$(du -sb "$directory" | awk '{print $1}')"
      if [[ -n "$reason" ]]; then
        printf 'RELEASE_KEEP\t%s\tbytes=%s\treason=%s\n' "$directory" "$bytes" "$reason"
        continue
      fi
      resolved="$(realpath "$directory")"
      [[ "$resolved" =~ ^${release_root}/[0-9a-f]{40}$ ]] || {
        echo "Refusing unsafe release candidate: $resolved" >&2; exit 2;
      }
      printf 'RELEASE_CANDIDATE\t%s\tbytes=%s\n' "$resolved" "$bytes"
      release_candidates=$((release_candidates + 1))
      release_bytes=$((release_bytes + bytes))
      if [[ "$MODE" == "--apply" ]]; then rm -rf -- "$resolved"; fi
    done
    printf 'RELEASE_SUMMARY\tmode=%s\tcandidates=%s\tbytes=%s\tpolicy=3_recent+2_weekly+3_monthly\n' \
      "$MODE" "$release_candidates" "$release_bytes"
  fi

  if [[ -d "$artifact_root" ]]; then
    artifact_root="$(realpath "$artifact_root")"
    [[ "$artifact_root" == "$ROOT_DIR/.release" ]] || {
      echo "Refusing unexpected artifact root: $artifact_root" >&2
      exit 2
    }
    declare -A artifact_weeks=() artifact_months=()
    local artifact_week_count=0 artifact_month_count=0
    mapfile -t artifact_entries < <(find "$artifact_root" -mindepth 1 -maxdepth 1 -type f \
      -name 'brain-release-*.tar.gz' -printf '%T@\t%p\n' | sort -rn)
    local artifact_candidates=0 artifact_bytes=0 archive checksum sha archive_bytes checksum_bytes
    for index in "${!artifact_entries[@]}"; do
      entry="${artifact_entries[$index]}"
      epoch="${entry%%$'\t'*}"
      archive="${entry#*$'\t'}"
      sha="$(basename "$archive")"
      sha="${sha#brain-release-}"; sha="${sha%.tar.gz}"
      [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || continue
      reason=""
      if (( index < 3 )); then reason="recent"; fi
      week="$(date -u -d "@${epoch%.*}" +%G-W%V)"
      month="$(date -u -d "@${epoch%.*}" +%Y%m)"
      if (( artifact_week_count < 2 )) && [[ -z "${artifact_weeks[$week]:-}" ]]; then
        artifact_weeks["$week"]=1; artifact_week_count=$((artifact_week_count + 1)); reason="${reason:+$reason,}weekly"
      fi
      if (( artifact_month_count < 3 )) && [[ -z "${artifact_months[$month]:-}" ]]; then
        artifact_months["$month"]=1; artifact_month_count=$((artifact_month_count + 1)); reason="${reason:+$reason,}monthly"
      fi
      [[ "$sha" == "$current_tag" ]] && reason="${reason:+$reason,}current"
      [[ "$sha" == "$previous_tag" ]] && reason="${reason:+$reason,}previous"
      checksum="$archive.sha256"
      archive_bytes="$(stat -c %s "$archive")"
      checksum_bytes=0; [[ -f "$checksum" ]] && checksum_bytes="$(stat -c %s "$checksum")"
      bytes=$((archive_bytes + checksum_bytes))
      if [[ -n "$reason" ]]; then
        printf 'ARTIFACT_KEEP\t%s\tbytes=%s\treason=%s\n' "$archive" "$bytes" "$reason"
        continue
      fi
      resolved="$(realpath "$archive")"
      [[ "$resolved" =~ ^${artifact_root}/brain-release-[0-9a-f]{40}\.tar\.gz$ ]] || {
        echo "Refusing unsafe artifact candidate: $resolved" >&2; exit 2;
      }
      printf 'ARTIFACT_CANDIDATE\t%s\tbytes=%s\n' "$resolved" "$bytes"
      artifact_candidates=$((artifact_candidates + 1)); artifact_bytes=$((artifact_bytes + bytes))
      if [[ "$MODE" == "--apply" ]]; then rm -f -- "$resolved" "$checksum"; fi
    done
    printf 'ARTIFACT_SUMMARY\tmode=%s\tcandidates=%s\tbytes=%s\tpolicy=3_recent+2_weekly+3_monthly\n' \
      "$MODE" "$artifact_candidates" "$artifact_bytes"
  fi
}

retain_release_history
printf 'DISK_RELEASE_HISTORY\tpercent=%s\n' "$(disk_percent)"

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

backup_root="${BACKUP_ROOT:-/var/backups/brain-ai}"
if [[ -d "$backup_root" ]]; then
  backup_root="$(realpath "$backup_root")"
  [[ "$backup_root" == "/var/backups/brain-ai" ]] || {
    echo "Refusing unexpected backup root: $backup_root" >&2
    exit 2
  }
  latest_target="$(realpath "$backup_root/latest" 2>/dev/null || true)"
  restore_target="$(awk '{for (i=1;i<=NF;i++) if ($i ~ /^backup=/) {sub(/^backup=/,"",$i); print $i}}' \
    "$backup_root/restore-tests/LAST_SUCCESS" 2>/dev/null || true)"
  if [[ -n "$restore_target" ]]; then
    restore_target="$(realpath "$restore_target" 2>/dev/null || true)"
  fi
  declare -A backup_keep=() weekly_seen=() monthly_seen=()
  mapfile -t backup_dirs < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\t%p\n' | awk -F '\t' '$1 ~ /^[0-9]{8}T[0-9]{6}Z$/' | sort -r | cut -f2-)
  for index in "${!backup_dirs[@]}"; do
    directory="${backup_dirs[$index]}"
    stamp="$(basename "$directory")"
    if (( index < 3 )); then
      backup_keep["$directory"]="recent"
    fi
    week="$(date -u -d "${stamp:0:4}-${stamp:4:2}-${stamp:6:2}" +%G-W%V)"
    month="${stamp:0:6}"
    if (( ${#weekly_seen[@]} < 2 )) && [[ -z "${weekly_seen[$week]:-}" ]]; then
      weekly_seen["$week"]=1; backup_keep["$directory"]="${backup_keep[$directory]:+${backup_keep[$directory]},}weekly"
    fi
    if (( ${#monthly_seen[@]} < 3 )) && [[ -z "${monthly_seen[$month]:-}" ]]; then
      monthly_seen["$month"]=1; backup_keep["$directory"]="${backup_keep[$directory]:+${backup_keep[$directory]},}monthly"
    fi
    if [[ "$directory" == "$latest_target" ]]; then
      backup_keep["$directory"]="${backup_keep[$directory]:+${backup_keep[$directory]},}latest"
    fi
    if [[ "$directory" == "$restore_target" ]]; then
      backup_keep["$directory"]="${backup_keep[$directory]:+${backup_keep[$directory]},}last_restore"
    fi
    if [[ -e "$directory/.keep" ]]; then
      backup_keep["$directory"]="${backup_keep[$directory]:+${backup_keep[$directory]},}keep_marker"
    fi
  done
  backup_candidates=0
  backup_bytes=0
  for directory in "${backup_dirs[@]}"; do
    bytes="$(du -sb "$directory" | awk '{print $1}')"
    if [[ -n "${backup_keep[$directory]:-}" ]]; then
      printf 'BACKUP_KEEP\t%s\tbytes=%s\treason=%s\n' "$directory" "$bytes" "${backup_keep[$directory]}"
      continue
    fi
    resolved="$(realpath "$directory")"
    [[ "$resolved" == "$backup_root"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z ]] || {
      echo "Refusing unsafe backup candidate: $resolved" >&2; exit 2;
    }
    printf 'BACKUP_CANDIDATE\t%s\tbytes=%s\n' "$resolved" "$bytes"
    backup_candidates=$((backup_candidates + 1)); backup_bytes=$((backup_bytes + bytes))
    if [[ "$MODE" == "--apply" ]]; then
      rm -rf -- "$resolved"
    fi
  done
  printf 'BACKUP_SUMMARY\tmode=%s\tcandidates=%s\tbytes=%s\tpolicy=3_recent+2_weekly+3_monthly\n' \
    "$MODE" "$backup_candidates" "$backup_bytes"
  printf 'DISK_FINAL\tpercent=%s\n' "$(disk_percent)"
fi
