-- A WhatsApp question and its automated answer intentionally share one
-- correlation_id. They are distinct projections because their directions
-- differ. Keep lead_buffer as the durable envelope and repair messages without
-- copying data into another store.

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
     AND direction = v_buffer.direction
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
         AND direction = v_buffer.direction
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

WITH missing AS (
  SELECT b.*
  FROM public.lead_buffer b
  WHERE b.direction = 'outbound'
    AND b.lead_ref IS NOT NULL
    AND b.channel_binding_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.messages m
      WHERE m.channel_binding_id = b.channel_binding_id
        AND m.direction = b.direction
        AND (
          (
            b.external_message_id IS NOT NULL
            AND m.external_message_id = b.external_message_id
          )
          OR (
            b.correlation_id IS NOT NULL
            AND m.correlation_id = b.correlation_id
          )
        )
    )
),
inserted AS (
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
  SELECT
    b.lead_ref,
    CASE WHEN b.payload->>'sender_type' = 'human' THEN 'human' ELSE 'assistant' END,
    COALESCE(b.payload->>'text', ''),
    'outbound',
    CASE
      WHEN b.status IN ('sent', 'delivered', 'read', 'failed') THEN b.status
      WHEN b.status IN ('pending_send', 'retry') THEN 'pending'
      ELSE COALESCE(b.status, 'pending')
    END,
    'whatsapp',
    COALESCE(
      NULLIF(b.payload->>'sender_id', ''),
      'projection:' || b.id::text
    ),
    b.whatsapp_phone_number_id,
    b.external_message_id,
    b.channel_binding_id,
    b.correlation_id,
    jsonb_build_object(
      'projection_backfill', '070_whatsapp_directional_projection',
      'sender_type', COALESCE(b.payload->>'sender_type', 'agent'),
      'buffer_id', b.id
    ),
    b.created_at
  FROM missing b
  ON CONFLICT DO NOTHING
  RETURNING lead_id, id
),
counts AS (
  SELECT l.persona_id, count(*)::integer AS restored
  FROM inserted i
  JOIN public.leads l ON l.id = i.lead_id
  GROUP BY l.persona_id
)
INSERT INTO public.system_events (
  event_type,
  entity_type,
  entity_id,
  persona_id,
  payload,
  level,
  source
)
SELECT
  'whatsapp.message_projection_backfilled',
  'persona',
  persona_id::text,
  persona_id,
  jsonb_build_object('restored_messages', restored),
  'info',
  'migration.070'
FROM counts;

-- Existing release E2E leads are validation conversations. Normalize their
-- marker without moving or duplicating any message.
UPDATE public.leads
SET metadata = jsonb_set(
      COALESCE(metadata, '{}'::jsonb),
      '{validation}',
      jsonb_build_object(
        'is_validation', true,
        'source', 'release_e2e',
        'run_id', metadata->>'e2e_run'
      ),
      true
    ),
    updated_at = now()
WHERE NULLIF(metadata->>'e2e_run', '') IS NOT NULL;
