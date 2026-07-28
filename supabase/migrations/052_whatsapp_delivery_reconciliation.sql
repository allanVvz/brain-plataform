-- Some installations had lead_buffer before migration 050 was introduced.
-- CREATE TABLE IF NOT EXISTS cannot add the new column in that case, so make
-- the Meta wamid durable explicitly before enabling delivery callbacks.
alter table public.lead_buffer
  add column if not exists external_message_id text;

create index if not exists idx_lead_buffer_external_message_id
  on public.lead_buffer (external_message_id)
  where external_message_id is not null and external_message_id <> '';
