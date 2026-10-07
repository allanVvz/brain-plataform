#!/usr/bin/env bash
# VPS only. Selected-service release/config activation with exact env rollback.
set -Eeuo pipefail
umask 077
service="${1:-}"; mode="${2:---dry-run}"; image="${3:-}"
[[ "$service" == operations-api || "$service" == gateway ]] || exit 2
[[ "$mode" == --dry-run || "$mode" == --apply || "$mode" == --activate || "$mode" == --activation-plan ]] || exit 2
[[ "$image" =~ ^ghcr\.io/allanvvz/akia-${service}@sha256:[0-9a-f]{64}$ ]] || exit 2
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$root"
unit=operations-api; overlay=infra/akia/compose.yml; env_file="${AKIA_OPERATIONS_ENV_FILE:-}"
export AKIA_OPERATIONS_API_IMAGE="$image"
if [[ "$service" == gateway ]]; then
 unit=akia-gateway; overlay=infra/akia/gateway.compose.yml; env_file="${AKIA_GATEWAY_ENV_FILE:-}"
 export AKIA_GATEWAY_IMAGE="$image"
fi
[[ "$env_file" == /* && -s "$env_file" && ! -L "$env_file" && "$(stat -c %a "$env_file")" == 600 ]] || exit 2
compose=(docker compose --env-file .env.compose -f docker-compose.yml -f "$overlay")
"${compose[@]}" config --quiet
check_disk(){ local p used; for p in "$root" "$(docker info --format '{{.DockerRootDir}}')"; do used="$(df -P "$p" | awk 'NR==2 {gsub(/%/,"",$5);print $5}')"; [[ "$used" =~ ^[0-9]+$ ]] && ((used<50)) || return 1; done; }
check_disk
old="$("${compose[@]}" ps -q "$unit")"; old_image=''
[[ -z "$old" ]] || old_image="$(docker inspect --format '{{.Config.Image}}' "$old")"
[[ -z "$old_image" || "$old_image" =~ ^ghcr\.io/allanvvz/akia-${service}@sha256:[0-9a-f]{64}$ ]] || { echo 'active image lacks immutable rollback digest' >&2; exit 2; }
activating=false
if [[ "$mode" == --activate || "$mode" == --activation-plan ]]; then
 activating=true
 [[ -n "$old" && "$image" == "$old_image" ]] || { echo 'activation requires the exact active digest' >&2; exit 2; }
fi
if [[ "$activating" == true || "$service" == gateway ]]; then
 f="${AKIA_NORTH_RUNTIME_FIXTURE_FILE:-}"
 [[ "$f" == /* && -s "$f" && ! -L "$f" && "$(stat -c %a "$f")" == 600 ]] || { echo 'private fixture required' >&2; exit 2; }
fi
printf 'AKIA_RELEASE_PLAN service=%s mode=%s current=%s candidate=%s\n' "$service" "$mode" "${old_image:-none}" "$image"
[[ "$mode" == --apply || "$mode" == --activate ]] || exit 0
state="$root/.deploy/akia/$service"; mkdir -p "$state"
exec 9>"$state/release.lock"; flock -n 9 || exit 1
[[ "$("${compose[@]}" ps -q "$unit")" == "$old" ]] || exit 1
work="$(mktemp -d "$state/release-XXXXXX")"; candidate="akia-$service-candidate-$$"
cutover=false; committed=false
wait_ready(){ local health; for _ in $(seq 1 18); do health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$1" 2>/dev/null || true)"; [[ "$health" == healthy ]] && return 0; [[ "$health" == unhealthy ]] && return 1; sleep 5; done; return 1; }
rollback(){
 if [[ -z "$old" ]]; then "${compose[@]}" rm -s -f "$unit" >/dev/null; return; fi
 "${compose[@]}" -f "$work/rollback.json" up -d --no-deps --force-recreate "$unit" >/dev/null
 wait_ready "$("${compose[@]}" ps -q "$unit")"
 echo "AKIA_RELEASE_ROLLBACK=healthy service=$service"
}
cleanup(){ local status=$?; trap - EXIT; if [[ "$cutover" == true && "$committed" != true ]]; then rollback || echo 'AKIA_RELEASE_ROLLBACK=failed' >&2; fi; docker rm -f "$candidate" >/dev/null 2>&1 || true; exit "$status"; }
trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM
# Private snapshots stay versioned, mode600. No secret appears in stdout/argv.
"${compose[@]}" config --format json | python3 -c 'import sys,json; c=json.load(sys.stdin); print(json.dumps({"services":{sys.argv[1]:c["services"][sys.argv[1]]}}))' "$unit" > "$work/desired-config.json"
if [[ -n "$old" ]]; then docker inspect "$old" > "$work/old-inspect.json"; fi
python3 - "$work" "$unit" "$image" "$activating" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1]);unit,image,activation=sys.argv[2:]
desired=json.loads((p/'desired-config.json').read_text())['services'][unit]['environment']
old=None
if (p/'old-inspect.json').exists():
 old=json.loads((p/'old-inspect.json').read_text())[0]['Config']
 previous=dict(e.split('=',1) for e in old['Env'])
flags=['NORTH_RUNTIME_COMMENTS_ENABLED','NORTH_RUNTIME_TASK_EDIT_ENABLED','NORTH_RUNTIME_CLIENT_EDIT_ENABLED','NORTH_RUNTIME_SETTINGS_ENABLED']
if activation=='true':
 desired=dict(previous)
 if unit=='operations-api':
  assert previous.get('OPERATIONS_NORTH_DELEGATION_ENABLED')=='true'
  assert previous.get('NORTH_SHARED_TRILHAS_APPROVED')=='true'
  assert all(previous.get(k)=='false' for k in flags), 'activation already performed or baseline not staged'
  desired.update({k:'true' for k in flags})
 else:
  assert previous.get('AKIA_NORTH_DELEGATION_ENABLED') in (None,'false','true')
  desired['AKIA_NORTH_DELEGATION_ENABLED']='true'
elif unit=='akia-gateway' and old:
 # A compatible gateway image keeps already activated North writes during CRM rollout.
 for key in ('AKIA_NORTH_DELEGATION_ENABLED','AKIA_CRM_ENABLED'):
  if previous.get(key)=='true': desired[key]='true'
elif unit=='operations-api':
 assert desired.get('OPERATIONS_NORTH_DELEGATION_ENABLED')=='true'
 assert desired.get('NORTH_SHARED_TRILHAS_APPROVED')=='true'
 if old:
  # Compatible image changes preserve actions already activated in production.
  for key in flags+['NORTH_RUNTIME_DRIVE_ENABLED','NORTH_RUNTIME_CLIENT_CREATE_ENABLED']:
   value=previous.get(key,'false')
   assert value in ('true','false'), 'invalid active capability flag'
   desired[key]=value
 else:
  assert all(desired.get(k)=='false' for k in flags), 'stage Ops before planned activation'
assert desired.get('OPERATIONS_CRON_ENABLED')!='true' or desired.get('OPERATIONS_CRON_DRY_RUN')=='true', 'canonical cron execution must remain disabled'
assert desired.get('NORTH_CANONICAL_EXECUTION_ENABLED')!='true'
def save(name,image,env):
 # Compose interpolates strings in JSON/YAML too: escape literal dollars.
 env={k:(v.replace('$','$$') if isinstance(v,str) else v) for k,v in env.items()}
 (p/name).write_text(json.dumps({'services':{unit:{'image':image,'environment':env}}}))
save('candidate.json',image,desired)
if old:
 # Null removes keys introduced only by the new env_file during rollback.
 save('rollback.json',old['Image'],{**dict.fromkeys(desired),**previous})
PY
chmod 600 "$work"/*
if [[ "$activating" == false ]]; then "${compose[@]}" pull "$unit" >/dev/null; fi
check_disk
"${compose[@]}" -f "$work/candidate.json" run --no-deps -d --name "$candidate" "$unit" >/dev/null
verify(){
 wait_ready "$1" || return 1
 if [[ "$service" == operations-api ]]; then
  docker exec "$1" node /app/verification/north-read-contract-smoke.mjs
  if [[ "$activating" == true ]] || docker exec "$1" env | grep -qx 'NORTH_RUNTIME_COMMENTS_ENABLED=true'; then
   docker exec -i "$1" node --input-type=module -e "$(cat ops/akia-bridge/north-activation-smoke.mjs)" < "$AKIA_NORTH_RUNTIME_FIXTURE_FILE"
  fi
 elif [[ "$service" == gateway ]]; then
  if docker exec "$1" env | grep -qx 'AKIA_CRM_ENABLED=true'; then
   docker exec "$1" python -I -c "$(cat ops/akia-bridge/north-gateway-crm-smoke.py)"
  fi
  if docker exec "$1" env | grep -qx 'AKIA_NORTH_DELEGATION_ENABLED=true'; then
   docker exec -i "$1" python -I -c "$(cat ops/akia-bridge/north-gateway-activation-smoke.py)" < "$AKIA_NORTH_RUNTIME_FIXTURE_FILE"
  fi
 fi
}
verify "$candidate"
check_disk
cutover=true
"${compose[@]}" -f "$work/candidate.json" up -d --no-deps --force-recreate "$unit" >/dev/null
verify "$("${compose[@]}" ps -q "$unit")"
cp "$work/candidate.json" "$state/current.json.tmp"; mv "$state/current.json.tmp" "$state/current.json"
[[ ! -f "$work/rollback.json" ]] || cp "$work/rollback.json" "$state/previous.json"
printf '%s\n' "$image" > "$state/current.image"
committed=true
printf 'AKIA_RELEASE_RESULT=healthy service=%s image=%s activation=%s\n' "$service" "$image" "$activating"
