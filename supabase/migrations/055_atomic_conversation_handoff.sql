-- Persist the final cart/stage and pause AI in the same transaction. Pending
-- work is quarantined before the approved final summary is enqueued.

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead_state(
  p_lead_ref bigint,
  p_metadata jsonb,
  p_stage text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
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
     AND status IN (
       'received', 'buffered', 'processing', 'pending_send', 'retry'
     );
END;
$$;

GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead_state(bigint, jsonb, text)
  TO service_role;
