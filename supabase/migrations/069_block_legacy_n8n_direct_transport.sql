-- Provider-direct WhatsApp delivery must never retain an executable n8n route.
-- Remove legacy pointers without touching messages, outbox rows, credentials,
-- provider identifiers, or historical external message ids.

WITH cleaned AS (
  UPDATE public.workflow_bindings
  SET n8n_workflow_id = NULL,
      metadata = (
        COALESCE(metadata, '{}'::jsonb)
        - 'outbound_webhook_url'
        - 'n8n_outbound_webhook_url'
        - 'conversation_webhook_url'
      ),
      updated_at = now()
  WHERE channel = 'whatsapp'
    AND COALESCE(metadata->>'transport_mode', '') = 'provider_direct'
    AND (
      NULLIF(n8n_workflow_id, '') IS NOT NULL
      OR NULLIF(metadata->>'outbound_webhook_url', '') IS NOT NULL
      OR NULLIF(metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL
      OR NULLIF(metadata->>'conversation_webhook_url', '') IS NOT NULL
    )
  RETURNING id, persona_id, provider
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
  'whatsapp.binding_n8n_route_removed',
  'workflow_binding',
  id,
  persona_id,
  jsonb_build_object(
    'provider', provider,
    'binding_id', id,
    'transport_mode', 'provider_direct'
  ),
  'info',
  'migration.069'
FROM cleaned;

CREATE OR REPLACE FUNCTION public.enforce_whatsapp_provider_direct_contract()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  IF NEW.channel = 'whatsapp'
     AND NEW.active = true
     AND NEW.provider IN ('meta_cloud', 'evolution_baileys') THEN
    IF COALESCE(NEW.metadata->>'decision_owner', '') <> 'deterministic'
       OR COALESCE(NEW.metadata->>'transport_mode', '') <> 'provider_direct' THEN
      RAISE EXCEPTION
        'Active WhatsApp binding must use deterministic provider-direct transport'
        USING ERRCODE = '23514';
    END IF;

    IF NULLIF(NEW.n8n_workflow_id, '') IS NOT NULL
       OR NULLIF(NEW.metadata->>'outbound_webhook_url', '') IS NOT NULL
       OR NULLIF(NEW.metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL
       OR NULLIF(NEW.metadata->>'conversation_webhook_url', '') IS NOT NULL THEN
      RAISE EXCEPTION
        'Provider-direct WhatsApp binding cannot reference n8n'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_whatsapp_provider_direct_contract
  ON public.workflow_bindings;
CREATE TRIGGER trg_enforce_whatsapp_provider_direct_contract
BEFORE INSERT OR UPDATE ON public.workflow_bindings
FOR EACH ROW
EXECUTE FUNCTION public.enforce_whatsapp_provider_direct_contract();
