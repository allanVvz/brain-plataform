#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.compose}"
cd "$ROOT_DIR"
COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
select pg_size_pretty(pg_database_size(current_database())) as database_size;
select 'personas' as entity, count(*) from personas
union all select 'users', count(*) from app_users
union all select 'nodes', count(*) from knowledge_nodes
union all select 'edges', count(*) from knowledge_edges
union all select 'rag_entries', count(*) from knowledge_rag_entries
union all select 'rag_chunks', count(*) from knowledge_rag_chunks
union all select 'assets', count(*) from assets
order by entity;
select count(*) as orphan_edges
from knowledge_edges e
left join knowledge_nodes s on s.id=e.source_node_id
left join knowledge_nodes t on t.id=e.target_node_id
where s.id is null or t.id is null;
SQL
docker system df
api_bind="$("${COMPOSE[@]}" port api 8080)"
curl --fail --show-error --silent "http://$api_bind/health/ready"
echo
