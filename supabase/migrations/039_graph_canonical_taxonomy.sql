-- 039_graph_canonical_taxonomy.sql
-- Canonical fractal graph taxonomy.
--
-- Establishes ONE source of truth for node types, relation types, and edge
-- kinds (primary | secondary | asset_pending | asset_approved). Extends the
-- existing registries (009) and reconciles 037's product_collection/category
-- under a single product_group canonical type.
--
-- Idempotent and additive.

-- ── 1. Extend node-type registry with canonical/alias columns ──────

ALTER TABLE public.knowledge_node_type_registry
  ADD COLUMN IF NOT EXISTS alias_of      TEXT,
  ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS canonical     BOOLEAN NOT NULL DEFAULT TRUE;

-- ── 2. Extend relation registry with edge-kind classification ──────

ALTER TABLE public.knowledge_relation_type_registry
  ADD COLUMN IF NOT EXISTS edge_kind          TEXT NOT NULL DEFAULT 'secondary',
  ADD COLUMN IF NOT EXISTS primary_one_to_one BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS canonical          BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.check_constraints
    WHERE constraint_schema = 'public'
      AND constraint_name = 'knowledge_relation_type_registry_edge_kind_check'
  ) THEN
    ALTER TABLE public.knowledge_relation_type_registry
      ADD CONSTRAINT knowledge_relation_type_registry_edge_kind_check
      CHECK (edge_kind IN ('primary','secondary','asset_pending','asset_approved'));
  END IF;
END$$;

-- ── 3. Insert/upsert canonical node types (12) ─────────────────────

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical)
VALUES
  ('persona',       'Persona',        'Raiz cognitiva do grafo. Origem da marca e contexto.',         0,  1.00, '#7c6fff', 'user',          0,  TRUE),
  ('brand',         'Brand',          'Identidade, posicionamento e atributos de marca.',            10, 0.95, '#a78bfa', 'badge',         10, TRUE),
  ('briefing',      'Briefing',       'Contexto estratégico operacional, direto sob Brand.',         20, 0.90, '#c084fc', 'file-text',     20, TRUE),
  ('campaign',      'Campaign',       'Ação comercial ou criativa, direto sob Briefing.',            30, 0.85, '#fb923c', 'megaphone',     30, TRUE),
  ('audience',      'Audience',       'Público-alvo da campanha. Pai semântico do product_group.',   40, 0.80, '#f472b6', 'users',         40, TRUE),
  ('product_group', 'Product Group',  'Categoria/coleção/grupo de produtos. Tipo único canônico.',   50, 0.78, '#34d399', 'folder',        50, TRUE),
  ('product',       'Product',        'Produto específico abaixo de product_group.',                 60, 0.85, '#60a5fa', 'package',       60, TRUE),
  ('offer',         'Offer',          'Proposta comercial aplicada ao produto.',                     70, 0.75, '#facc15', 'tag',           70, TRUE),
  ('copy',          'Copy',           'Argumento textual derivado da offer.',                        80, 0.70, '#64748b', 'text',          80, TRUE),
  ('faq',           'FAQ',            'Saída final textual. Filha direta de copy.',                  90, 0.65, '#4ade80', 'circle-help',   90, TRUE),
  ('gallery',       'Gallery',        'Saída final visual. Filha direta de copy.',                   90, 0.65, '#d946ef', 'image',         91, TRUE),
  ('asset',         'Asset',          'Camada lateral. Pode conectar a qualquer node ou a outro asset.', 95, 0.55, '#f59e0b', 'image', 95, TRUE)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  canonical = TRUE,
  alias_of = NULL,
  deprecated_at = NULL,
  active = TRUE,
  updated_at = now();

-- ── 4. Mark legacy types as aliases of canonical ones ──────────────

UPDATE public.knowledge_node_type_registry
   SET alias_of      = 'product_group',
       canonical     = FALSE,
       deprecated_at = COALESCE(deprecated_at, now()),
       updated_at    = now()
 WHERE node_type IN ('product_collection','category');

-- Non-canonical (kept active for backwards compat but flagged):
UPDATE public.knowledge_node_type_registry
   SET canonical  = FALSE,
       updated_at = now()
 WHERE node_type IN ('entity','tone','rule','tag','knowledge_item','kb_entry','embedded')
   AND canonical IS DISTINCT FROM FALSE;

-- ── 5. Backfill node_type in knowledge_nodes ───────────────────────
-- Convert product_collection / category to product_group canonical type.

UPDATE public.knowledge_nodes
   SET node_type = 'product_group',
       metadata  = COALESCE(metadata, '{}'::jsonb)
                || jsonb_build_object(
                     'legacy_node_type', node_type,
                     'canonicalized_at', now()::text
                   ),
       updated_at = now()
 WHERE node_type IN ('product_collection','category');

-- ── 6. Canonical primary relation graph ────────────────────────────

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types,
   default_weight, directional, sort_order, edge_kind, primary_one_to_one, canonical)
