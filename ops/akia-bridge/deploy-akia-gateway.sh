#!/usr/bin/env bash
# VPS only: publish the AKIA portal edge without replacing the Brain gateway.
set -Eeuo pipefail
mode="${1:---dry-run}"
image="${2:-}"
[[ "$mode" == --dry-run || "$mode" == --apply ]] || { echo 'use --dry-run or --apply' >&2; exit 2; }
[[ "$image" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || { echo 'image must use an immutable sha256 digest' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
[[ -s .env.compose ]] || { echo '.env.compose is required on the VPS' >&2; exit 2; }
[[ -n "${AKIA_GATEWAY_ENV_FILE:-}" && -s "$AKIA_GATEWAY_ENV_FILE" ]] || {
  echo 'AKIA_GATEWAY_ENV_FILE must point to a populated private env file' >&2; exit 2;
}
docker_root="$(docker info --format '{{.DockerRootDir}}')"
check_disk() {
  local label="$1" path used
  for path in "$root" "$docker_root"; do
    used="$(df -P "$path" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
    [[ "$used" =~ ^[0-9]+$ ]] && (( used < 50 )) || {
      echo "disk gate failed at $label: $path ${used:-unknown}% required <50%" >&2; return 1;
    }
    printf 'AKIA_DISK_GATE phase=%s path=%s used=%s%%\n' "$label" "$path" "$used"
  done
}
check_disk before
compose=(docker compose --env-file .env.compose -f docker-compose.yml -f infra/akia/gateway.compose.yml)
export AKIA_GATEWAY_IMAGE="$image"
"${compose[@]}" config --quiet
old_container="$("${compose[@]}" ps -q akia-gateway 2>/dev/null || true)"
old_image=''
if [[ -n "$old_container" ]]; then old_image="$(docker inspect --format '{{.Config.Image}}' "$old_container")"; fi
printf 'AKIA_RELEASE_PLAN service=akia-gateway mode=%s candidate=%s current=%s\n' "$mode" "$image" "${old_image:-none}"
[[ "$mode" == --apply ]] || exit 0
"${compose[@]}" pull akia-gateway
check_disk after_pull

candidate="akia-gateway-candidate-$$"
cleanup_candidate() { docker rm -f "$candidate" >/dev/null 2>&1 || true; }
trap cleanup_candidate EXIT
"${compose[@]}" run --no-deps -d --name "$candidate" akia-gateway >/dev/null
wait_for_health() {
  local container="$1" status
  for _ in $(seq 1 24); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container" 2>/dev/null || true)"
    [[ "$status" == healthy ]] && return 0
    [[ "$status" == unhealthy ]] && return 1
    sleep 5
  done
  return 1
}
wait_for_health "$candidate" || { echo 'candidate failed readiness' >&2; exit 1; }
check_disk before_cutover
rollback() {
  [[ -n "$old_image" && "$old_image" != "$image" ]] || return 1
  export AKIA_GATEWAY_IMAGE="$old_image"
  "${compose[@]}" up -d --no-deps --force-recreate akia-gateway || return 1
  local previous
  previous="$("${compose[@]}" ps -q akia-gateway)"
  wait_for_health "$previous" || return 1
  echo "AKIA_RELEASE_ROLLBACK=healthy image=$old_image" >&2
}
if ! "${compose[@]}" up -d --no-deps --force-recreate akia-gateway; then
  rollback || echo 'AKIA_RELEASE_ROLLBACK=failed_or_unavailable' >&2
  exit 1
fi
active="$("${compose[@]}" ps -q akia-gateway)"
if ! wait_for_health "$active"; then
  rollback || echo 'AKIA_RELEASE_ROLLBACK=failed_or_unavailable' >&2
  exit 1
fi
mkdir -p .deploy/akia
printf '%s\n' "$image" > .deploy/akia/current-gateway-image
printf 'AKIA_RELEASE_RESULT=healthy service=akia-gateway image=%s\n' "$image"
