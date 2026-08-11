#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/brain-ai/releases}"
[[ -d "$BACKUP_ROOT" ]] || { echo "Backup root not found: $BACKUP_ROOT" >&2; exit 1; }
BACKUP_ROOT="$(realpath "$BACKUP_ROOT")"
case "$BACKUP_ROOT" in
  /|/var|/var/backups|/var/backups/brain-ai)
    echo "Refusing unsafe BACKUP_ROOT: $BACKUP_ROOT" >&2
    exit 2
    ;;
esac

mapfile -d '' directories < <(
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
    -name '20*T*Z-*' -print0 | sort -zr
)

declare -A keep_reasons=()
declare -A weekly_seen=()
declare -A monthly_seen=()

for index in "${!directories[@]}"; do
  directory="${directories[$index]}"
  name="$(basename "$directory")"
  created="${name%%-*}"
  calendar_date="${created:0:4}-${created:4:2}-${created:6:2}"
  if (( index < 7 )); then
    keep_reasons["$directory"]="recent"
  fi
  if [[ -f "$directory/.keep" ]]; then
    keep_reasons["$directory"]="${keep_reasons[$directory]:+${keep_reasons[$directory]},}protected"
  fi
  if (( index >= 7 )); then
    week="$(date -u -d "$calendar_date" +%G-W%V)"
    if (( ${#weekly_seen[@]} < 4 )) && [[ -z "${weekly_seen[$week]:-}" ]]; then
      weekly_seen["$week"]=1
      keep_reasons["$directory"]="${keep_reasons[$directory]:+${keep_reasons[$directory]},}weekly"
    fi
    month="${created:0:6}"
    if (( ${#monthly_seen[@]} < 6 )) && [[ -z "${monthly_seen[$month]:-}" ]]; then
      monthly_seen["$month"]=1
      keep_reasons["$directory"]="${keep_reasons[$directory]:+${keep_reasons[$directory]},}monthly"
    fi
  fi
done

printf 'status\treason\tcreated_utc\tbytes\tlabel\tpath\n'
total=0
count=0
review_bytes=0
review_count=0
for directory in "${directories[@]}"; do
  name="$(basename "$directory")"
  created="${name%%-*}"
  label="${name#*-}"
  bytes="$(du -sb "$directory" | awk '{print $1}')"
  total=$((total + bytes))
  count=$((count + 1))
  reason="${keep_reasons[$directory]:-}"
  if [[ -n "$reason" ]]; then
    status="keep"
  else
    status="review"
    review_bytes=$((review_bytes + bytes))
    review_count=$((review_count + 1))
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$status" "${reason:--}" "$created" "$bytes" "$label" "$directory"
done

printf 'SUMMARY\tcount=%s\tbytes=%s\treview_count=%s\treview_bytes=%s\troot=%s\n' \
  "$count" "$total" "$review_count" "$review_bytes" "$BACKUP_ROOT"
printf 'POLICY\tkeep=7 recent full + 4 weekly full + 6 monthly full; preserve *.keep; removal requires explicit approval\n'
