-- record_whatsapp_safety_violation compared system_events.entity_id (text)
-- directly against p_binding_id (uuid) with no cast. The INSERT a few lines
-- above never failed because PostgreSQL's assignment-cast context allows
-- uuid -> text there; the SELECT ... WHERE comparison uses the default
-- operator-resolution context, which has no `text = uuid` operator.
--
-- This function is called at the top of every claim_whatsapp_buffer() cycle
-- (via quarantine_expired_whatsapp_attempts) whenever any lead_buffer row is
-- expired/stuck, so the bug aborted the *entire* claim transaction on every
-- worker poll -- halting outbound WhatsApp dispatch for every persona, not
-- just the one that produced the stuck row. Confirmed live in production on
-- 2026-08-01: a single stuck Aurora buffer row crash-looped
-- WhatsAppDispatchWorker for all personas until this was patched.

CREATE OR REPLACE FUNCTION public.record_whatsapp_safety_violation(
  p_binding_id uuid,
  p_lead_ref bigint,
  p_violation_key text,
  p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_persona_id uuid;
  v_count integer;
  v_paused boolean := false;
BEGIN
  SELECT persona_id
    INTO v_persona_id
    FROM public.workflow_bindings
   WHERE id = p_binding_id
   FOR UPDATE;

  IF v_persona_id IS NULL THEN
    RAISE EXCEPTION 'workflow binding not found';
  END IF;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  )
  VALUES (
    'whatsapp.safety_violation',
    'workflow_binding',
    p_binding_id,
    v_persona_id,
    jsonb_build_object(
      'violation_key', p_violation_key,
      'reason', p_reason,
      'lead_ref', p_lead_ref
    ),
    'error',
    'whatsapp.safety'
  );

  IF p_lead_ref IS NOT NULL THEN
    UPDATE public.leads
       SET ai_paused = true,
           updated_at = now()
     WHERE id = p_lead_ref
       AND persona_id = v_persona_id;

    UPDATE public.lead_buffer
       SET status = 'waiting_human',
           locked_at = NULL,
           locked_by = NULL,
           updated_at = now()
     WHERE lead_ref = p_lead_ref
       AND channel_binding_id = p_binding_id
       AND status IN (
         'received', 'buffered', 'processing', 'pending_send', 'retry'
       );
  END IF;

  SELECT count(DISTINCT payload->>'violation_key')
    INTO v_count
    FROM public.system_events
   WHERE event_type = 'whatsapp.safety_violation'
     AND entity_type = 'workflow_binding'
     AND entity_id = p_binding_id::text
     AND created_at >= now() - interval '5 minutes';

  IF v_count >= 3 THEN
    UPDATE public.workflow_bindings
       SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
             'safety_paused', true,
             'safety_paused_at', now(),
             'safety_reason', p_reason,
             'safety_violation_count', v_count
           ),
           connection_status = 'safety_paused',
           updated_at = now()
     WHERE id = p_binding_id;
    v_paused := true;
  END IF;

  RETURN jsonb_build_object(
    'binding_id', p_binding_id,
    'violation_count', v_count,
    'safety_paused', v_paused
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.record_whatsapp_safety_violation(
  uuid, bigint, text, text
) TO service_role;
