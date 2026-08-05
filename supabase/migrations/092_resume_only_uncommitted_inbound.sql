-- Resume AI without replaying turns that already produced a durable decision.
--
-- A handoff intentionally leaves the inbound lead_buffer row in
-- waiting_human.  The previous resume RPC requeued every such row, including
-- rows whose payload.conversation_commit was already completed.  Repeated
-- pause/resume cycles could therefore replay historical inbound turns beside
-- the genuinely pending one and make the agent answer twice from stale state.
--
-- The existing lead_buffer payload is the idempotency ledger; no new table is
-- needed.  Only never-claimed inbound turns are safe to retry automatically.

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
  WITH candidates AS (
    SELECT id
      FROM public.lead_buffer
     WHERE lead_ref = p_lead_ref
       AND direction = 'inbound'
       AND status = 'waiting_human'
       AND payload->'conversation_commit' IS NULL
     ORDER BY created_at, id
     FOR UPDATE SKIP LOCKED
  )
  UPDATE public.lead_buffer AS buffer
     SET status = 'retry',
         available_at = now(),
         locked_at = NULL,
         locked_by = NULL,
         payload = COALESCE(buffer.payload, '{}'::jsonb)
           - 'decision_attempt_started_at' - 'decision_attempt_worker'
           - 'provider_attempt_started_at' - 'provider_attempt_worker',
         updated_at = now()
    FROM candidates
   WHERE buffer.id = candidates.id;

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.requeue_waiting_human_whatsapp_buffer(bigint)
  TO service_role;
