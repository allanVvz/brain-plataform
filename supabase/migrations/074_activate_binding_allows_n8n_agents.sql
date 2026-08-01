-- activate_persona_whatsapp_binding still hardcoded decision_owner to
-- 'deterministic': it rejected activating any binding whose decision_owner
-- was 'n8n_agents', and on success it force-rewrote the binding's metadata
-- back to decision_owner='deterministic' regardless of what was there
-- before. This was never updated when 072_allow_n8n_decision_provider_direct
-- loosened enforce_whatsapp_provider_direct_contract() to accept both
-- 'deterministic' and 'n8n_agents' as decision owners.
--
-- Net effect: using the standard "activate/reconnect channel" admin flow on
-- an n8n_agents binding (e.g. Aurora's agentic SDR) either fails outright or
-- silently reverts it to the deterministic engine. Bring this function's
-- contract in line with the trigger's, validating and preserving whichever
-- decision_owner the target binding already has instead of assuming
-- 'deterministic'.

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
  v_decision_owner text;
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

  v_decision_owner := COALESCE(target.metadata->>'decision_owner', '');

  IF v_decision_owner NOT IN ('deterministic', 'n8n_agents')
     OR COALESCE(target.metadata->>'transport_mode', '') <> 'provider_direct'
     OR NULLIF(target.metadata->>'outbound_webhook_url', '') IS NOT NULL
     OR NULLIF(target.metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL THEN
    RAISE EXCEPTION 'WhatsApp binding must use an approved decision owner and provider-direct transport'
      USING ERRCODE = '23514';
  END IF;

  IF v_decision_owner = 'deterministic'
     AND (
       NULLIF(target.n8n_workflow_id, '') IS NOT NULL
       OR NULLIF(target.metadata->>'conversation_webhook_url', '') IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'Deterministic binding cannot reference a conversation workflow'
      USING ERRCODE = '23514';
  END IF;

  IF v_decision_owner = 'n8n_agents'
     AND (
       NULLIF(target.n8n_workflow_id, '') IS NULL
       OR NULLIF(target.metadata->>'conversation_webhook_url', '') IS NULL
     ) THEN
    RAISE EXCEPTION 'n8n decision binding requires workflow id and conversation webhook'
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

  -- Only strip the forbidden outbound-adapter keys and reassert the
  -- provider-direct contract; decision_owner (and therefore
  -- n8n_workflow_id/conversation_webhook_url) is preserved exactly as
  -- already validated above, never forced to 'deterministic'.
  UPDATE public.workflow_bindings
  SET active = true,
      metadata = (
        COALESCE(metadata, '{}'::jsonb)
        - 'n8n_outbound_webhook_url'
        - 'outbound_webhook_url'
      ) || jsonb_build_object(
        'decision_owner', v_decision_owner,
        'conversation_mode', CASE
          WHEN v_decision_owner = 'n8n_agents' THEN 'n8n_agents'
          ELSE 'deterministic'
        END,
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
      'decision_owner', v_decision_owner,
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
    'decision_owner', v_decision_owner,
    'previous_binding_ids', previous_binding_ids,
    'rebound_leads', rebound_count,
    'status', target.connection_status
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.activate_persona_whatsapp_binding(uuid, uuid, text, text)
  TO service_role;
