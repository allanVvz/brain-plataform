-- resume-ai only ever flipped leads.ai_paused back to false; it never
-- touched lead_buffer. Every code path that moves an inbound row to
-- waiting_human (ai_paused check, automation_mode='human_only',
-- record_whatsapp_safety_violation, handoff_whatsapp_lead) is a dead end:
-- no other function anywhere ever transitions a row out of 'waiting_human'
-- back into a claimable status. claim_whatsapp_buffer only picks up
-- ('buffered', 'retry', 'pending_send') plus stale 'processing' — never
-- 'waiting_human'. So a customer message that arrives while the AI is
-- paused sits unanswered forever unless a human replies to it manually or
-- an engineer runs a one-off SQL fix. Confirmed live in production on
-- 2026-08-01 (Aurora Lead #23).
--
-- Only inbound rows are requeued: an outbound row already in
-- waiting_human represents a reply that was diverted before sending, and
-- resending stale, already-decided content would ignore anything that
-- happened in the conversation since. An inbound row is safe to
-- re-process because it re-runs decide/commit against the lead's current
-- state, not a stale decision.

CREATE OR REPLACE FUNCTION public.requeue_waiting_human_whatsapp_buffer(
  p_lead_ref bigint
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE public.lead_buffer
     SET status = 'retry',
         available_at = now(),
         locked_at = NULL,
         locked_by = NULL,
         updated_at = now()
   WHERE lead_ref = p_lead_ref
     AND direction = 'inbound'
     AND status = 'waiting_human';
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.requeue_waiting_human_whatsapp_buffer(bigint)
  TO service_role;
