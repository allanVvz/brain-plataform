-- n8n may own the conversational decision while WhatsApp delivery remains
-- provider-direct.  Outbound transport adapters remain forbidden.

CREATE OR REPLACE FUNCTION public.enforce_whatsapp_provider_direct_contract()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_owner text;
BEGIN
  IF NEW.channel = 'whatsapp'
     AND NEW.active = true
     AND NEW.provider IN ('meta_cloud', 'evolution_baileys') THEN
    v_owner := COALESCE(NEW.metadata->>'decision_owner', '');
    IF v_owner NOT IN ('deterministic', 'n8n_agents')
       OR COALESCE(NEW.metadata->>'transport_mode', '') <> 'provider_direct' THEN
      RAISE EXCEPTION
        'Active WhatsApp binding must use an approved decision owner and provider-direct transport'
        USING ERRCODE = '23514';
    END IF;

    IF NULLIF(NEW.metadata->>'outbound_webhook_url', '') IS NOT NULL
       OR NULLIF(NEW.metadata->>'n8n_outbound_webhook_url', '') IS NOT NULL THEN
      RAISE EXCEPTION
        'Provider-direct WhatsApp binding cannot use an outbound n8n adapter'
        USING ERRCODE = '23514';
    END IF;

    IF v_owner = 'deterministic'
       AND (
         NULLIF(NEW.n8n_workflow_id, '') IS NOT NULL
         OR NULLIF(NEW.metadata->>'conversation_webhook_url', '') IS NOT NULL
       ) THEN
      RAISE EXCEPTION
        'Deterministic binding cannot reference a conversation workflow'
        USING ERRCODE = '23514';
    END IF;

    IF v_owner = 'n8n_agents'
       AND (
         NULLIF(NEW.n8n_workflow_id, '') IS NULL
         OR NULLIF(NEW.metadata->>'conversation_webhook_url', '') IS NULL
       ) THEN
      RAISE EXCEPTION
        'n8n decision binding requires workflow id and conversation webhook'
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
