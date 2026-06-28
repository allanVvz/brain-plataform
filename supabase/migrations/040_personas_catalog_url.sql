-- 040_personas_catalog_url.sql
-- Adds personas.catalog_url so each persona can point to its public catalog
-- (dashboard /persona surfaces this and the cardapio link uses it directly
-- when present, falling back to NEXT_PUBLIC_CARDAPIO_BASE_URL/{slug}).
--
-- Idempotent and additive. Safe to re-run.

ALTER TABLE public.personas
  ADD COLUMN IF NOT EXISTS catalog_url text;

COMMENT ON COLUMN public.personas.catalog_url IS
  'Public catalog URL for this persona. When NULL the frontend derives the URL '
  'from NEXT_PUBLIC_CARDAPIO_BASE_URL + persona.slug. Set per-persona to point '
  'to a custom domain or a different cardapio deploy.';

-- Seed sensible defaults for personas we know already have catalogs in QA/PROD.
-- INSERT-IF-NULL semantics: never overwrites a value the operator already set.

UPDATE public.personas
   SET catalog_url = 'https://baita-cardapio.vercel.app/baita-conveniencia'
 WHERE slug = 'baita-conveniencia'
   AND catalog_url IS NULL;

UPDATE public.personas
   SET catalog_url = 'https://baita-cardapio-qa.vercel.app/vz-lupas'
 WHERE slug = 'vz-lupas'
   AND catalog_url IS NULL;
