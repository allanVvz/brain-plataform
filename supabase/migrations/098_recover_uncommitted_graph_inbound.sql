-- Recover a technically failed inbound only when no durable decision or
-- outbound side effect exists. This is an operator recovery primitive, not a
-- commercial state transition.

CREATE OR REPLACE FUNCTION public.recover_uncommitted_graph_inbound(
  p_buffer_id uuid,
  p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_has_proof boolean;
  v_has_outbound boolean;
BEGIN
  IF p_buffer_id IS NULL OR nullif(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'buffer id and recovery reason are required';
  END IF;

  SELECT * INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_buffer_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'inbound buffer not found';
  END IF;
  IF v_buffer.direction <> 'inbound' THEN
    RAISE EXCEPTION 'only inbound buffers may be recovered';
  END IF;
  IF v_buffer.status NOT IN ('sent', 'dead_letter', 'waiting_human', 'failed') THEN
    RAISE EXCEPTION 'buffer status is not recoverable: %', v_buffer.status;
  END IF;
  IF COALESCE(v_buffer.payload, '{}'::jsonb)->'conversation_commit' IS NOT NULL THEN
    RAISE EXCEPTION 'inbound already has a conversation commit';
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.conversation_turn_proofs
     WHERE canonical_inbound_id = p_buffer_id::text
  ) INTO v_has_proof;
  IF v_has_proof THEN
    RAISE EXCEPTION 'inbound already has a turn proof';
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.lead_buffer
     WHERE direction = 'outbound'
       AND idempotency_key = 'ai:' || COALESCE(v_buffer.correlation_id, '')
  ) INTO v_has_outbound;
  IF v_has_outbound THEN
    RAISE EXCEPTION 'inbound already has an outbound side effect';
  END IF;

  UPDATE public.lead_buffer
     SET status = 'retry',
         available_at = now(),
         locked_at = NULL,
         locked_by = NULL,
         last_error = left('technical_recovery:' || btrim(p_reason), 1000),
         payload = COALESCE(payload, '{}'::jsonb)
           - 'decision_attempt_started_at' - 'decision_attempt_worker'
           - 'provider_attempt_started_at' - 'provider_attempt_worker',
         updated_at = now()
   WHERE id = p_buffer_id;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'conversation.uncommitted_inbound_recovered',
    'lead_buffer',
    p_buffer_id::text,
    v_buffer.persona_id,
    jsonb_build_object(
      'buffer_id', p_buffer_id,
      'lead_ref', v_buffer.lead_ref,
      'correlation_id', v_buffer.correlation_id,
      'previous_status', v_buffer.status,
      'reason', left(btrim(p_reason), 500)
    ),
    'warning',
    'graph_runtime.recovery'
  );

  RETURN jsonb_build_object(
    'ok', true,
    'buffer_id', p_buffer_id,
    'lead_ref', v_buffer.lead_ref,
    'previous_status', v_buffer.status,
    'status', 'retry'
  );
END;
$$;

REVOKE ALL ON FUNCTION public.recover_uncommitted_graph_inbound(uuid, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.recover_uncommitted_graph_inbound(uuid, text)
  TO service_role;

