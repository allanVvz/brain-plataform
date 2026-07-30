-- Atomic callback claim on the existing inbound inbox row.
-- No new table is required: the inbound lead_buffer row is already the
-- durable idempotency lock for the decision associated with that message.

CREATE OR REPLACE FUNCTION public.claim_conversation_commit(
  p_inbound_buffer_id uuid,
  p_binding_id uuid,
  p_lead_ref bigint,
  p_correlation_id text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_commit jsonb;
  v_state text;
BEGIN
  IF p_inbound_buffer_id IS NULL
     OR p_binding_id IS NULL
     OR p_lead_ref IS NULL
     OR NULLIF(p_correlation_id, '') IS NULL THEN
    RAISE EXCEPTION 'complete conversation commit identity is required';
  END IF;

  SELECT *
    INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_inbound_buffer_id
     AND channel_binding_id = p_binding_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'inbound buffer not found for binding';
  END IF;
  IF v_buffer.direction <> 'inbound' THEN
    RAISE EXCEPTION 'conversation commit requires an inbound buffer';
  END IF;
  IF v_buffer.lead_ref IS DISTINCT FROM p_lead_ref THEN
    RAISE EXCEPTION 'inbound buffer does not match lead';
  END IF;
  IF v_buffer.correlation_id IS NOT NULL
     AND v_buffer.correlation_id <> p_correlation_id THEN
    RAISE EXCEPTION 'inbound buffer correlation mismatch';
  END IF;

  v_commit := COALESCE(v_buffer.payload, '{}'::jsonb)->'conversation_commit';
  IF v_commit IS NOT NULL THEN
    IF v_commit->>'correlation_id' IS DISTINCT FROM p_correlation_id THEN
      RAISE EXCEPTION 'conversation commit correlation mismatch';
    END IF;
    v_state := COALESCE(NULLIF(v_commit->>'status', ''), 'processing');
    RETURN jsonb_build_object(
      'state', v_state,
      'result', v_commit->'result'
    );
  END IF;

  UPDATE public.lead_buffer
     SET payload = jsonb_set(
           COALESCE(payload, '{}'::jsonb),
           '{conversation_commit}',
           jsonb_build_object(
             'status', 'processing',
             'correlation_id', p_correlation_id,
             'claimed_at', now()
           ),
           true
         ),
         updated_at = now()
   WHERE id = v_buffer.id;

  RETURN jsonb_build_object('state', 'claimed');
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_conversation_commit(
  uuid, uuid, bigint, text
) TO service_role;


CREATE OR REPLACE FUNCTION public.complete_conversation_commit(
  p_inbound_buffer_id uuid,
  p_binding_id uuid,
  p_lead_ref bigint,
  p_correlation_id text,
  p_result jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_commit jsonb;
BEGIN
  SELECT *
    INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_inbound_buffer_id
     AND channel_binding_id = p_binding_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'inbound buffer not found for binding';
  END IF;
  IF v_buffer.direction <> 'inbound'
     OR v_buffer.lead_ref IS DISTINCT FROM p_lead_ref THEN
    RAISE EXCEPTION 'inbound buffer does not match conversation commit';
  END IF;

  v_commit := COALESCE(v_buffer.payload, '{}'::jsonb)->'conversation_commit';
  IF v_commit IS NULL
     OR v_commit->>'correlation_id' IS DISTINCT FROM p_correlation_id THEN
    RAISE EXCEPTION 'conversation commit was not claimed';
  END IF;

  IF v_commit->>'status' = 'completed' THEN
    RETURN COALESCE(v_commit->'result', '{}'::jsonb);
  END IF;
  IF v_commit->>'status' <> 'processing' THEN
    RAISE EXCEPTION 'conversation commit is not processing';
  END IF;

  UPDATE public.lead_buffer
     SET payload = jsonb_set(
           COALESCE(payload, '{}'::jsonb),
           '{conversation_commit}',
           jsonb_build_object(
             'status', 'completed',
             'correlation_id', p_correlation_id,
             'completed_at', now(),
             'result', COALESCE(p_result, '{}'::jsonb)
           ),
           true
         ),
         updated_at = now()
   WHERE id = v_buffer.id;

  RETURN COALESCE(p_result, '{}'::jsonb);
END;
$$;

GRANT EXECUTE ON FUNCTION public.complete_conversation_commit(
  uuid, uuid, bigint, text, jsonb
) TO service_role;
