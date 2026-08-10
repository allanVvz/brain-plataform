-- Fix 109_stagger_requeue_on_resume.sql: FOR UPDATE is not allowed in the
-- same SELECT as a window function (row_number() OVER (...)). Postgres
-- rejected the whole statement with "FOR UPDATE is not allowed with window
-- functions" -- confirmed live 2026-08-10 immediately after 109 shipped:
-- every resume_lead() call logged "resume_lead requeue failed" and the
-- backlog stayed in waiting_human even though handoff_level was cleared.
--
-- Splits the locking (FOR UPDATE SKIP LOCKED, no window function) into its
-- own CTE, then computes row_number() over the already-locked row set in a
-- second CTE. Same candidate filter and stagger behavior as 109 intended.

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
  WITH locked AS (
    SELECT id, created_at
      FROM public.lead_buffer
     WHERE lead_ref = p_lead_ref
       AND direction = 'inbound'
       AND status = 'waiting_human'
       AND payload->'conversation_commit' IS NULL
     ORDER BY created_at, id
     FOR UPDATE SKIP LOCKED
  ),
  candidates AS (
    SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
      FROM locked
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
