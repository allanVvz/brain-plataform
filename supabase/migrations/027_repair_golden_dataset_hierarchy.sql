-- 027_repair_golden_dataset_hierarchy.sql
-- Repairs Golden Dataset graph hierarchy after legacy persona fallback /
-- mention pollution issues. Keeps N8N as RAG consumer; this only fixes graph
-- lineage used to create snapshots and chunks.

CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type IN ('persona', 'embedded', 'gallery', 'tag', 'mention') THEN
    RETURN NEW;
  END IF;

  IF (NEW.metadata ? 'resolved_parent_node_id') THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE e.target_node_id = NEW.id
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
      AND COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
      AND e.relation_type IN (
        'belongs_to_persona',
        'contains',
        'part_of_campaign',
        'about_product',
        'briefed_by',
        'answers_question',
        'supports_copy',
        'uses_asset',
        'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id,
    node_type,
    slug,
    title,
    metadata,
    status
  )
  VALUES (
    NEW.persona_id,
    'persona',
    'self',
    'Persona',
    '{"role":"root","protected":true}'::jsonb,
    'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id,
    source_node_id,
    target_node_id,
    relation_type,
    weight,
    metadata
  )
  VALUES (
    NEW.persona_id,
    persona_node_id,
    NEW.id,
    'belongs_to_persona',
    1,
    '{"primary_tree":true,"active":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type)
  DO NOTHING;

  RETURN NEW;
END;
$$;

-- Mention is auxiliary, never a primary tree node.
UPDATE public.knowledge_nodes
SET metadata = COALESCE(metadata, '{}'::jsonb)
  || jsonb_build_object('visual_hidden', true, 'canonical_auxiliary', true)
WHERE node_type = 'mention';

UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_repair_golden_dataset_hierarchy',
    'deleted_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND (src.node_type = 'mention' OR tgt.node_type = 'mention');

-- Direction is parent -> child. node -> persona belongs edges pollute paths.
UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_node_to_persona_cleanup',
    'deleted_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND tgt.node_type = 'persona'
  AND src.node_type <> 'persona';

-- Restore top-down plan edges incorrectly soft-deleted as graph_ui_reparent.
UPDATE public.knowledge_edges e
SET metadata = (COALESCE(e.metadata, '{}'::jsonb) - 'deleted_at' - 'deleted_from')
  || jsonb_build_object(
    'active', true,
    'primary_tree', true,
    'restored_from', '027_repair_golden_dataset_hierarchy',
    'restored_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND COALESCE(e.metadata->>'deleted_from', '') = 'graph_ui_reparent'
  AND (
    (src.node_type = 'brand' AND tgt.node_type = 'briefing')
    OR (src.node_type = 'briefing' AND tgt.node_type IN ('campaign','audience','product','copy','faq'))
    OR (src.node_type = 'campaign' AND tgt.node_type IN ('audience','product','copy','faq'))
    OR (src.node_type = 'audience' AND tgt.node_type IN ('product','copy','faq'))
    OR (src.node_type = 'product' AND tgt.node_type IN ('copy','faq','asset'))
  );

-- Materialize resolved_parent_node_id as active primary edge.
INSERT INTO public.knowledge_edges (
  persona_id,
  source_node_id,
  target_node_id,
  relation_type,
  weight,
  metadata
)
SELECT
  child.persona_id,
  parent.id,
  child.id,
  CASE
    WHEN parent.node_type = 'product' AND child.node_type = 'faq' THEN 'answers_question'
    WHEN parent.node_type = 'product' AND child.node_type = 'copy' THEN 'supports_copy'
    WHEN parent.node_type = 'product' AND child.node_type = 'asset' THEN 'uses_asset'
    WHEN parent.node_type = 'audience' AND child.node_type = 'product' THEN 'about_product'
    ELSE 'contains'
  END,
  1,
  jsonb_build_object(
    'active', true,
    'primary_tree', true,
    'created_from', '027_resolved_parent_repair',
    'parent_slug', parent.slug,
    'parent_type', parent.node_type
  )
FROM public.knowledge_nodes child
JOIN public.knowledge_nodes parent
  ON parent.id::text = child.metadata->>'resolved_parent_node_id'
WHERE child.node_type NOT IN ('persona','embedded','gallery','tag','mention')
  AND parent.node_type NOT IN ('embedded','gallery','tag','mention')
  AND child.persona_id = parent.persona_id
  AND child.id <> parent.id
ON CONFLICT (source_node_id, target_node_id, relation_type)
DO UPDATE SET
  metadata = (COALESCE(public.knowledge_edges.metadata, '{}'::jsonb) - 'deleted_at' - 'deleted_from')
    || EXCLUDED.metadata,
  weight = EXCLUDED.weight,
  persona_id = EXCLUDED.persona_id;

-- Once a node has a real non-persona primary parent, direct persona fallback
-- edges must be visual-hidden and non-primary.
UPDATE public.knowledge_edges fallback
SET metadata = COALESCE(fallback.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_direct_persona_fallback_cleanup',
    'deleted_at', now()
  )
FROM public.knowledge_nodes persona_node, public.knowledge_nodes child
WHERE fallback.source_node_id = persona_node.id
  AND fallback.target_node_id = child.id
  AND persona_node.node_type = 'persona'
  AND child.node_type NOT IN ('brand','briefing')
  AND COALESCE((fallback.metadata->>'primary_tree')::boolean, false) = true
  AND EXISTS (
    SELECT 1
    FROM public.knowledge_edges real_parent
    JOIN public.knowledge_nodes parent_node ON parent_node.id = real_parent.source_node_id
    WHERE real_parent.target_node_id = child.id
      AND parent_node.node_type <> 'persona'
      AND COALESCE((real_parent.metadata->>'active')::boolean, true) = true
      AND COALESCE((real_parent.metadata->>'primary_tree')::boolean, false) = true
  );

-- Align stale metadata.classification.content_type with the real column.
UPDATE public.knowledge_items
SET metadata = COALESCE(metadata, '{}'::jsonb)
  || jsonb_build_object(
    'classification',
    COALESCE(metadata->'classification', '{}'::jsonb)
      || jsonb_build_object('content_type', content_type)
  )
WHERE metadata ? 'classification'
  AND COALESCE(metadata->'classification'->>'content_type', '') <> content_type;
