-- Stagger the backlog requeue on resume instead of releasing every row at once.
--
-- requeue_waiting_human_whatsapp_buffer set available_at = now() for every
-- candidate row in one UPDATE, so a lead resumed after a long pause with N
-- backlogged inbound messages had all N claimed by the dispatch worker in
-- the same cycle and dispatched back-to-back in under two seconds. Confirmed
-- live 2026-08-10: ~12 backlogged messages for one lead were all claimed and
-- processed within ~1.5s of a manual resume. Spacing available_at per row
-- gives the worker's normal 2s poll interval room to breathe between turns
-- for the same lead, without changing which rows are eligible or losing the
-- existing idempotency-ledger filter from migration 092.

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
    SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
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
         available_at = now() + ((candidates.rn - 1) * interval '4 seconds'),
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
