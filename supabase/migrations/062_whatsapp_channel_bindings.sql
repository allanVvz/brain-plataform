-- Generic WhatsApp transport identity. This migration is expand-first:
-- Meta fields remain readable while new traffic is routed by binding id.

ALTER TABLE public.workflow_bindings
  ADD COLUMN IF NOT EXISTS channel text,
  ADD COLUMN IF NOT EXISTS provider text,
  ADD COLUMN IF NOT EXISTS provider_instance_key text,
  ADD COLUMN IF NOT EXISTS provider_secret_ciphertext text,
  ADD COLUMN IF NOT EXISTS connection_status text,
  ADD COLUMN IF NOT EXISTS last_connection_at timestamptz,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'workflow_bindings_channel_check'
      AND conrelid = 'public.workflow_bindings'::regclass
  ) THEN
    ALTER TABLE public.workflow_bindings
      ADD CONSTRAINT workflow_bindings_channel_check
      CHECK (channel IS NULL OR channel IN ('whatsapp'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'workflow_bindings_provider_check'
      AND conrelid = 'public.workflow_bindings'::regclass
  ) THEN
    ALTER TABLE public.workflow_bindings
      ADD CONSTRAINT workflow_bindings_provider_check
      CHECK (provider IS NULL OR provider IN ('meta_cloud', 'evolution_baileys'));
  END IF;
END
$$;

UPDATE public.workflow_bindings
SET channel = 'whatsapp',
    provider = COALESCE(provider, 'meta_cloud'),
    connection_status = COALESCE(connection_status, CASE WHEN active THEN 'connected' ELSE 'disabled' END),
    updated_at = now()
WHERE whatsapp_phone_number_id IS NOT NULL
  AND whatsapp_phone_number_id <> '';

ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS channel_binding_id uuid REFERENCES public.workflow_bindings(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS external_contact_id text;

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS channel_binding_id uuid REFERENCES public.workflow_bindings(id) ON DELETE SET NULL;

ALTER TABLE public.lead_buffer
  ADD COLUMN IF NOT EXISTS channel_binding_id uuid REFERENCES public.workflow_bindings(id) ON DELETE SET NULL;

UPDATE public.leads l
SET channel_binding_id = wb.id
FROM public.workflow_bindings wb
WHERE l.channel_binding_id IS NULL
  AND l.whatsapp_phone_number_id IS NOT NULL
  AND wb.whatsapp_phone_number_id = l.whatsapp_phone_number_id
  AND wb.active = true;

UPDATE public.messages m
SET channel_binding_id = wb.id
FROM public.workflow_bindings wb
WHERE m.channel_binding_id IS NULL
  AND m.whatsapp_phone_number_id IS NOT NULL
  AND wb.whatsapp_phone_number_id = m.whatsapp_phone_number_id
  AND wb.active = true;

UPDATE public.lead_buffer b
SET channel_binding_id = wb.id
FROM public.workflow_bindings wb
WHERE b.channel_binding_id IS NULL
  AND b.whatsapp_phone_number_id IS NOT NULL
  AND wb.whatsapp_phone_number_id = b.whatsapp_phone_number_id
  AND wb.active = true;

CREATE INDEX IF NOT EXISTS idx_workflow_bindings_provider_instance
  ON public.workflow_bindings(provider, provider_instance_key);
CREATE INDEX IF NOT EXISTS idx_leads_channel_contact
  ON public.leads(persona_id, channel_binding_id, external_contact_id);
CREATE INDEX IF NOT EXISTS idx_messages_channel_external
  ON public.messages(channel_binding_id, external_message_id);
CREATE INDEX IF NOT EXISTS idx_lead_buffer_channel
  ON public.lead_buffer(channel_binding_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_bindings_provider_instance_unique
  ON public.workflow_bindings(provider, provider_instance_key)
  WHERE provider_instance_key IS NOT NULL AND provider_instance_key <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_persona_channel_contact_unique
  ON public.leads(persona_id, channel_binding_id, external_contact_id)
  WHERE channel_binding_id IS NOT NULL
    AND external_contact_id IS NOT NULL
    AND external_contact_id <> '';

DROP INDEX IF EXISTS public.idx_messages_external_message_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_channel_external_unique
  ON public.messages(channel_binding_id, external_message_id)
  WHERE channel_binding_id IS NOT NULL
    AND external_message_id IS NOT NULL
    AND external_message_id <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_buffer_channel_external_unique
  ON public.lead_buffer(channel_binding_id, external_message_id)
  WHERE channel_binding_id IS NOT NULL
    AND external_message_id IS NOT NULL
    AND external_message_id <> '';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM public.workflow_bindings
    WHERE active = true AND channel = 'whatsapp'
    GROUP BY persona_id, channel
    HAVING count(*) > 1
  ) THEN
    EXECUTE
      'CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_bindings_one_active_whatsapp_per_persona
       ON public.workflow_bindings(persona_id, channel)
       WHERE active = true AND channel = ''whatsapp''';
  ELSE
    RAISE NOTICE 'Skipped active WhatsApp uniqueness: duplicate persona bindings require audit.';
  END IF;
END
$$;

ALTER TABLE public.lead_buffer
  ALTER COLUMN whatsapp_phone_number_id DROP NOT NULL;

-- The legacy global lead_id uniqueness prevents the same contact from existing
-- in two personas. Drop only a single-column UNIQUE constraint/index on lead_id.
DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT c.conname INTO constraint_name
  FROM pg_constraint c
  JOIN pg_attribute a
    ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
  WHERE c.conrelid = 'public.leads'::regclass
    AND c.contype = 'u'
    AND array_length(c.conkey, 1) = 1
    AND a.attname = 'lead_id'
  LIMIT 1;
  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.leads DROP CONSTRAINT %I', constraint_name);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_leads_legacy_lead_id ON public.leads(lead_id);
