-- ============================================================
-- Brain AI Platform - Migration 021
-- Backfill: garante uma system audience "import" por persona com
-- leads existentes, e adiciona membership "primary" para cada lead
-- com persona_id atribuido. Idempotente.
-- ============================================================

-- 1. Cria a system audience "import" para cada persona que tem leads.
INSERT INTO public.audiences (persona_id, slug, name, description, source_type, is_system)
SELECT DISTINCT
  l.persona_id,
  'import' AS slug,
  'Import' AS name,
  'Audiencia padrao para leads importados via CSV ou consolidados antes de segmentacao manual.' AS description,
  'import' AS source_type,
  true AS is_system
FROM public.leads l
WHERE l.persona_id IS NOT NULL
ON CONFLICT (persona_id, slug) DO NOTHING;

-- 2. Para cada lead com persona_id, garante membership primary
--    na audience "import" da sua persona.
INSERT INTO public.lead_audience_memberships (lead_id, audience_id, membership_type)
SELECT
  l.id AS lead_id,
  a.id AS audience_id,
  'primary' AS membership_type
FROM public.leads l
JOIN public.audiences a
  ON a.persona_id = l.persona_id
 AND a.slug = 'import'
WHERE l.persona_id IS NOT NULL
ON CONFLICT (lead_id, audience_id) DO NOTHING;

-- 3. Forca o PostgREST a recarregar o schema cache para que o
--    supabase-py enxergue as tabelas novas sem reiniciar a instancia.
NOTIFY pgrst, 'reload schema';
