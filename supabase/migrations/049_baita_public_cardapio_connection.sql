-- 049_baita_public_cardapio_connection.sql
-- Final public-site identity for the Baita menu renderer.  This is data
-- configuration only; the canonical menu remains knowledge_nodes/edges.

DO $$
DECLARE
  current_config jsonb;
  current_site jsonb;
BEGIN
  SELECT COALESCE(config, '{}'::jsonb)
    INTO current_config
    FROM public.personas
   WHERE slug = 'baita-conveniencia'
   FOR UPDATE;

  IF FOUND THEN
    current_site := COALESCE(current_config->'public_site', '{}'::jsonb);
    current_config := jsonb_set(
      current_config,
      '{public_site}',
      current_site || jsonb_build_object(
        'site_slug', 'baita',
        'site_name', 'Baita',
        'format_key', 'cardapio',
        'default_collection_slug', 'cardapio-baita-v14'
      ),
      true
    );

    UPDATE public.personas
       SET config = current_config,
           catalog_url = CASE
             WHEN catalog_url IS NULL
               OR catalog_url = 'https://baita-cardapio.vercel.app/baita-conveniencia'
             THEN 'https://baita-cardapio.vercel.app/cardapio/baita'
             ELSE catalog_url
           END,
           updated_at = now()
     WHERE slug = 'baita-conveniencia';
  END IF;
END $$;
