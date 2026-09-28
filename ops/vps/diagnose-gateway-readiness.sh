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

compose=(docker compose --env-file .env.compose -f docker-compose.yml -f infra/microservices/docker-compose.blue-green.yml)
"${compose[@]}" exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|"' <<'SQL'
with scoped as (
  select l.*
  from public.leads l join public.personas p on p.id=l.persona_id
  where p.slug='tock-fatal'
), matched as (
  select l.id,
    exists (
      select 1 from unnest(array[
        l.telefone, l.lead_id, l.external_contact_id,
        l.metadata->'identities'->>'remote_jid',
        l.metadata->'identities'->>'remote_jid_alt'
      ]) as identity(value)
      where right(regexp_replace(coalesce(value,''),'[^0-9]','','g'),4)='8510'
    ) as phone_match,
    lower(coalesce(l.nome,'')) like '%allan%' as name_match
  from scoped l
)
select 'SCOPED_LEAD_IDENTITY_LOOKUP',
  count(*) filter (where phone_match),
  case when count(*) filter (where phone_match)=1
    then min(id) filter (where phone_match)::text else '' end,
  count(*) filter (where name_match),
  case when count(*) filter (where name_match)=1
    then min(id) filter (where name_match)::text else '' end
from matched;

with recursive pages(page_offset,data) as (
  select 0, public.list_actionable_message_queue_v1(
    array(select id from public.personas where slug='tock-fatal'),null,null,0,100)
  union all
  select (data->>'next_offset')::integer,
    public.list_actionable_message_queue_v1(
      array(select id from public.personas where slug='tock-fatal'),null,null,
      (data->>'next_offset')::integer,100)
  from pages where data->>'next_offset' is not null and page_offset<10000
), items as (
  select item from pages, lateral jsonb_array_elements(coalesce(data->'items','[]'::jsonb)) item
)
select 'QUEUE_PROJECTION_STATE',item->>'queue_state',item->>'origin',
  count(*),count(distinct item->>'lead_ref')
from items group by item->>'queue_state',item->>'origin'
order by item->>'queue_state',item->>'origin';

select 'AUDIENCE_GROUP',a.id,a.slug,a.name,a.source_type,count(m.lead_id)
from public.audiences a join public.personas p on p.id=a.persona_id
left join public.lead_audience_memberships m on m.audience_id=a.id
where p.slug='tock-fatal' and coalesce(a.metadata->>'kind','semantic_group')='semantic_group'
group by a.id,a.slug,a.name,a.source_type order by a.slug;

select 'IMPORT_STATUS',b.status,count(*),sum(b.valid_rows)
from public.lead_import_batches b join public.personas p on p.id=b.persona_id
where p.slug='tock-fatal' group by b.status order by b.status;

select 'CONSENT_STATUS',c.purpose,c.status,count(*),count(distinct c.lead_id)
from public.contact_consents c join public.personas p on p.id=c.persona_id
where p.slug='tock-fatal' and c.channel='whatsapp'
group by c.purpose,c.status order by c.purpose,c.status;

select 'TEMPLATE',t.id,t.provider,t.status,t.meta_approval_status,
  coalesce(t.meta_template_name,t.template_key)
from public.message_templates t join public.personas p on p.id=t.persona_id
where p.slug='tock-fatal' order by t.created_at desc;

select 'CAMPAIGN',c.id,c.status,c.campaign_kind,c.provider,c.audience_id
from public.campaigns c join public.personas p on p.id=c.persona_id
where p.slug='tock-fatal' order by c.created_at desc limit 50;

select 'ACTIVE_GRAPH',g.id,g.version,g.checksum,g.activated_at
from public.graph_publications g join public.personas p on p.id=g.persona_id
where p.slug='tock-fatal' and g.status='active';
SQL

bash ops/vps/rollout-microservices.sh status

echo "GATEWAY_READINESS_DIAGNOSTIC_END"
