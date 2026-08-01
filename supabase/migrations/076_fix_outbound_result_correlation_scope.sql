-- complete_whatsapp_outbound_result's messages UPDATE was scoped only by
-- (channel_binding_id, correlation_id) — not by direction, not by row id.
-- That was safe as long as no two messages rows for the same binding ever
-- shared a correlation_id. They did: conversation_runtime.commit() reused
-- the *inbound* message's correlation_id for the *outbound* reply it
-- generated (fixed separately in api/services/conversation_runtime.py).
-- With that collision, this UPDATE matched both the inbound and outbound
-- rows and tried to force the same external_message_id (the provider's
-- wamid) onto both — tripping idx_messages_channel_external_unique and
-- aborting the whole completion, even though the provider had already
-- delivered the message. Confirmed live 2026-08-01 during the Baita<->
-- Aurora production E2E test (Lead #23, binding
-- c18834ee-566c-410c-9daa-34eff8a3ac56).
--
-- This migration adds `direction = 'outbound'` to both UPDATE statements
-- as defense in depth: the Python-side root cause is fixed too, but this
-- function should never be able to corrupt an inbound row's
-- external_message_id regardless of what correlation_id a caller passes.

CREATE OR REPLACE FUNCTION public.complete_whatsapp_outbound_result(
  p_buffer_id uuid,
  p_binding_id uuid,
  p_correlation_id text,
  p_external_message_id text,
  p_success boolean,
  p_error text DEFAULT NULL::text,
  p_execution_id text DEFAULT NULL::text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
  v_conflict boolean := false;
BEGIN
  SELECT *
    INTO v_row
    FROM public.lead_buffer
   WHERE id = p_buffer_id
     AND channel_binding_id = p_binding_id
     AND correlation_id = p_correlation_id
   FOR UPDATE;

  IF v_row.id IS NULL THEN
    RAISE EXCEPTION 'outbound result does not match buffer binding/correlation';
  END IF;

  IF p_external_message_id IS NOT NULL
     AND v_row.external_message_id IS NOT NULL
     AND p_external_message_id <> v_row.external_message_id THEN
    v_conflict := true;
    UPDATE public.lead_buffer
       SET status = 'waiting_human',
           last_error = 'conflicting provider external id',
           locked_at = NULL,
           locked_by = NULL,
           updated_at = now()
     WHERE id = v_row.id;
    PERFORM public.record_whatsapp_safety_violation(
      p_binding_id,
      v_row.lead_ref,
      'external-id-conflict:' || v_row.id::text,
      'conflicting provider external id'
    );
  ELSIF p_success AND v_row.status IN ('sent', 'delivered', 'read') THEN
    INSERT INTO public.system_events (
      event_type, entity_type, entity_id, persona_id, payload, level, source
    )
    VALUES (
      'whatsapp.outbound_callback_ignored',
      'workflow_binding',
      p_binding_id,
      v_row.persona_id,
      jsonb_build_object(
        'buffer_id', p_buffer_id,
        'correlation_id', p_correlation_id,
        'execution_id', p_execution_id,
        'reason', 'duplicate success'
      ),
      'info',
      'whatsapp.outbound'
    );
  ELSIF NOT p_success
        AND v_row.status IN (
          'sent', 'delivered', 'read', 'waiting_human', 'failed'
        ) THEN
    INSERT INTO public.system_events (
      event_type, entity_type, entity_id, persona_id, payload, level, source
    )
    VALUES (
      'whatsapp.outbound_callback_ignored',
      'workflow_binding',
      p_binding_id,
      v_row.persona_id,
      jsonb_build_object(
        'buffer_id', p_buffer_id,
        'correlation_id', p_correlation_id,
        'execution_id', p_execution_id,
        'reason', 'late or duplicate failure'
      ),
      'info',
      'whatsapp.outbound'
    );
  ELSIF p_success THEN
    UPDATE public.lead_buffer
       SET status = 'sent',
           external_message_id = COALESCE(
             p_external_message_id, external_message_id
           ),
           last_error = NULL,
           locked_at = NULL,
           locked_by = NULL,
           payload = COALESCE(payload, '{}'::jsonb)
             || jsonb_build_object(
                  'provider_execution_id', p_execution_id
                ),
           updated_at = now()
     WHERE id = v_row.id;
    UPDATE public.messages
       SET status = 'sent',
           external_message_id = COALESCE(
             p_external_message_id, external_message_id
           )
     WHERE channel_binding_id = p_binding_id
       AND correlation_id = p_correlation_id
       AND direction = 'outbound';
  ELSE
    UPDATE public.lead_buffer
       SET status = 'waiting_human',
           last_error = LEFT(COALESCE(p_error, 'ambiguous outbound failure'), 1000),
           locked_at = NULL,
           locked_by = NULL,
           payload = COALESCE(payload, '{}'::jsonb)
             || jsonb_build_object(
                  'provider_execution_id', p_execution_id
                ),
           updated_at = now()
     WHERE id = v_row.id;
    UPDATE public.messages
       SET status = 'waiting_human'
     WHERE channel_binding_id = p_binding_id
       AND correlation_id = p_correlation_id
       AND direction = 'outbound'
       AND status NOT IN ('sent', 'delivered', 'read');
  END IF;

  RETURN jsonb_build_object(
    'ok', NOT v_conflict,
    'buffer_id', v_row.id,
    'message_id', (
      SELECT sender_id
        FROM public.messages
       WHERE channel_binding_id = p_binding_id
         AND correlation_id = p_correlation_id
         AND direction = 'outbound'
       ORDER BY created_at
       LIMIT 1
    ),
    'status', (
      SELECT status FROM public.lead_buffer WHERE id = v_row.id
    ),
    'deduplicated', (
      v_conflict
      OR (p_success AND v_row.status IN ('sent', 'delivered', 'read'))
      OR (
        NOT p_success
        AND v_row.status IN (
          'sent', 'delivered', 'read', 'waiting_human', 'failed'
        )
      )
    )
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.complete_whatsapp_outbound_result(
  uuid, uuid, text, text, boolean, text, text
) TO service_role;
