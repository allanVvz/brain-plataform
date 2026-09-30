#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${AUDIT_ROOT:-/opt/brain-ai}"
cd "$ROOT_DIR"

container_id="$(docker ps -aq \
  --filter label=com.docker.compose.project=brain-ai \
  --filter label=com.docker.compose.service=gateway-blue | head -n 1)"

if [[ -z "$container_id" ]]; then
  echo "gateway-blue container not found" >&2
  exit 1
fi

echo "GATEWAY_READINESS_DIAGNOSTIC_BEGIN"
echo "container_id=${container_id:0:12}"
docker ps --filter "id=$container_id" \
  --format 'container={{.Names}} image={{.Image}} status={{.Status}}'
docker inspect --format 'health={{json .State.Health}}' "$container_id"

for state_file in \
  .deploy/microservices/slots.json \
  .deploy/caddy/public-upstream.caddy \
  .deploy/caddy/internal-upstreams.caddy
do
  echo "STATE_FILE_BEGIN path=$state_file"
  if [[ -f "$state_file" ]]; then
    sed -n '1,240p' "$state_file"
  else
    echo "missing"
  fi
  echo "STATE_FILE_END path=$state_file"
done

probe_from_gateway() {
  local label="$1"
  local url="$2"
  echo "PROBE_BEGIN target=$label"
  docker exec "$container_id" python -c '
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read(4096).decode("utf-8", errors="replace")
        print(f"status={response.status}")
        print(body)
except urllib.error.HTTPError as exc:
    body = exc.read(4096).decode("utf-8", errors="replace")
    print(f"status={exc.code}")
    print(body)
except Exception as exc:
    print(f"error={type(exc).__name__}: {exc}")
' "$url"
  echo "PROBE_END target=$label"
}

probe_from_gateway gateway-live http://127.0.0.1:8080/health
probe_from_gateway gateway-ready http://127.0.0.1:8080/health/ready
probe_from_gateway control-plane http://caddy:8090/control-plane/health/ready
probe_from_gateway conversation-runtime http://caddy:8090/conversation-runtime/health/ready
probe_from_gateway transport http://caddy:8090/transport/health/ready

echo "GATEWAY_READINESS_DIAGNOSTIC_END"

# Read-only AKIA bootstrap inventory. Only public fingerprints, field names,
# account/client identity IDs and service metadata are printed.
python3 - <<'PY'
import glob, json, os, subprocess
from pathlib import Path
print('AKIA_BOOTSTRAP_AUDIT_BEGIN')
for path in glob.glob('/etc/ssh/ssh_host_*_key.pub'):
    result = subprocess.run(['ssh-keygen','-lf',path],capture_output=True,text=True,check=True)
    print('AKIA_SSH_HOST_KEY=' + result.stdout.strip())
subprocess.run(['df','-P',os.getcwd(),'/var/lib/docker'],check=True)
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
database=None
for row in rows:
    labels=row['Config'].get('Labels') or {}
    service=labels.get('com.docker.compose.service','')
    if labels.get('com.docker.compose.project') != 'brain-ai':
        continue
    if service == 'db': database=row
    if service == 'db' or service == 'caddy' or service.startswith(('gateway-','control-plane-')):
        print('AKIA_SERVICE=' + json.dumps({'name':row['Name'],'service':service,'image':row['Config']['Image'],
            'networks':list(row['NetworkSettings']['Networks']),
            'env_keys':[value.split('=',1)[0] for value in row['Config']['Env']]}))
for folder in ['secrets','.deploy/microservices']:
    root=Path(folder)
    if root.is_dir():
        for path in root.rglob('*.env'):
            print('AKIA_ENV_FILE=' + str(path))
if database:
    values=dict(value.split('=',1) for value in database['Config']['Env'] if '=' in value)
    command=['docker','exec',database['Id'],'psql','-U',values.get('POSTGRES_USER','postgres'),
             '-d',values.get('POSTGRES_DB','postgres'),'-X','-A','-t','-v','ON_ERROR_STOP=1','-c']
    queries=[
        "SELECT json_build_object('schema',to_regnamespace('operations')::text,'role_exists',EXISTS(SELECT 1 FROM pg_roles WHERE rolname='brain_control_plane'))",
        "SELECT json_build_object('id',u.id,'email',u.email,'role',to_jsonb(u)->>'role','account_type',to_jsonb(u)->>'account_type','is_active',to_jsonb(u)->>'is_active') FROM public.app_users u WHERE lower(u.email) IN ('allan@north.com','allanulisses@hotmail.com','allanulisses@hotmai.com')",
        "SELECT json_build_object('id',p.id,'slug',to_jsonb(p)->>'slug','name',to_jsonb(p)->>'name') FROM public.personas p WHERE lower(coalesce(to_jsonb(p)->>'slug','') || ' ' || coalesce(to_jsonb(p)->>'name','')) ~ '(utzig|aurora|tock|lupas)' ORDER BY p.id",
    ]
    for query in queries:
        result=subprocess.run(command+['BEGIN READ ONLY; '+query+'; ROLLBACK;'],capture_output=True,text=True)
        if result.returncode: print('AKIA_DB_AUDIT_ERROR=readonly_query_failed')
        else:
            for line in result.stdout.splitlines():
                if line.startswith('{'): print('AKIA_DB_IDENTITY=' + line)
print('AKIA_BOOTSTRAP_AUDIT_END')
PY
