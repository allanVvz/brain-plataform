-- Brain AI auth and persona-level permissions.
-- Supabase CLI was not available in this workspace, so this migration was
-- created manually and should be applied with the existing deployment process.

create extension if not exists pgcrypto;

create table if not exists public.app_users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  username text unique,
  password_hash text not null,
  name text,
  role text not null default 'user' check (role in ('admin', 'user', 'viewer', 'operator')),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_login_at timestamptz
);

create index if not exists idx_app_users_role on public.app_users(role);
create index if not exists idx_app_users_active on public.app_users(is_active);

create table if not exists public.user_persona_access (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.app_users(id) on delete cascade,
  client_id text not null,
  persona_id uuid not null references public.personas(id) on delete cascade,
  persona_slug text,
  can_view boolean not null default true,
  can_edit boolean not null default false,
  can_manage boolean not null default false,
  created_at timestamptz not null default now(),
  unique (user_id, persona_id)
);

create index if not exists idx_user_persona_access_user on public.user_persona_access(user_id);
create index if not exists idx_user_persona_access_persona on public.user_persona_access(persona_id);
create index if not exists idx_user_persona_access_client on public.user_persona_access(client_id);

alter table public.app_users enable row level security;
alter table public.user_persona_access enable row level security;

drop policy if exists "app_users_service_only" on public.app_users;
create policy "app_users_service_only"
  on public.app_users
  for all
  using (false)
  with check (false);

drop policy if exists "user_persona_access_service_only" on public.user_persona_access;
create policy "user_persona_access_service_only"
  on public.user_persona_access
  for all
  using (false)
  with check (false);
