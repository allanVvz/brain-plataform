-- Brain AI Platform - Migration 025
-- User-managed integrations, schema hardening for knowledge mirrors and FAQ embed stability.

create table if not exists public.user_integration_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.app_users(id) on delete cascade,
  service text not null,
  enabled boolean not null default false,
  status text not null default 'never_validated',
  config_json jsonb not null default '{}'::jsonb,
  secret_ciphertext text,
  last_validated_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, service)
);

create index if not exists idx_user_integration_connections_user on public.user_integration_connections(user_id);
create index if not exists idx_user_integration_connections_service on public.user_integration_connections(service);

alter table public.user_integration_connections enable row level security;

drop policy if exists "user_integration_connections_service_only" on public.user_integration_connections;
create policy "user_integration_connections_service_only"
  on public.user_integration_connections
  for all
  using (false)
  with check (false);

alter table public.kb_entries
  add column if not exists embedding_status text;

create index if not exists idx_system_health_snapshot_at on public.system_health(snapshot_at desc);

create index if not exists idx_knowledge_nodes_source_persona_lookup
  on public.knowledge_nodes (source_table, source_id, persona_id, created_at desc);

create unique index if not exists idx_workflow_bindings_unique_name_persona
  on public.workflow_bindings (workflow_name, persona_id);
