-- Exactly-once WhatsApp hotfix.
--
-- lead_buffer.idempotency_key is the durable lock for inboxes, decisions and
-- manual sends.  Provider callbacks are observations only and all delivery
-- transitions are scoped by channel binding + provider message id.

ALTER TABLE public.lead_buffer
  DROP CONSTRAINT IF EXISTS lead_buffer_status_check;
ALTER TABLE public.lead_buffer
  ADD CONSTRAINT lead_buffer_status_check CHECK (status IN (
    'received', 'buffered', 'processing', 'pending_send', 'sent', 'delivered',
    'read', 'failed', 'retry', 'dead_letter', 'waiting_human', 'ignored'
  ));

CREATE OR REPLACE FUNCTION public.enqueue_whatsapp_envelope(
  p_buffer jsonb,
  p_message jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_message public.messages%ROWTYPE;
  v_inserted boolean := false;
BEGIN
  IF NULLIF(p_buffer->>'idempotency_key', '') IS NULL THEN
    RAISE EXCEPTION 'idempotency_key is required';
  END IF;
  IF NULLIF(p_buffer->>'channel_binding_id', '') IS NULL THEN
    RAISE EXCEPTION 'channel_binding_id is required';
  END IF;

  INSERT INTO public.lead_buffer (
    persona_id,
    lead_ref,
    channel_binding_id,
    whatsapp_phone_number_id,
    external_message_id,
    direction,
    payload,
    status,
    batch_key,
    available_at,
    max_attempts,
    idempotency_key,
    correlation_id
  )
  VALUES (
    (p_buffer->>'persona_id')::uuid,
    NULLIF(p_buffer->>'lead_ref', '')::bigint,
    (p_buffer->>'channel_binding_id')::uuid,
    NULLIF(p_buffer->>'whatsapp_phone_number_id', ''),
    NULLIF(p_buffer->>'external_message_id', ''),
    p_buffer->>'direction',
    COALESCE(p_buffer->'payload', '{}'::jsonb),
    COALESCE(NULLIF(p_buffer->>'status', ''), 'buffered'),
    p_buffer->>'batch_key',
    COALESCE(NULLIF(p_buffer->>'available_at', '')::timestamptz, now()),
    COALESCE(NULLIF(p_buffer->>'max_attempts', '')::integer, 5),
    p_buffer->>'idempotency_key',
    NULLIF(p_buffer->>'correlation_id', '')
  )
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING * INTO v_buffer;

  v_inserted := FOUND;
  IF NOT v_inserted THEN
    SELECT *
      INTO v_buffer
      FROM public.lead_buffer
     WHERE idempotency_key = p_buffer->>'idempotency_key';
  END IF;

  IF v_buffer.id IS NULL THEN
    RAISE EXCEPTION 'failed to resolve WhatsApp idempotency lock';
  END IF;

  SELECT *
    INTO v_message
    FROM public.messages
   WHERE channel_binding_id = v_buffer.channel_binding_id
     AND (
       (
         v_buffer.external_message_id IS NOT NULL
         AND external_message_id = v_buffer.external_message_id
       )
       OR (
         v_buffer.correlation_id IS NOT NULL
         AND correlation_id = v_buffer.correlation_id
       )
     )
   ORDER BY created_at
   LIMIT 1;

  -- The winning transaction creates both projections.  The second branch also
  -- repairs a pre-hotfix buffer that was committed without its message row.
  IF v_message.id IS NULL THEN
    BEGIN
      INSERT INTO public.messages (
        lead_id,
        role,
        content,
        direction,
        status,
        channel,
        sender_id,
        whatsapp_phone_number_id,
        external_message_id,
        channel_binding_id,
        correlation_id,
        metadata,
        created_at
      )
      VALUES (
        NULLIF(p_message->>'lead_id', '')::bigint,
        COALESCE(NULLIF(p_message->>'role', ''), 'user'),
        COALESCE(p_message->>'content', ''),
        p_message->>'direction',
        p_message->>'status',
        COALESCE(NULLIF(p_message->>'channel', ''), 'whatsapp'),
        p_message->>'sender_id',
        NULLIF(p_message->>'whatsapp_phone_number_id', ''),
        NULLIF(p_message->>'external_message_id', ''),
        (p_message->>'channel_binding_id')::uuid,
        NULLIF(p_message->>'correlation_id', ''),
        COALESCE(p_message->'metadata', '{}'::jsonb),
        COALESCE(NULLIF(p_message->>'created_at', '')::timestamptz, now())
      )
      RETURNING * INTO v_message;
    EXCEPTION WHEN unique_violation THEN
      SELECT *
        INTO v_message
        FROM public.messages
       WHERE channel_binding_id = v_buffer.channel_binding_id
         AND (
           (
             v_buffer.external_message_id IS NOT NULL
             AND external_message_id = v_buffer.external_message_id
           )
           OR (
             v_buffer.correlation_id IS NOT NULL
             AND correlation_id = v_buffer.correlation_id
           )
         )
       ORDER BY created_at
       LIMIT 1;
    END;
  END IF;

  RETURN jsonb_build_object(
    'buffer_id', v_buffer.id,
    'message_row_id', v_message.id,
    'message_id', COALESCE(v_message.sender_id, p_message->>'sender_id'),
    'status', v_buffer.status,
    'deduplicated', NOT v_inserted
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.enqueue_whatsapp_envelope(jsonb, jsonb)
  TO service_role;


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
     AND entity_id = p_binding_id
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


CREATE OR REPLACE FUNCTION public.mark_whatsapp_attempt(
  p_buffer_id uuid,
  p_worker text,
  p_kind text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_key text;
BEGIN
  IF p_kind NOT IN ('decision', 'provider') THEN
    RAISE EXCEPTION 'invalid WhatsApp attempt kind';
  END IF;
  v_key := p_kind || '_attempt_started_at';

  UPDATE public.lead_buffer
     SET payload = COALESCE(payload, '{}'::jsonb)
           || jsonb_build_object(
                v_key, now(),
                p_kind || '_attempt_worker', p_worker
              ),
         updated_at = now()
   WHERE id = p_buffer_id
     AND status = 'processing'
     AND locked_by = p_worker
     AND NOT (COALESCE(payload, '{}'::jsonb) ? v_key);

  RETURN FOUND;
END;
$$;

GRANT EXECUTE ON FUNCTION public.mark_whatsapp_attempt(uuid, text, text)
  TO service_role;


CREATE OR REPLACE FUNCTION public.quarantine_expired_whatsapp_attempts(
  p_lease_seconds integer DEFAULT 60
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
  v_count integer := 0;
BEGIN
  FOR v_row IN
    SELECT *
      FROM public.lead_buffer
     WHERE status = 'processing'
       AND locked_at < now() - make_interval(
             secs => greatest(p_lease_seconds, 1)
           )
       AND (
         COALESCE(payload, '{}'::jsonb) ? 'decision_attempt_started_at'
         OR COALESCE(payload, '{}'::jsonb) ? 'provider_attempt_started_at'
       )
     FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE public.lead_buffer
       SET status = 'waiting_human',
           last_error = 'expired ambiguous WhatsApp attempt',
           locked_at = NULL,
           locked_by = NULL,
           updated_at = now()
     WHERE id = v_row.id;

    PERFORM public.record_whatsapp_safety_violation(
      v_row.channel_binding_id,
      v_row.lead_ref,
      'expired-attempt:' || v_row.id::text,
      'expired ambiguous WhatsApp attempt'
    );
    v_count := v_count + 1;
  END LOOP;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.quarantine_expired_whatsapp_attempts(integer)
  TO service_role;


-- An expired row is reclaimable only when no decision/provider attempt began.
-- Once an external side effect may have happened, quarantine_expired... moves
-- it to waiting_human before this query can return it.
CREATE OR REPLACE FUNCTION public.claim_whatsapp_buffer(
  p_worker text,
  p_limit integer DEFAULT 20,
  p_lease_seconds integer DEFAULT 60
)
RETURNS SETOF public.lead_buffer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  PERFORM public.quarantine_expired_whatsapp_attempts(p_lease_seconds);

  RETURN QUERY
  WITH candidates AS (
    SELECT id
      FROM public.lead_buffer
     WHERE (
       status IN ('buffered', 'retry', 'pending_send')
       AND available_at <= now()
     ) OR (
       status = 'processing'
       AND locked_at < now() - make_interval(
             secs => greatest(p_lease_seconds, 1)
           )
       AND NOT (
         COALESCE(payload, '{}'::jsonb) ? 'decision_attempt_started_at'
         OR COALESCE(payload, '{}'::jsonb) ? 'provider_attempt_started_at'
       )
     )
     ORDER BY available_at, created_at
     FOR UPDATE SKIP LOCKED
     LIMIT greatest(p_limit, 1)
  )
  UPDATE public.lead_buffer b
     SET status = 'processing',
         locked_at = now(),
         locked_by = p_worker,
         attempt_count = b.attempt_count + 1,
         updated_at = now()
    FROM candidates
   WHERE b.id = candidates.id
  RETURNING b.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_whatsapp_buffer(text, integer, integer)
  TO service_role;


-- Delivery callbacks are observations, never queue commands.  Repeated,
-- unknown and out-of-order callbacks stay auditable but do not mutate state.
CREATE OR REPLACE FUNCTION public.reconcile_whatsapp_delivery(
  p_binding_id uuid,
  p_external_message_id text,
  p_status text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_persona_id uuid;
  v_updated boolean := false;
BEGIN
  SELECT persona_id
    INTO v_persona_id
    FROM public.workflow_bindings
   WHERE id = p_binding_id;

  IF p_status = 'sent' THEN
    UPDATE public.lead_buffer
       SET status = 'sent', updated_at = now()
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status IN ('processing', 'pending_send');
    v_updated := v_updated OR FOUND;
    UPDATE public.messages
       SET status = 'sent'
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status IN ('pending', 'pending_send', 'processing');
    v_updated := v_updated OR FOUND;
  ELSIF p_status = 'delivered' THEN
    UPDATE public.lead_buffer
       SET status = 'delivered', updated_at = now()
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status = 'sent';
    v_updated := v_updated OR FOUND;
    UPDATE public.messages
       SET status = 'delivered'
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status = 'sent';
    v_updated := v_updated OR FOUND;
  ELSIF p_status = 'read' THEN
    UPDATE public.lead_buffer
       SET status = 'read', updated_at = now()
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status = 'delivered';
    v_updated := v_updated OR FOUND;
    UPDATE public.messages
       SET status = 'read'
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status = 'delivered';
    v_updated := v_updated OR FOUND;
  ELSIF p_status = 'failed' THEN
    UPDATE public.lead_buffer
       SET status = 'failed', updated_at = now()
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status NOT IN ('delivered', 'read', 'failed');
    v_updated := v_updated OR FOUND;
    UPDATE public.messages
       SET status = 'failed'
     WHERE channel_binding_id = p_binding_id
       AND external_message_id = p_external_message_id
       AND status NOT IN ('delivered', 'read', 'failed');
    v_updated := v_updated OR FOUND;
  END IF;

  IF NOT v_updated THEN
    INSERT INTO public.system_events (
      event_type, entity_type, entity_id, persona_id, payload, level, source
    )
    VALUES (
      'whatsapp.delivery_ack_ignored',
      'workflow_binding',
      p_binding_id,
      v_persona_id,
      jsonb_build_object(
        'external_message_id', p_external_message_id,
        'status', p_status
      ),
      'info',
      'whatsapp.delivery'
    );
  END IF;

  RETURN jsonb_build_object(
    'updated', v_updated,
    'binding_id', p_binding_id,
    'external_message_id', p_external_message_id,
    'status', p_status
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.reconcile_whatsapp_delivery(uuid, text, text)
  TO service_role;


CREATE OR REPLACE FUNCTION public.complete_whatsapp_outbound_result(
  p_buffer_id uuid,
  p_binding_id uuid,
  p_correlation_id text,
  p_external_message_id text,
  p_success boolean,
  p_error text DEFAULT NULL,
  p_execution_id text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
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
       AND correlation_id = p_correlation_id;
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


-- Outstanding Evolution work is cancelled without erasing the audit trail.
UPDATE public.lead_buffer
   SET status = 'ignored',
       last_error = 'safety_hotfix_cancelled',
       locked_at = NULL,
       locked_by = NULL,
       updated_at = now()
 WHERE direction = 'outbound'
   AND status IN ('pending_send', 'retry', 'processing')
   AND channel_binding_id IN (
     SELECT id
       FROM public.workflow_bindings
      WHERE provider = 'evolution_baileys'
   );
