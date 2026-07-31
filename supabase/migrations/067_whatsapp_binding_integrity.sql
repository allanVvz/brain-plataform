-- Keep one active WhatsApp transport per persona and make the lead pointer
-- follow that transport. Existing messages/outbox rows intentionally retain
-- their original binding for delivery history and provider reconciliation.

-- Resolve any legacy duplicate active bindings deterministically before
-- enforcing the invariant. The most recently updated binding wins.
WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY persona_id
      ORDER BY updated_at DESC NULLS LAST, id DESC
    ) AS position
  FROM public.workflow_bindings
  WHERE channel = 'whatsapp'
    AND active = true
)
UPDATE public.workflow_bindings binding
SET active = false,
    updated_at = now()
FROM ranked
WHERE binding.id = ranked.id
  AND ranked.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_bindings_one_active_whatsapp_per_persona
  ON public.workflow_bindings(persona_id, channel)
  WHERE active = true
    AND channel = 'whatsapp';

CREATE OR REPLACE FUNCTION public.activate_persona_whatsapp_binding(
  p_persona_id uuid,
  p_binding_id uuid,
  p_provider text,
  p_source text DEFAULT 'admin.settings'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  target public.workflow_bindings%ROWTYPE;
  rebound_count integer := 0;
  previous_binding_ids jsonb := '[]'::jsonb;
BEGIN
  IF p_provider NOT IN ('meta_cloud', 'evolution_baileys') THEN
    RAISE EXCEPTION 'Unsupported WhatsApp provider: %', p_provider
      USING ERRCODE = '22023';
  END IF;

  -- Serialize channel switches for this persona while retaining all historical
  -- binding rows and their provider-specific delivery identifiers.
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text, 0));

  SELECT *
  INTO target
  FROM public.workflow_bindings
  WHERE id = p_binding_id
  FOR UPDATE;

  IF NOT FOUND
     OR target.persona_id IS DISTINCT FROM p_persona_id
     OR target.channel IS DISTINCT FROM 'whatsapp'
     OR target.provider IS DISTINCT FROM p_provider THEN
    RAISE EXCEPTION 'WhatsApp binding does not belong to the requested persona/provider'
      USING ERRCODE = '23514';
  END IF;

  IF COALESCE(target.metadata->>'decision_owner', '') <> 'deterministic'
     OR COALESCE(target.metadata->>'transport_mode', '') <> 'provider_direct'
     OR NULLIF(target.metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL
     OR NULLIF(target.metadata->>'conversation_webhook_url', '') IS NOT NULL THEN
    RAISE EXCEPTION 'WhatsApp binding must use deterministic provider-direct transport'
      USING ERRCODE = '23514';
  END IF;

  IF p_provider = 'meta_cloud' AND (
    NULLIF(target.whatsapp_phone_number_id, '') IS NULL
    OR NULLIF(target.provider_secret_ciphertext, '') IS NULL
    OR COALESCE(target.connection_status, '') NOT IN ('connected', 'open')
  ) THEN
    RAISE EXCEPTION 'Meta binding is missing credential, phone number id, or connected status'
      USING ERRCODE = '23514';
  END IF;

  IF p_provider = 'evolution_baileys' AND (
    NULLIF(target.provider_instance_key, '') IS NULL
    OR NULLIF(target.provider_secret_ciphertext, '') IS NULL
    OR COALESCE(target.connection_status, '') NOT IN (
      'provisioning', 'connecting', 'qr_ready', 'connected', 'open'
    )
  ) THEN
    RAISE EXCEPTION 'Evolution binding is missing instance, credential, or connection state'
      USING ERRCODE = '23514';
  END IF;

  SELECT COALESCE(jsonb_agg(id), '[]'::jsonb)
  INTO previous_binding_ids
  FROM public.workflow_bindings
  WHERE persona_id = p_persona_id
    AND channel = 'whatsapp'
    AND active = true
    AND id <> p_binding_id;

  UPDATE public.workflow_bindings
  SET active = false,
      updated_at = now()
  WHERE persona_id = p_persona_id
    AND channel = 'whatsapp'
    AND active = true
    AND id <> p_binding_id;

  UPDATE public.workflow_bindings
  SET active = true,
      metadata = (
        COALESCE(metadata, '{}'::jsonb)
        - 'n8n_outbound_webhook_url'
        - 'conversation_webhook_url'
      ) || jsonb_build_object(
        'decision_owner', 'deterministic',
        'conversation_mode', 'deterministic',
        'transport_mode', 'provider_direct',
        'pipeline_contract', 'conversation_v1'
      ),
      updated_at = now()
  WHERE id = p_binding_id;

  UPDATE public.leads
  SET channel_binding_id = p_binding_id,
      updated_at = now()
  WHERE persona_id = p_persona_id
    AND channel_binding_id IS DISTINCT FROM p_binding_id;
  GET DIAGNOSTICS rebound_count = ROW_COUNT;

  INSERT INTO public.system_events (
    event_type,
    entity_type,
    entity_id,
    persona_id,
    payload,
    level,
    source
  )
  VALUES (
    'whatsapp.binding_activated',
    'workflow_binding',
    p_binding_id,
    p_persona_id,
    jsonb_build_object(
      'provider', p_provider,
      'binding_id', p_binding_id,
      'previous_binding_ids', previous_binding_ids,
      'rebound_leads', rebound_count
    ),
    'info',
    COALESCE(NULLIF(p_source, ''), 'admin.settings')
  );

  RETURN jsonb_build_object(
    'ok', true,
    'provider', p_provider,
    'binding_id', p_binding_id,
    'previous_binding_ids', previous_binding_ids,
    'rebound_leads', rebound_count,
    'status', target.connection_status
  );
END;
$$;

REVOKE ALL ON FUNCTION public.activate_persona_whatsapp_binding(uuid, uuid, text, text)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.activate_persona_whatsapp_binding(uuid, uuid, text, text)
  TO service_role;

-- Backfill every existing persona with an active channel. This also records
-- production evidence without exposing credentials or phone numbers.
DO $$
DECLARE
  binding record;
  rebound_count integer;
BEGIN
  FOR binding IN
    SELECT id, persona_id, provider
    FROM public.workflow_bindings
    WHERE channel = 'whatsapp'
      AND active = true
  LOOP
    UPDATE public.leads
    SET channel_binding_id = binding.id,
        updated_at = now()
    WHERE persona_id = binding.persona_id
      AND channel_binding_id IS DISTINCT FROM binding.id;
    GET DIAGNOSTICS rebound_count = ROW_COUNT;

    INSERT INTO public.system_events (
      event_type,
      entity_type,
      entity_id,
      persona_id,
      payload,
      level,
      source
    )
    VALUES (
      'whatsapp.binding_backfilled',
      'workflow_binding',
      binding.id,
      binding.persona_id,
      jsonb_build_object(
        'provider', binding.provider,
        'binding_id', binding.id,
        'rebound_leads', rebound_count
      ),
      'info',
      'migration.067'
    );
  END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION public.enforce_lead_channel_binding()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  binding_persona_id uuid;
  binding_channel text;
BEGIN
  IF NEW.persona_id IS NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.channel_binding_id IS NULL THEN
    SELECT id
    INTO NEW.channel_binding_id
    FROM public.workflow_bindings
    WHERE persona_id = NEW.persona_id
      AND channel = 'whatsapp'
      AND active = true
    LIMIT 1;
    RETURN NEW;
  END IF;

  SELECT persona_id, channel
  INTO binding_persona_id, binding_channel
  FROM public.workflow_bindings
  WHERE id = NEW.channel_binding_id;

  IF NOT FOUND OR binding_channel IS DISTINCT FROM 'whatsapp' THEN
    RAISE EXCEPTION 'Lead channel binding is not a WhatsApp binding'
      USING ERRCODE = '23514';
  END IF;
  IF binding_persona_id IS DISTINCT FROM NEW.persona_id THEN
    RAISE EXCEPTION 'Lead channel binding belongs to another persona'
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_lead_channel_binding ON public.leads;
CREATE TRIGGER trg_enforce_lead_channel_binding
BEFORE INSERT OR UPDATE ON public.leads
FOR EACH ROW
EXECUTE FUNCTION public.enforce_lead_channel_binding();
