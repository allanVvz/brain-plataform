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
