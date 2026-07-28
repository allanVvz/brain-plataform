-- Canonical WhatsApp runtime. This is expand-first: legacy /process and
-- existing message rows remain valid while all new traffic uses lead_buffer.

alter table public.workflow_bindings
  add column if not exists metadata jsonb not null default '{}'::jsonb;

create unique index if not exists idx_workflow_bindings_active_whatsapp_phone
  on public.workflow_bindings (whatsapp_phone_number_id)
  where active = true and whatsapp_phone_number_id is not null and whatsapp_phone_number_id <> '';

create table if not exists public.lead_buffer (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references public.personas(id) on delete cascade,
  lead_ref bigint references public.leads(id) on delete set null,
  whatsapp_phone_number_id text not null,
  external_message_id text,
  direction text not null check (direction in ('inbound', 'outbound')),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'received' check (status in (
    'received','buffered','processing','pending_send','sent','delivered','read',
    'retry','dead_letter','waiting_human','ignored'
  )),
  batch_key text not null,
  available_at timestamptz not null default now(),
  locked_at timestamptz,
  locked_by text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 5 check (max_attempts > 0),
  last_error text,
  idempotency_key text not null,
  correlation_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (persona_id, whatsapp_phone_number_id, external_message_id),
  unique (idempotency_key)
);

create index if not exists idx_lead_buffer_available
  on public.lead_buffer (status, available_at, created_at);
create index if not exists idx_lead_buffer_lead
  on public.lead_buffer (lead_ref, created_at desc);

-- Compatibility columns make the canonical message contract queryable without
-- requiring a parallel messages table.
alter table public.messages add column if not exists external_message_id text;
alter table public.messages add column if not exists correlation_id text;
alter table public.messages add column if not exists whatsapp_phone_number_id text;
create unique index if not exists idx_messages_external_message_id
  on public.messages (external_message_id)
  where external_message_id is not null and external_message_id <> '';
