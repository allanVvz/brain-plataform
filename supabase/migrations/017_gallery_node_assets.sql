-- 017_gallery_node_assets.sql
-- Gallery uses existing graph tables and mirrors connected nodes into assets.

ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS knowledge_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS gallery_edge_id UUID REFERENCES public.knowledge_edges(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_assets_knowledge_node_id
  ON public.assets(knowledge_node_id)
  WHERE knowledge_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assets_gallery_edge
  ON public.assets(gallery_edge_id);

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, active)
VALUES
  ('gallery', 'Gallery', 'Bloco protegido para referencias visuais e materiais de criacao.', 112, 0.82, '#f0abfc', 'images', 112, true),
  ('embedded', 'Embedded', 'Bloco protegido para conteudos enviados ao RAG.', 120, 0.78, '#ffffff', 'database', 120, true)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('gallery_asset', 'na gallery', 'contem', '{"gallery"}', '{"brand","briefing","product","campaign","copy","asset","faq","rule","tone","audience","entity","kb_entry","knowledge_item"}', 0.90, true, 82, true)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;
