-- Normalize active bindings created before the provider-direct contract became
-- mandatory. Provider credentials and historical transport rows are untouched.

UPDATE public.workflow_bindings
SET metadata = (
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
WHERE channel = 'whatsapp'
  AND active = true
  AND (
    COALESCE(metadata->>'decision_owner', '') <> 'deterministic'
    OR COALESCE(metadata->>'transport_mode', '') <> 'provider_direct'
    OR NULLIF(metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL
    OR NULLIF(metadata->>'conversation_webhook_url', '') IS NOT NULL
  );

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
  'whatsapp.binding_contract_normalized',
  'workflow_binding',
  id,
  persona_id,
  jsonb_build_object(
    'provider', provider,
    'binding_id', id,
    'decision_owner', metadata->>'decision_owner',
    'transport_mode', metadata->>'transport_mode'
  ),
  'info',
  'migration.068'
FROM public.workflow_bindings
WHERE channel = 'whatsapp'
  AND active = true
  AND metadata->>'decision_owner' = 'deterministic'
  AND metadata->>'transport_mode' = 'provider_direct';
