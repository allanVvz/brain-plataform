-- 028_flexible_marketing_graph_contract.sql
-- Flexible marketing graph contract: entity cards, primary-tree read model,
-- and indexes used by CRIAR/E2E validation.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','other'
  ));

CREATE OR REPLACE VIEW public.knowledge_graph_primary_tree
WITH (security_invoker = true) AS
SELECT *
FROM public.knowledge_edges
WHERE COALESCE((metadata->>'active')::boolean, true) = true
  AND COALESCE((metadata->>'primary_tree')::boolean, false) = true
  AND COALESCE((metadata->>'visual_hidden')::boolean, false) = false;

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_persona_type_slug
  ON public.knowledge_nodes (persona_id, node_type, slug);

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_persona_source_target
  ON public.knowledge_edges (persona_id, source_node_id, target_node_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_persona_content_type
  ON public.knowledge_items (persona_id, content_type);

COMMENT ON VIEW public.knowledge_graph_primary_tree IS
  'Active visible primary-tree edges for CRIAR / graph-data tree rendering.';
