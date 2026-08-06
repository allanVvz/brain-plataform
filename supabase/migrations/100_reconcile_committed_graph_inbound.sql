-- Reconcile an inbound whose n8n HTTP response was lost or malformed after
-- the GraphRAG transaction had already committed exactly one valid proof and
-- exactly one durable outbound. This function never re-runs the model and
-- never sends a message.

CREATE OR REPLACE FUNCTION public.reconcile_committed_graph_inbound(
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
  v_outbound public.lead_buffer%ROWTYPE;
  v_proof_count integer;
  v_valid_proof_count integer;
  v_outbound_id text;
  v_message_count integer;
BEGIN
  IF p_buffer_id IS NULL OR nullif(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'buffer id and reconciliation reason are required';
  END IF;

  SELECT * INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_buffer_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'inbound buffer not found';
  END IF;
  IF v_buffer.direction <> 'inbound' THEN
    RAISE EXCEPTION 'only inbound buffers may be reconciled';
  END IF;
  IF v_buffer.status = 'sent' THEN
    RETURN jsonb_build_object(
      'ok', true,
      'reconciled', false,
      'reason', 'already_reconciled',
      'buffer_id', p_buffer_id,
      'status', v_buffer.status
    );
  END IF;
  IF v_buffer.status NOT IN ('processing', 'retry', 'failed', 'waiting_human') THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reconciled', false,
      'reason', 'inbound_status_not_reconcilable',
      'buffer_id', p_buffer_id,
      'status', v_buffer.status
    );
  END IF;
  IF COALESCE(v_buffer.payload, '{}'::jsonb)
       #>> '{conversation_commit,status}' <> 'completed' THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reconciled', false,
      'reason', 'conversation_commit_not_completed',
      'buffer_id', p_buffer_id
    );
  END IF;

  SELECT count(*),
         count(*) FILTER (
           WHERE COALESCE((proof_result->>'valid')::boolean, false)
         ),
         max(outbound_id)
    INTO v_proof_count, v_valid_proof_count, v_outbound_id
    FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id = p_buffer_id::text;

  IF v_proof_count <> 1 OR v_valid_proof_count <> 1
     OR nullif(v_outbound_id, '') IS NULL THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reconciled', false,
      'reason', 'turn_does_not_have_one_valid_proof_and_outbound',
      'buffer_id', p_buffer_id,
      'proof_count', v_proof_count,
      'valid_proof_count', v_valid_proof_count
    );
  END IF;

  SELECT * INTO v_outbound
    FROM public.lead_buffer
   WHERE id::text = v_outbound_id
   FOR UPDATE;

  IF v_outbound.id IS NULL
     OR v_outbound.direction <> 'outbound'
     OR v_outbound.persona_id <> v_buffer.persona_id
     OR v_outbound.lead_ref IS DISTINCT FROM v_buffer.lead_ref
     OR v_outbound.status NOT IN (
       'pending_send', 'processing', 'sent', 'delivered', 'read'
     ) THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reconciled', false,
      'reason', 'durable_outbound_not_dispatchable_or_terminal',
      'buffer_id', p_buffer_id,
      'outbound_id', v_outbound_id
    );
  END IF;

  SELECT count(*) INTO v_message_count
    FROM public.messages
   WHERE direction = 'outbound'
     AND channel_binding_id = v_outbound.channel_binding_id
     AND correlation_id = v_outbound.correlation_id;
  IF v_message_count <> 1 THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reconciled', false,
      'reason', 'outbound_message_is_not_unique',
      'buffer_id', p_buffer_id,
      'outbound_id', v_outbound_id,
      'message_count', v_message_count
    );
  END IF;

  UPDATE public.lead_buffer
     SET status = 'sent',
         locked_at = NULL,
         locked_by = NULL,
         last_error = NULL,
         payload = COALESCE(payload, '{}'::jsonb)
           || jsonb_build_object(
             'technical_reconciliation', jsonb_build_object(
               'reason', left(btrim(p_reason), 500),
               'reconciled_at', now(),
               'proof_count', v_proof_count,
               'outbound_id', v_outbound_id
             )
           ),
         updated_at = now()
   WHERE id = p_buffer_id;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'conversation.committed_inbound_reconciled',
    'lead_buffer',
    p_buffer_id::text,
    v_buffer.persona_id,
    jsonb_build_object(
      'buffer_id', p_buffer_id,
      'lead_ref', v_buffer.lead_ref,
      'correlation_id', v_buffer.correlation_id,
      'previous_status', v_buffer.status,
      'outbound_id', v_outbound_id,
      'reason', left(btrim(p_reason), 500)
    ),
    'warning',
    'graph_runtime.reconciliation'
  );

  RETURN jsonb_build_object(
    'ok', true,
    'reconciled', true,
    'buffer_id', p_buffer_id,
    'lead_ref', v_buffer.lead_ref,
    'previous_status', v_buffer.status,
    'status', 'sent',
    'outbound_id', v_outbound_id
  );
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_committed_graph_inbound(uuid, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_committed_graph_inbound(uuid, text)
  TO service_role;

