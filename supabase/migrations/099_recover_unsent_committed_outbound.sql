-- Recover an outbound that already belongs to one committed turn but provably
-- never reached a provider attempt. This never re-runs retrieval or the model.

CREATE OR REPLACE FUNCTION public.recover_unsent_committed_outbound(
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
  v_proof_count integer;
BEGIN
  IF p_buffer_id IS NULL OR nullif(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'buffer id and recovery reason are required';
  END IF;

  SELECT * INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_buffer_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'outbound buffer not found';
  END IF;
  IF v_buffer.direction <> 'outbound' THEN
    RAISE EXCEPTION 'only outbound buffers may be recovered';
  END IF;
  IF v_buffer.status NOT IN ('waiting_human', 'dead_letter', 'failed') THEN
    RAISE EXCEPTION 'outbound status is not recoverable: %', v_buffer.status;
  END IF;
  IF v_buffer.provider_attempt_count <> 0
     OR v_buffer.external_message_id IS NOT NULL
     OR COALESCE(v_buffer.payload, '{}'::jsonb) ? 'provider_attempt_started_at' THEN
    RAISE EXCEPTION 'outbound may already have reached the provider';
  END IF;

  SELECT count(*) INTO v_proof_count
    FROM public.conversation_turn_proofs
   WHERE outbound_id = p_buffer_id::text
     AND COALESCE((proof_result->>'valid')::boolean, false);
  IF v_proof_count <> 1 THEN
    RAISE EXCEPTION 'outbound must belong to exactly one valid turn proof';
  END IF;

  UPDATE public.lead_buffer
     SET status = 'retry',
         available_at = now(),
         locked_at = NULL,
         locked_by = NULL,
         last_error = left('technical_recovery:' || btrim(p_reason), 1000),
         payload = COALESCE(payload, '{}'::jsonb)
           - 'provider_attempt_started_at' - 'provider_attempt_worker',
         updated_at = now()
   WHERE id = p_buffer_id;

  UPDATE public.messages
     SET status = 'pending',
         metadata = COALESCE(metadata, '{}'::jsonb)
           || jsonb_build_object('technical_recovery_buffer_id', p_buffer_id)
   WHERE channel_binding_id = v_buffer.channel_binding_id
     AND correlation_id = v_buffer.correlation_id
     AND direction = 'outbound'
     AND external_message_id IS NULL;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'conversation.unsent_committed_outbound_recovered',
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

REVOKE ALL ON FUNCTION public.recover_unsent_committed_outbound(uuid, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.recover_unsent_committed_outbound(uuid, text)
  TO service_role;

