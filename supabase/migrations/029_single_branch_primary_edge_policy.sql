-- 029_single_branch_primary_edge_policy.sql
-- Enforce the read-model contract: only one active visible primary_tree edge
-- per source -> target pair. Alternate semantic labels remain hidden lineage.

UPDATE public.knowledge_edges e
SET relation_type = 'offers_product',
    metadata = jsonb_set(
      jsonb_set(COALESCE(e.metadata, '{}'::jsonb), '{canonicalized_relation_from}', to_jsonb(e.relation_type), true),
      '{canonical_relation}', '"audience_product_offers_product"'::jsonb,
      true
    )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND src.node_type = 'audience'
  AND tgt.node_type = 'product'
  AND e.relation_type = 'about_product'
  AND NOT EXISTS (
    SELECT 1
    FROM public.knowledge_edges other
    WHERE other.source_node_id = e.source_node_id
      AND other.target_node_id = e.target_node_id
      AND other.relation_type = 'offers_product'
  );

WITH ranked AS (
  SELECT
    e.id,
    row_number() OVER (
      PARTITION BY e.source_node_id, e.target_node_id
      ORDER BY
        CASE e.relation_type
          WHEN 'offers_product' THEN 0
          WHEN 'supports_copy' THEN 1
          WHEN 'answers_question' THEN 2
          WHEN 'contains' THEN 3
          ELSE 9
        END,
        e.id
    ) AS rn
  FROM public.knowledge_edges e
  WHERE COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
    AND COALESCE((e.metadata->>'active')::boolean, true) = true
    AND COALESCE((e.metadata->>'visual_hidden')::boolean, false) = false
)
UPDATE public.knowledge_edges e
SET metadata =
  jsonb_set(
    jsonb_set(
      jsonb_set(COALESCE(e.metadata, '{}'::jsonb), '{primary_tree}', 'false'::jsonb, true),
      '{visual_hidden}', 'true'::jsonb,
      true
    ),
    '{demoted_from_primary_tree}',
    '"duplicate_source_target_migration_029"'::jsonb,
    true
  )
FROM ranked r
WHERE e.id = r.id
  AND r.rn > 1;
