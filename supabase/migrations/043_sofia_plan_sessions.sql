create table if not exists public.sofia_plan_sessions (
  session_id text primary key,
  persona_slug text not null,
  active_persona_slug text,
  plan_json jsonb not null default '{}'::jsonb,
  last_referenced_node jsonb not null default '{}'::jsonb,
  recent_turns jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_sofia_plan_sessions_persona_slug
  on public.sofia_plan_sessions(persona_slug);

create index if not exists idx_sofia_plan_sessions_updated_at
  on public.sofia_plan_sessions(updated_at desc);

create or replace function public.touch_sofia_plan_sessions_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_touch_sofia_plan_sessions_updated_at on public.sofia_plan_sessions;
create trigger trg_touch_sofia_plan_sessions_updated_at
before update on public.sofia_plan_sessions
for each row execute function public.touch_sofia_plan_sessions_updated_at();