VALUES
  ('brand_has_briefing',        'brand tem briefing',        'briefing de brand',
     '{"brand"}',         '{"briefing"}',       0.95, TRUE,  100, 'primary', TRUE,  TRUE),
  ('briefing_has_campaign',     'briefing tem campanha',     'campanha do briefing',
     '{"briefing"}',      '{"campaign"}',       0.90, TRUE,  110, 'primary', FALSE, TRUE),
  ('campaign_has_audience',     'campanha tem audiência',    'audiência da campanha',
     '{"campaign"}',      '{"audience"}',       0.90, TRUE,  120, 'primary', FALSE, TRUE),
  ('audience_has_product_group','audiência tem grupo',       'grupo da audiência',
     '{"audience"}',      '{"product_group"}',  0.85, TRUE,  130, 'primary', FALSE, TRUE),
  ('product_group_has_product', 'grupo tem produto',         'produto do grupo',
     '{"product_group"}', '{"product"}',        0.85, TRUE,  140, 'primary', FALSE, TRUE),
  ('product_has_offer',         'produto tem oferta',        'oferta do produto',
     '{"product"}',       '{"offer"}',          0.80, TRUE,  150, 'primary', FALSE, TRUE),
  ('offer_has_copy',             'oferta tem copy',          'copy da oferta',
     '{"offer"}',         '{"copy"}',           0.80, TRUE,  160, 'primary', FALSE, TRUE),
  ('copy_has_faq',              'copy tem FAQ',              'FAQ da copy',
     '{"copy"}',          '{"faq"}',            0.80, TRUE,  170, 'primary', TRUE,  TRUE),
  ('copy_has_gallery',          'copy tem gallery',          'gallery da copy',
     '{"copy"}',          '{"gallery"}',        0.80, TRUE,  180, 'primary', TRUE,  TRUE),
  ('persona_has_brand',         'persona tem brand',         'brand da persona',
     '{"persona"}',       '{"brand"}',          1.00, TRUE,   90, 'primary', TRUE,  TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  edge_kind = EXCLUDED.edge_kind,
  primary_one_to_one = EXCLUDED.primary_one_to_one,
  canonical = TRUE,
  active = TRUE,
  updated_at = now();

-- ── 7. Asset lateral relations (pending + approved + gallery) ──────

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types,
   default_weight, directional, sort_order, edge_kind, primary_one_to_one, canonical)
VALUES
  ('asset_pending',   'asset pendente',          'pendência de aprovação',
     '{}', '{"asset"}', 0.50, TRUE, 200, 'asset_pending',  FALSE, TRUE),
  ('asset_approved',  'asset aprovado',          'aprovação de asset',
     '{}', '{"asset"}', 0.90, TRUE, 201, 'asset_approved', FALSE, TRUE),
  ('gallery_has_asset','gallery tem asset',      'asset da gallery',
     '{"gallery"}', '{"asset"}', 0.95, TRUE, 202, 'asset_approved', FALSE, TRUE),
  ('asset_related',   'asset relacionado',       'relacionado',
     '{"asset"}', '{"asset"}', 0.40, FALSE, 203, 'secondary', FALSE, TRUE),
  ('secondary',       'conexão secundária',      'conexão secundária',
     '{}', '{}', 0.30, FALSE, 999, 'secondary', FALSE, TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  edge_kind = EXCLUDED.edge_kind,
  primary_one_to_one = EXCLUDED.primary_one_to_one,
  canonical = TRUE,
  active = TRUE,
  updated_at = now();

-- ── 8. Mark legacy relations as non-canonical aliases ──────────────
-- Legacy hierarchy from 037 (brand_has_collection, collection_has_briefing,
-- collection_has_category, category_has_product, etc) stays active for read
-- compatibility but is flagged so middleware in window 3 can refuse to write
-- new primary edges using them.

UPDATE public.knowledge_relation_type_registry
   SET canonical  = FALSE,
       updated_at = now()
 WHERE relation_type IN (
   'brand_has_collection',
   'collection_has_briefing',
   'collection_has_category',
   'part_of_collection',
   'category_has_product',
   'in_category',
   'product_has_copy',
   'product_has_faq',
   'product_has_asset',
   'product_image',
   'faq_has_embed',
   'defines_brand',
   'has_tone',
   'about_product',
   'part_of_campaign',
   'answers_question',
   'supports_copy',
   'uses_asset',
   'briefed_by',
   'same_topic_as',
   'duplicate_of',
   'derived_from',
   'contains',
   'belongs_to_persona',
   'gallery_asset'
 ) AND canonical IS DISTINCT FROM FALSE;

-- ── 9. Compatibility view exposing canonicalized node_type ─────────

CREATE OR REPLACE VIEW public.knowledge_nodes_canonical AS
SELECT
  n.*,
  COALESCE(r.alias_of, n.node_type) AS canonical_node_type
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_node_type_registry r
  ON r.node_type = n.node_type;

COMMENT ON VIEW public.knowledge_nodes_canonical IS
  'Knowledge nodes exposing canonical_node_type that resolves alias_of from '
  'knowledge_node_type_registry (e.g. product_collection -> product_group).';

-- ── 10. Helper indexes for taxonomy lookup ─────────────────────────

CREATE INDEX IF NOT EXISTS idx_kn_type_registry_canonical
  ON public.knowledge_node_type_registry (canonical, sort_order)
  WHERE canonical = TRUE;

CREATE INDEX IF NOT EXISTS idx_kr_type_registry_edge_kind
  ON public.knowledge_relation_type_registry (edge_kind, canonical, sort_order)
  WHERE canonical = TRUE;
