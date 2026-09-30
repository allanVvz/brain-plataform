#!/usr/bin/env bash
# Run on the VPS only. One AKIA API image, one health check, automatic rollback.
set -Eeuo pipefail

mode="${1:---dry-run}"
image="${2:-}"
[[ "$mode" == --dry-run || "$mode" == --apply ]] || { echo 'use --dry-run or --apply' >&2; exit 2; }
[[ "$image" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || { echo 'image must use an immutable sha256 digest' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
[[ -s .env.compose ]] || { echo '.env.compose is required on the VPS' >&2; exit 2; }
[[ -n "${AKIA_OPERATIONS_ENV_FILE:-}" && -s "$AKIA_OPERATIONS_ENV_FILE" ]] || {
  echo 'AKIA_OPERATIONS_ENV_FILE must point to a populated private env file' >&2; exit 2;
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

compose=(docker compose --env-file .env.compose -f docker-compose.yml -f infra/akia/compose.yml)
export AKIA_OPERATIONS_API_IMAGE="$image"
"${compose[@]}" config --quiet
old_container="$("${compose[@]}" ps -q operations-api 2>/dev/null || true)"
old_image=''
if [[ -n "$old_container" ]]; then
  old_image="$(docker inspect --format '{{.Config.Image}}' "$old_container")"
fi
printf 'AKIA_RELEASE_PLAN mode=%s candidate=%s current=%s\n' "$mode" "$image" "${old_image:-none}"
[[ "$mode" == --apply ]] || exit 0

"${compose[@]}" pull operations-api
check_disk after_pull

# Prove the candidate on the same private network and environment before
# replacing the active Compose container. Only this short-lived container is
# removed by the trap; data, volumes and release images are untouched.
db_container="$("${compose[@]}" ps -q db)"
[[ -n "$db_container" ]] || { echo 'running db container required' >&2; exit 1; }
network="$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$db_container" | head -n 1)"
[[ -n "$network" ]] || { echo 'db private network not found' >&2; exit 1; }
candidate="akia-operations-candidate-$$"
cleanup_candidate() { docker rm -f "$candidate" >/dev/null 2>&1 || true; }
trap cleanup_candidate EXIT
docker run -d --name "$candidate" --network "$network" --env-file "$AKIA_OPERATIONS_ENV_FILE" \
  -e OPERATIONS_API_PORT=8096 "$image" >/dev/null

candidate_ready=false
for _ in $(seq 1 12); do
  if docker exec "$candidate" node -e "fetch('http://127.0.0.1:8096/health/ready').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))" >/dev/null 2>&1; then
    candidate_ready=true
    break
  fi
  sleep 5
done
[[ "$candidate_ready" == true ]] || { echo 'candidate failed DB/schema readiness' >&2; exit 1; }
check_disk before_cutover

wait_for_health() {
  local container status
  for _ in $(seq 1 24); do
    container="$("${compose[@]}" ps -q operations-api 2>/dev/null || true)"
    if [[ -n "$container" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container")"
      [[ "$status" == healthy ]] && return 0
    fi
    sleep 5
  done
  return 1
}

rollback() {
  [[ -n "$old_image" && "$old_image" != "$image" ]] || return 1
  export AKIA_OPERATIONS_API_IMAGE="$old_image"
  "${compose[@]}" up -d --no-deps --force-recreate operations-api || return 1
  wait_for_health || return 1
  echo "AKIA_RELEASE_ROLLBACK=healthy image=$old_image" >&2
}

if ! "${compose[@]}" up -d --no-deps --force-recreate operations-api || ! wait_for_health; then
  echo 'AKIA operations API failed cutover health check' >&2
  rollback || echo 'AKIA_RELEASE_ROLLBACK=failed_or_unavailable' >&2
  exit 1
fi

mkdir -p .deploy/akia
printf '%s\n' "$image" > .deploy/akia/current-operations-api-image
if [[ -n "$old_image" && "$old_image" != "$image" ]]; then
  printf '%s\n' "$old_image" > .deploy/akia/previous-operations-api-image
fi
printf 'AKIA_RELEASE_RESULT=healthy image=%s\n' "$image"
