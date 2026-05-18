-- 034_repair_faq_edge_direction.sql
-- FAQ is a terminal commercial node. Commercial/context vectors point into FAQ;
-- the only valid outgoing FAQ edge is publication to Embedded.

UPDATE public.knowledge_node_type_registry
SET default_importance = 0.45,
    updated_at = now()
WHERE node_type = 'faq';

UPDATE public.knowledge_relation_type_registry
SET source_node_types = ARRAY['product', 'offer', 'copy', 'campaign', 'audience', 'brand', 'entity'],
    target_node_types = ARRAY['faq', 'kb_entry'],
    updated_at = now()
WHERE relation_type = 'answers_question';

WITH invalid_edges AS (
  SELECT
    e.id,
    e.persona_id,
    e.source_node_id AS faq_node_id,
    e.target_node_id AS parent_node_id,
    e.weight,
    e.metadata
  FROM public.knowledge_edges e
  JOIN public.knowledge_nodes src ON src.id = e.source_node_id
  JOIN public.knowledge_nodes tgt ON tgt.id = e.target_node_id
  WHERE src.node_type = 'faq'
    AND tgt.node_type IN ('product', 'offer', 'copy', 'campaign', 'audience')
    AND COALESCE((e.metadata->>'active')::boolean, true) IS TRUE
)
INSERT INTO public.knowledge_edges (
  persona_id,
  source_node_id,
  target_node_id,
  relation_type,
  weight,
  metadata
)
SELECT
  invalid_edges.persona_id,
  invalid_edges.parent_node_id,
  invalid_edges.faq_node_id,
  'answers_question',
  COALESCE(invalid_edges.weight, 1),
  jsonb_strip_nulls(
    COALESCE(invalid_edges.metadata, '{}'::jsonb)
    || jsonb_build_object(
      'active', true,
      'repaired_from_edge_id', invalid_edges.id,
      'repaired_direction', 'faq_terminal_inbound',
      'created_from', 'migration_034_repair_faq_edge_direction'
    )
    - 'deleted_from'
    - 'deleted_at'
  )
FROM invalid_edges
ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE
SET metadata = jsonb_strip_nulls(
      COALESCE(public.knowledge_edges.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', true,
        'repaired_from_edge_id', EXCLUDED.metadata->>'repaired_from_edge_id',
        'repaired_direction', 'faq_terminal_inbound',
        'reactivated_from', 'migration_034_repair_faq_edge_direction'
      )
    ),
    updated_at = now();

WITH invalid_edges AS (
  SELECT e.id, e.metadata
  FROM public.knowledge_edges e
  JOIN public.knowledge_nodes src ON src.id = e.source_node_id
  JOIN public.knowledge_nodes tgt ON tgt.id = e.target_node_id
  WHERE src.node_type = 'faq'
    AND tgt.node_type IN ('product', 'offer', 'copy', 'campaign', 'audience')
    AND COALESCE((e.metadata->>'active')::boolean, true) IS TRUE
)
UPDATE public.knowledge_edges e
SET metadata = jsonb_strip_nulls(
      COALESCE(e.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', false,
        'primary_tree', false,
        'visual_hidden', true,
        'deleted_from', 'migration_034_repair_faq_edge_direction',
        'deleted_at', now(),
        'invalid_reason', 'faq_terminal_node_cannot_point_to_commercial_parent'
      )
    ),
    updated_at = now()
FROM invalid_edges
WHERE e.id = invalid_edges.id;
