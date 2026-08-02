-- record_whatsapp_safety_violation already inserts one whatsapp.safety_violation
-- (level='error') per call, but the moment a binding actually crosses the
-- 3-violations-in-5-minutes threshold and gets safety_paused=true — which
-- stops ALL automated replies on that channel, not just one message — was
-- never logged as its own event. Every Python call site that receives this
-- function's `safety_paused` return value discards it
-- (api/workers/whatsapp_dispatch_worker.py, api/services/conversation_runtime.py),
-- so the only trace was a passive status label buried in
-- Settings > Mensageria for that one binding. Add a second, distinct,
-- unmissable event at the moment the pause actually takes effect, so it
-- shows up in the Logs > Auditoria tab like any other operational incident.

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
           payload = COALESCE(payload, '{}'::jsonb)
             - 'decision_attempt_started_at' - 'decision_attempt_worker'
             - 'provider_attempt_started_at' - 'provider_attempt_worker',
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

    INSERT INTO public.system_events (
      event_type, entity_type, entity_id, persona_id, payload, level, source
    )
    VALUES (
      'whatsapp.binding_safety_paused',
      'workflow_binding',
      p_binding_id,
      v_persona_id,
      jsonb_build_object(
        'violation_count', v_count,
        'last_reason', p_reason,
        'window_minutes', 5
      ),
      'error',
      'whatsapp.safety'
    );
  END IF;

  RETURN jsonb_build_object(
    'binding_id', p_binding_id,
    'violation_count', v_count,
    'safety_paused', v_paused
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.record_whatsapp_safety_violation(uuid, bigint, text, text) TO service_role;
