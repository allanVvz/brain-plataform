-- handoff_whatsapp_lead / handoff_whatsapp_lead_state sweep every
-- lead_buffer row for a lead into waiting_human, regardless of direction.
-- Intent is "stop auto-processing new incoming customer messages" — but
-- an outbound row in 'pending_send' is a reply the engine already decided
-- and queued for delivery. When multiple backlogged inbound messages for
-- the same lead are reprocessed in one worker burst (e.g. right after
-- resume-ai's requeue) and a later one triggers handoff, its sweep was
-- catching the *earlier* messages' own just-created outbound replies
-- before the dispatch worker ever attempted to send them — silently
-- discarding an already-decided reply with zero attempts, zero error, and
-- nothing in the WhatsApp send log. The platform showed the drafted text;
-- the real customer never received anything.
--
-- Confirmed live 2026-08-01 during the Baita<->Aurora production E2E test
-- (Lead #23, Aurora binding c18834ee-566c-410c-9daa-34eff8a3ac56): 3
-- reprocessed backlog messages each produced a correct reply, but all 3
-- outbound rows ended up in waiting_human with attempt_count=0 — never
-- dispatched.
--
-- Fix: scope both sweeps to direction = 'inbound', matching the same
-- direction-scoping already applied to requeue_waiting_human_whatsapp_
-- buffer (migration 075) and record_whatsapp_safety_violation's lead_buffer
-- update.

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead(p_lead_ref bigint)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
begin
  update public.leads
  set ai_paused = true, updated_at = now()
  where id = p_lead_ref;

  update public.lead_buffer
  set status = 'waiting_human', locked_at = null, locked_by = null, updated_at = now()
  where lead_ref = p_lead_ref
    and direction = 'inbound'
    and status in ('received', 'buffered', 'processing', 'pending_send', 'retry');
end;
$$;

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead_state(p_lead_ref bigint, p_metadata jsonb, p_stage text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
BEGIN
  UPDATE public.leads
     SET ai_paused = true,
         metadata = COALESCE(p_metadata, metadata, '{}'::jsonb),
         stage = COALESCE(NULLIF(p_stage, ''), stage),
         updated_at = now()
   WHERE id = p_lead_ref;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'lead not found: %', p_lead_ref;
  END IF;

  UPDATE public.lead_buffer
     SET status = 'waiting_human',
         locked_at = null,
         locked_by = null,
         updated_at = now()
   WHERE lead_ref = p_lead_ref
     AND direction = 'inbound'
     AND status IN (
       'received', 'buffered', 'processing', 'pending_send', 'retry'
     );
END;
$$;

GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead(bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead_state(bigint, jsonb, text) TO service_role;
