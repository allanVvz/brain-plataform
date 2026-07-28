-- Leasing is database-owned so concurrent workers cannot process the same
-- WhatsApp event.  No messages are deleted: exhausted work stays auditable in
-- lead_buffer as dead_letter.
create or replace function public.claim_whatsapp_buffer(
  p_worker text,
  p_limit integer default 20,
  p_lease_seconds integer default 60
)
returns setof public.lead_buffer
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidates as (
    select id
    from public.lead_buffer
    where (
      status in ('buffered', 'retry', 'pending_send')
      and available_at <= now()
    ) or (
      status = 'processing'
      and locked_at < now() - make_interval(secs => greatest(p_lease_seconds, 1))
    )
    order by available_at, created_at
    for update skip locked
    limit greatest(p_limit, 1)
  )
  update public.lead_buffer b
  set status = 'processing',
      locked_at = now(),
      locked_by = p_worker,
      attempt_count = b.attempt_count + 1,
      updated_at = now()
  from candidates
  where b.id = candidates.id
  returning b.*;
end;
$$;

grant execute on function public.claim_whatsapp_buffer(text, integer, integer)
  to service_role;

-- A handoff cannot leave a window where the dashboard sees AI paused while a
-- leased/retryable message can still be sent automatically.
create or replace function public.handoff_whatsapp_lead(p_lead_ref bigint)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.leads
  set ai_paused = true, updated_at = now()
  where id = p_lead_ref;

  update public.lead_buffer
  set status = 'waiting_human', locked_at = null, locked_by = null, updated_at = now()
  where lead_ref = p_lead_ref
    and status in ('received', 'buffered', 'processing', 'pending_send', 'retry');
end;
$$;

grant execute on function public.handoff_whatsapp_lead(bigint) to service_role;
