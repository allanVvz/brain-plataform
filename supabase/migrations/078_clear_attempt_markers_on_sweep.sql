-- Every sweep that returns a lead_buffer row to a reprocessable state
-- (waiting_human via handoff/safety-violation, retry via resume-ai's
-- requeue) resets status/locked_at/locked_by but has never cleared the
-- decision_attempt_started_at / provider_attempt_started_at markers
-- mark_whatsapp_attempt wrote into payload during the interrupted attempt.
--
-- mark_whatsapp_attempt only succeeds when payload does NOT already have
-- that key (its whole job is detecting two workers racing the same row).
-- Once a stale marker survives a sweep, every future attempt on that row
-- reads it as "already in progress" and fires
-- record_whatsapp_safety_violation as a false positive -- which sweeps
-- and re-pauses the lead again, forever. The row can never be
-- successfully processed again without an engineer manually clearing
-- payload.
--
-- Confirmed live 2026-08-02 (Baita lead #5): a message that started a
-- decision attempt, got swept back to waiting_human by a sibling
-- message's handoff, was resumed via resume-ai's requeue, and immediately
-- re-tripped the safety guard on its own stale marker -- re-pausing the
-- lead within milliseconds of every resume attempt, with no real
-- concurrent execution ever happening.
--
-- By the time any of these functions run, the guard has already done its
-- job for that attempt (violation logged and/or lead paused): carrying
-- the marker forward protects nothing and only blocks all future
-- reprocessing, so it is safe to clear here.

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead(p_lead_ref bigint)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
begin
  update public.leads
  set ai_paused = true, updated_at = now()
  where id = p_lead_ref;

  update public.lead_buffer
  set status = 'waiting_human',
      locked_at = null,
      locked_by = null,
      payload = COALESCE(payload, '{}'::jsonb)
        - 'decision_attempt_started_at' - 'decision_attempt_worker'
        - 'provider_attempt_started_at' - 'provider_attempt_worker',
      updated_at = now()
  where lead_ref = p_lead_ref
    and direction = 'inbound'
    and status in ('received', 'buffered', 'processing', 'pending_send', 'retry');
end;
$$;

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead_state(p_lead_ref bigint, p_metadata jsonb, p_stage text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
BEGIN
  UPDATE public.leads
     SET ai_paused = true,
         metadata = COALESCE(p_metadata, metadata, '{}'::jsonb),
         stage = COALESCE(NULLIF(p_stage, ''), stage),
         updated_at = now()
   WHERE id = p_lead_ref;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'lead not found: %', p_lead_ref;
  END IF;

  UPDATE public.lead_buffer
     SET status = 'waiting_human',
         locked_at = null,
         locked_by = null,
         payload = COALESCE(payload, '{}'::jsonb)
           - 'decision_attempt_started_at' - 'decision_attempt_worker'
           - 'provider_attempt_started_at' - 'provider_attempt_worker',
         updated_at = now()
   WHERE lead_ref = p_lead_ref
     AND direction = 'inbound'
     AND status IN (
       'received', 'buffered', 'processing', 'pending_send', 'retry'
     );
END;
$$;

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
  UPDATE public.lead_buffer
     SET status = 'retry',
         available_at = now(),
         locked_at = NULL,
         locked_by = NULL,
         payload = COALESCE(payload, '{}'::jsonb)
           - 'decision_attempt_started_at' - 'decision_attempt_worker'
           - 'provider_attempt_started_at' - 'provider_attempt_worker',
         updated_at = now()
   WHERE lead_ref = p_lead_ref
     AND direction = 'inbound'
     AND status = 'waiting_human';
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

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
  END IF;

  RETURN jsonb_build_object(
    'binding_id', p_binding_id,
    'violation_count', v_count,
    'safety_paused', v_paused
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead(bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead_state(bigint, jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.requeue_waiting_human_whatsapp_buffer(bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_whatsapp_safety_violation(uuid, bigint, text, text) TO service_role;
