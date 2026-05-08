-- ============================================================
-- Brain AI Platform - Migration 022
-- Garante que TODAS as personas (inclusive sem leads) tenham
-- a system audience com slug='import'. Idempotente.
-- ============================================================

-- 1. Cria audience system "import" para toda persona, ainda que sem leads.
INSERT INTO public.audiences (persona_id, slug, name, description, source_type, is_system)
SELECT
  p.id AS persona_id,
  'import' AS slug,
  'Import' AS name,
  'Audiencia padrao para leads importados via CSV ou consolidados antes de segmentacao manual.' AS description,
  'import' AS source_type,
  true AS is_system
FROM public.personas p
ON CONFLICT (persona_id, slug) DO NOTHING;

-- 2. Reaplica o backfill de membership: leads novos sem membership recebem
--    primary na audience import da sua persona. Idempotente.
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

-- 3. Recarrega o schema cache do PostgREST.
NOTIFY pgrst, 'reload schema';
