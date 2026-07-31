-- Runtime credentials and public output belong to a persona, not to the
-- operator who happened to configure them. Reuse the existing table and keep
-- user_id as the audited configuring actor.

ALTER TABLE public.user_integration_connections
  ADD COLUMN IF NOT EXISTS persona_id uuid
  REFERENCES public.personas(id) ON DELETE CASCADE;

ALTER TABLE public.user_integration_connections
  DROP CONSTRAINT IF EXISTS user_integration_connections_user_id_service_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_integrations_persona_service
  ON public.user_integration_connections(persona_id, service)
  WHERE persona_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_integrations_legacy_user_service
  ON public.user_integration_connections(user_id, service)
  WHERE persona_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_user_integrations_persona
  ON public.user_integration_connections(persona_id);

-- Persist a real site configuration for personas that previously relied only
-- on the response-time fallback. Existing site configuration is untouched.
WITH site_defaults AS (
  SELECT
    p.id,
    p.slug,
    p.name,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM public.knowledge_nodes n
        WHERE n.persona_id = p.id
          AND n.node_type = 'campaign'
          AND COALESCE(n.status, '') NOT IN ('archived', 'inactive', 'rejected')
      ) THEN 'landing_page'
      WHEN EXISTS (
        SELECT 1
        FROM public.knowledge_nodes n
        WHERE n.persona_id = p.id
          AND n.node_type = 'product_collection'
          AND n.metadata->>'collection_type' = 'catalog'
      ) THEN 'catalogo_roupas'
      ELSE 'cardapio'
    END AS format_key,
    COALESCE(
      (
        SELECT n.slug
        FROM public.knowledge_nodes n
        WHERE n.persona_id = p.id
          AND n.node_type IN ('product_collection', 'campaign')
          AND COALESCE(n.status, '') NOT IN ('archived', 'inactive', 'rejected')
        ORDER BY
          CASE WHEN n.node_type = 'product_collection' THEN 0 ELSE 1 END,
          n.created_at
        LIMIT 1
      ),
      'site-' || p.slug
    ) AS default_collection_slug
  FROM public.personas p
  WHERE NOT COALESCE(p.config, '{}'::jsonb) ? 'public_site'
)
UPDATE public.personas p
SET config = jsonb_set(
      COALESCE(p.config, '{}'::jsonb),
      '{public_site}',
      jsonb_build_object(
        'site_slug', d.slug,
        'site_name', d.name,
        'format_key', d.format_key,
        'default_collection_slug', d.default_collection_slug,
        'whatsapp_phone', '',
        'whatsapp_message_template',
          'Ola, vim pelo site ' || d.name || ' e quero mais informacoes.'
      ),
      true
    ),
    updated_at = now()
FROM site_defaults d
WHERE p.id = d.id;
