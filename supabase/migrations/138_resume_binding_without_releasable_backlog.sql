-- Resume a persona-scoped WhatsApp binding when the canonical runtime
-- staleness check found no backlog row that may still speak.  This closes a
-- lifecycle hole in register_release_batch_v1: that function correctly
-- rejects an empty release list, but the rejection used to leave the binding
-- safety-paused forever even though there was intentionally nothing to send.

CREATE OR REPLACE FUNCTION public.resume_safety_paused_binding_v1(
  p_persona_id uuid,
  p_binding_id uuid,
  p_reason text,
  p_idempotency_key text,
  p_release_sha text DEFAULT NULL,
  p_actor_user_id uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_batch_id uuid;
BEGIN
  IF p_persona_id IS NULL OR p_binding_id IS NULL THEN
    RAISE EXCEPTION 'persona and binding are required' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(btrim(p_idempotency_key), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'idempotency key and reason are required' USING ERRCODE = '22023';
  END IF;

  SELECT id INTO v_batch_id
    FROM public.release_batches
   WHERE idempotency_key = p_idempotency_key;
  IF v_batch_id IS NOT NULL THEN
    RETURN jsonb_build_object(
      'batch_id', v_batch_id,
      'item_count', 0,
      'deduplicated', true
    );
  END IF;

  UPDATE public.workflow_bindings
     SET connection_status = 'connected',
         metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
           'safety_paused', false,
           'safety_resumed_at', now(),
           'safety_resume_reason', p_reason,
           'safety_resume_empty_backlog', true
         ),
         updated_at = now()
   WHERE id = p_binding_id
     AND persona_id = p_persona_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'workflow binding not found for persona' USING ERRCODE = 'P0002';
  END IF;

  INSERT INTO public.release_batches (
    persona_id, scope, binding_id, release_sha, status, timezone,
    window_start_local, window_end_local, stagger_seconds, item_count,
    reason, idempotency_key, created_by
  ) VALUES (
    p_persona_id, 'safety_paused_binding', p_binding_id, p_release_sha,
    'registered', 'America/Sao_Paulo', '08:00', '20:00', 4, 0,
    p_reason, p_idempotency_key, p_actor_user_id
  ) RETURNING id INTO v_batch_id;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'whatsapp.binding_resumed_without_releasable_backlog',
    'release_batch', v_batch_id::text, p_persona_id,
    jsonb_build_object(
      'scope', 'safety_paused_binding',
      'binding_id', p_binding_id,
      'release_sha', p_release_sha,
      'item_count', 0,
      'reason', p_reason,
      'idempotency_key', p_idempotency_key,
      'actor_user_id', p_actor_user_id
    ),
    'info', 'whatsapp.release_queue'
  );

  RETURN jsonb_build_object(
    'batch_id', v_batch_id,
    'item_count', 0,
    'deduplicated', false
  );
END;
$$;

REVOKE ALL ON FUNCTION public.resume_safety_paused_binding_v1(
  uuid, uuid, text, text, text, uuid
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resume_safety_paused_binding_v1(
  uuid, uuid, text, text, text, uuid
) TO service_role;
