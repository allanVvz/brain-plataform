-- 036_enforce_asset_graph_contract.sql
-- Asset files shown in marketing/assets must have a Graph node, a branch edge,
-- and an asset -> Gallery edge. This migration keeps the schema aligned with
-- the runtime contract; row repair is handled idempotently by the API because
-- choosing the correct commercial branch requires application semantics.

ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS knowledge_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS gallery_edge_id uuid REFERENCES public.knowledge_edges(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_assets_knowledge_node_id
  ON public.assets(knowledge_node_id)
  WHERE knowledge_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assets_gallery_edge
  ON public.assets(gallery_edge_id);

CREATE INDEX IF NOT EXISTS idx_assets_graph_metadata_node
  ON public.assets((metadata->>'knowledge_node_id'))
  WHERE metadata ? 'knowledge_node_id';

CREATE INDEX IF NOT EXISTS idx_assets_graph_metadata_gallery_edge
  ON public.assets((metadata->>'gallery_edge_id'))
  WHERE metadata ? 'gallery_edge_id';

UPDATE public.knowledge_relation_type_registry
SET
  label = 'na gallery',
  inverse_label = 'contem',
  source_node_types = '{"asset"}',
  target_node_types = '{"gallery"}',
  default_weight = 0.90,
  directional = true,
  sort_order = 82,
  active = true
WHERE relation_type = 'gallery_asset';

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
SELECT
  'gallery_asset',
  'na gallery',
  'contem',
  '{"asset"}',
  '{"gallery"}',
  0.90,
  true,
  82,
  true
WHERE NOT EXISTS (
  SELECT 1 FROM public.knowledge_relation_type_registry WHERE relation_type = 'gallery_asset'
);

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('uses_asset', 'usa asset', 'e usado por', '{"brand","briefing","campaign","audience","product","offer","copy","rule"}', '{"asset"}', 0.85, true, 80, true)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;
