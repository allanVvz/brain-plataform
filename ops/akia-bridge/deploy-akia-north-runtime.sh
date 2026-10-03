#!/usr/bin/env bash
# VPS only. Migrations and env/route activation are separate reviewed operations.
set -Eeuo pipefail
umask 077
mode="${1:---dry-run}"
image="${2:-}"
[[ "$mode" == --dry-run || "$mode" == --apply ]] || exit 2
[[ "$image" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || { echo 'immutable GHCR image required' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
[[ -s .env.compose && -s docker-compose.yml ]] || exit 2
for file in "${AKIA_NORTH_RUNTIME_ENV_FILE:-}" "${AKIA_NORTH_RUNTIME_FIXTURE_FILE:-}"; do
  [[ "$file" == /* && -f "$file" && ! -L "$file" && -s "$file" ]] || { echo 'private runtime env/fixture files required' >&2; exit 2; }
  [[ "$(stat -c '%a' "$file")" == 600 ]] || { echo 'runtime env/fixture must be mode 600' >&2; exit 2; }
done
export AKIA_NORTH_RUNTIME_IMAGE="$image"
compose=(docker compose --env-file .env.compose -f docker-compose.yml -f infra/akia/north-runtime.compose.yml)
"${compose[@]}" config --quiet
docker_root="$(docker info --format '{{.DockerRootDir}}')"
check_disk(){
  local path used
  for path in "$root" "$docker_root"; do
    used="$(df -P "$path" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
    [[ "$used" =~ ^[0-9]+$ ]] && (( used < 50 )) || { echo 'North runtime disk gate requires <50%' >&2; return 1; }
  done
}
check_disk
old_container="$("${compose[@]}" ps -q north-runtime 2>/dev/null || true)"
old_image=''
state_dir="$root/.deploy/akia/north-runtime"
if [[ -n "$old_container" ]]; then
  old_image="$(docker inspect --format '{{.Config.Image}}' "$old_container")"
  [[ "$old_image" =~ @sha256:[0-9a-f]{64}$ && -s "$state_dir/current.env" && -s "$state_dir/current.image" && "$(cat "$state_dir/current.image")" == "$old_image" ]] || { echo 'existing runtime requires recorded rollback image/env' >&2; exit 2; }
fi
printf 'AKIA_RELEASE_PLAN service=north-runtime mode=%s candidate=%s current=%s\n' "$mode" "$image" "${old_image:-none}"
# Dry-run performs no pull, container, file or native-session mutation.
[[ "$mode" == --apply ]] || exit 0
mkdir -p "$state_dir"
exec 9>"$state_dir/release.lock"
flock -n 9 || { echo 'North runtime release already active' >&2; exit 1; }
# Recheck after the lock: the plan must still describe the active container.
[[ "$("${compose[@]}" ps -q north-runtime 2>/dev/null || true)" == "$old_container" ]] || { echo 'runtime changed during preflight' >&2; exit 1; }
release_env="$state_dir/candidate-$$.env"
cp "$AKIA_NORTH_RUNTIME_ENV_FILE" "$release_env"
export AKIA_NORTH_RUNTIME_ENV_FILE="$release_env"
candidate="akia-north-runtime-candidate-$$"
rollback_env="$state_dir/rollback-$$.env"
[[ -z "$old_image" ]] || cp "$state_dir/current.env" "$rollback_env"
cutover_started=false
committed=false
cleanup(){
  local status=$?
  trap - EXIT
  if [[ "$cutover_started" == true && "$committed" != true ]]; then
    rollback || echo 'AKIA_RELEASE_ROLLBACK=failed' >&2
  fi
  docker rm -f "$candidate" >/dev/null 2>&1 || true
  rm -f "$release_env" "$rollback_env"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${compose[@]}" pull north-runtime
check_disk
"${compose[@]}" run --no-deps -d -e NORTH_RUNTIME_COMMENT_EFFECTS_WORKER_ENABLED=false --name "$candidate" north-runtime >/dev/null
wait_ready(){
  local container="$1" status
  for _ in $(seq 1 18); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container" 2>/dev/null || true)"
    [[ "$status" == healthy ]] && return 0
    [[ "$status" == unhealthy ]] && return 1
    sleep 5
  done
  return 1
}
# This test issues sessions only for a private pre-authorized fixture. It never
# calls a business mutation, edits a profile/grant or sends an email.
smoke="$(cat <<'JS'
import fs from 'node:fs';
import {createHmac} from 'node:crypto';
import {createAdapterFromEnvironment} from '/app/dist/src/adapter.js';
const check=value=>{if(!value)throw Error('North native contract unavailable');};
let adapter,context,principal,stage='fixture';
try {
 const f=JSON.parse(fs.readFileSync(0,'utf8'));
 const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
 check(f.approved===true&&f.isolated===true&&f.agency_slug==='north'&&[f.brainId,f.northId,f.clientId,f.fixtureTaskId,f.foreignTaskId,f.foreignClientId].every(uuid)&&f.fixtureTaskId!==f.foreignTaskId&&typeof f.email==='string'&&typeof f.password==='string');
 const control='http://caddy:8090/control-plane';
 stage='brain_login';
 const login=await fetch(control+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:f.email,password:f.password}),redirect:'error',signal:AbortSignal.timeout(15000)});
 check(login.ok);stage='brain_cookie';const cookie=login.headers.getSetCookie().find(v=>v.startsWith('ai_brain_session='))?.split(';')[0];check(cookie);
 const token=cookie.slice('ai_brain_session='.length);check(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token));
 stage='brain_identity';const me=await fetch(control+'/auth/me',{headers:{cookie},redirect:'error',signal:AbortSignal.timeout(15000)});check(me.ok);const session=await me.json();
 check(session.user?.id===f.brainId&&session.user.role==='user'&&session.user.account_type==='agency'&&Array.isArray(session.personas)&&session.personas.length===0&&session.navigation?.surface==='operations'&&session.navigation?.home_url==='/north/admin');
 stage='brain_claims';const claims=JSON.parse(Buffer.from(token.split('.')[0],'base64url').toString());check(claims.sub===f.brainId&&Number.isSafeInteger(claims.exp)&&claims.exp*1000>Date.now());
 const fingerprint=createHmac('sha256',process.env.BRAIN_INTERNAL_AUTH_SECRET).update('north-delegation-v1\0'+token,'ascii').digest('hex');
 principal={userId:f.brainId,tokenFingerprint:fingerprint,brainExpiresAt:claims.exp*1000,expiresAt:Math.min(Date.now()+90000,claims.exp*1000)};
 stage='adapter_configuration';adapter=createAdapterFromEnvironment();
 stage='adapter_readiness';check(await adapter.ready());
 stage='delegation_context';context=await adapter.resolve(principal);
 stage='delegation_scope';
 const now=Math.floor(Date.now()/1000),attestation={iss:'brain-gateway',aud:'operations-api',sub:principal.userId,portal_scope:'north',iat:now,exp:Math.min(now+60,claims.exp),north_delegation:{token_fingerprint:principal.tokenFingerprint,brain_expires_at:claims.exp}};
 const encoded=Buffer.from(JSON.stringify(attestation)).toString('base64url');
 stage='portal_access';
 const portalAccess=await fetch(new URL('/api/operations/portal-access',process.env.NORTH_OPERATIONS_PRIVATE_URL),{headers:{'x-brain-principal':encoded,'x-brain-principal-signature':createHmac('sha256',process.env.BRAIN_INTERNAL_AUTH_SECRET).update(encoded,'ascii').digest('hex')},redirect:'error',signal:AbortSignal.timeout(10000)});
 const access=await portalAccess.json();check(portalAccess.ok&&access.portal_scope==='north'&&access.allowed===true);
 stage='delegation_scope';
 const operationsResponse=await fetch(new URL('/internal/v1/north-delegations/context',process.env.NORTH_OPERATIONS_PRIVATE_URL),{method:'POST',headers:{'Content-Type':'application/json','x-brain-principal':encoded,'x-brain-principal-signature':createHmac('sha256',process.env.BRAIN_INTERNAL_AUTH_SECRET).update(encoded,'ascii').digest('hex')},body:'{}',redirect:'error',signal:AbortSignal.timeout(10000)});
 const authorized=await operationsResponse.json(),expected=authorized.allowedClientIds;
 check(operationsResponse.ok&&authorized.brainUserId===f.brainId&&authorized.northProfileId===f.northId&&Array.isArray(expected)&&expected.length>0&&expected.every(uuid)&&new Set(expected).size===expected.length);
 check(context.northProfileId===f.northId&&context.agency==='north'&&context.northRole==='admin'&&context.allowedClientIds.has(f.clientId)&&!context.allowedClientIds.has(f.foreignClientId)&&JSON.stringify([...context.allowedClientIds].sort())===JSON.stringify([...expected].sort())&&await adapter.revalidate(context));
 if(process.env.NORTH_RUNTIME_COMMENTS_ENABLED==='true'){stage='comment_rpc_readiness';check(await adapter.ready('comments'));}
 stage='native_session';const delegated=await adapter.sessions.get(context);check(delegated.northProfileId===f.northId);
 stage='native_scope';const north=await adapter.scoped(context,delegated);
 stage='fixture_task';const task=await north.taskDto(f.fixtureTaskId);
 check(task.id===f.fixtureTaskId&&task.client_id===f.clientId);
 stage='foreign_task_denied';check(await north.task(f.foreignTaskId)===null);
 stage='delegation_revalidate';check(await adapter.revalidate(context));

} catch {
 // Only fixed stage labels leave this gate; never print caught provider errors,
 // auth response bodies, credentials, claims, cookies or fixture identifiers.
 console.error('NORTH_NATIVE_CONTRACT=failed stage='+stage);process.exitCode=1;
} finally {
 if(principal){
  if(adapter&&context)adapter.sessions.invalidate(context.brainUserId,context.northDelegationId);
  try {
   stage='delegation_revoke';
   const now=Math.floor(Date.now()/1000),claims={iss:'brain-gateway',aud:'operations-api',sub:principal.userId,portal_scope:'north',iat:now,exp:Math.min(now+60,Math.floor(principal.brainExpiresAt/1000)),north_delegation:{token_fingerprint:principal.tokenFingerprint,brain_expires_at:Math.floor(principal.brainExpiresAt/1000)}};
   const token=Buffer.from(JSON.stringify(claims)).toString('base64url'),signature=createHmac('sha256',process.env.BRAIN_INTERNAL_AUTH_SECRET).update(token,'ascii').digest('hex');
   const response=await fetch(new URL('/internal/v1/north-delegations/revoke',process.env.NORTH_OPERATIONS_PRIVATE_URL),{method:'POST',headers:{'Content-Type':'application/json','x-brain-principal':token,'x-brain-principal-signature':signature},body:'{}',redirect:'error',signal:AbortSignal.timeout(10000)});
   check(response.ok&&(await response.json()).revoked===true);
   stage='revocation_revalidate';if(adapter&&context)check(!await adapter.revalidate(context));
  }catch{console.error('NORTH_NATIVE_CONTRACT=revocation_failed stage='+stage);process.exitCode=1;}
 }
}
if(!process.exitCode)console.log('NORTH_NATIVE_CONTRACT=passed fixture_scope=agency business_mutations=0 revocation=verified');
JS
)"
verify(){ wait_ready "$1" && docker exec -i "$1" node --input-type=module -e "$smoke" < "$AKIA_NORTH_RUNTIME_FIXTURE_FILE"; }
verify "$candidate" || { echo 'candidate native contract failed; active runtime unchanged' >&2; exit 1; }
check_disk
rollback(){
  if [[ -z "$old_image" ]]; then
    "${compose[@]}" rm -s -f north-runtime >/dev/null || return 1
    rm -f "$state_dir/current.env" "$state_dir/current.image"
    echo 'AKIA_RELEASE_ROLLBACK=restored_absent'; return
  fi
  export AKIA_NORTH_RUNTIME_IMAGE="$old_image"
  export AKIA_NORTH_RUNTIME_ENV_FILE="$rollback_env"
  "${compose[@]}" up -d --no-deps --force-recreate north-runtime || return 1
  wait_ready "$("${compose[@]}" ps -q north-runtime)" || return 1
  cp "$rollback_env" "$state_dir/current.env" || return 1
  printf '%s\n' "$old_image" > "$state_dir/current.image" || return 1
  echo 'AKIA_RELEASE_ROLLBACK=healthy'
}
cutover_started=true
if ! "${compose[@]}" up -d --no-deps --force-recreate north-runtime || ! verify "$("${compose[@]}" ps -q north-runtime)"; then
  exit 1
fi
if [[ -n "$old_image" ]]; then
  cp "$state_dir/current.env" "$state_dir/previous.env"
  cp "$state_dir/current.image" "$state_dir/previous.image"
fi
cp "$release_env" "$state_dir/current.env.tmp"
mv "$state_dir/current.env.tmp" "$state_dir/current.env"
printf '%s\n' "$image" > "$state_dir/current.image.tmp"
mv "$state_dir/current.image.tmp" "$state_dir/current.image"
committed=true
printf 'AKIA_RELEASE_RESULT=healthy service=north-runtime image=%s\n' "$image"
