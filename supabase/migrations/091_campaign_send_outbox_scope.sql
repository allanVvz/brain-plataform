-- enqueue_whatsapp_envelope (migration 070) does an explicit column-by-column
-- insert into lead_buffer/messages, so the campaign-scope columns migration
-- 087 added to both tables (message_origin, campaign_id, campaign_revision,
-- campaign_recipient_id, campaign_step, policy_checksum) are never populated
-- through this RPC today, even though a caller may now pass them. This
-- migration is additive: every new parameter defaults to the prior behavior
-- (message_origin='conversation', the rest NULL) when absent, so ordinary
-- 1:1 conversation sends are unaffected.

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
    correlation_id,
    message_origin,
    campaign_id,
    campaign_revision,
    campaign_recipient_id,
    campaign_step,
    policy_checksum
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
    NULLIF(p_buffer->>'correlation_id', ''),
    COALESCE(NULLIF(p_buffer->>'message_origin', ''), 'conversation'),
    NULLIF(p_buffer->>'campaign_id', '')::uuid,
    NULLIF(p_buffer->>'campaign_revision', '')::integer,
    NULLIF(p_buffer->>'campaign_recipient_id', '')::uuid,
    NULLIF(p_buffer->>'campaign_step', '')::integer,
    NULLIF(p_buffer->>'policy_checksum', '')
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
        created_at,
        message_origin,
        campaign_id,
        campaign_revision,
        campaign_recipient_id
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
        COALESCE(NULLIF(p_message->>'created_at', '')::timestamptz, now()),
        COALESCE(NULLIF(p_message->>'message_origin', ''), 'conversation'),
        NULLIF(p_message->>'campaign_id', '')::uuid,
        NULLIF(p_message->>'campaign_revision', '')::integer,
        NULLIF(p_message->>'campaign_recipient_id', '')::uuid
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

NOTIFY pgrst, 'reload schema';
