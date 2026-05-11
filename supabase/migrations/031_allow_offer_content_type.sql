-- 031_allow_offer_content_type.sql
-- CRIAR plan mode needs explicit commercial offer nodes between product and copy.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','offer','other'
  ));

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('offer', 'Oferta', 'Preco, quantidade, pacote, kit ou variacao comercial entre produto e copy.', 35, 0.78, '#38bdf8', 'badge-dollar-sign', 45)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

-- Backfill legacy offer mirrors that were materialized as generic
-- knowledge_item nodes before offer became an official graph node type.
UPDATE public.knowledge_nodes n
SET
  node_type = 'offer',
  level = 35,
  importance = 0.78,
  metadata = jsonb_set(
    jsonb_set(
      COALESCE(n.metadata, '{}'::jsonb),
      '{repaired_from_node_type}',
      to_jsonb(n.node_type),
      true
    ),
    '{content_type}',
    '"offer"'::jsonb,
    true
  ),
  updated_at = now()
FROM public.knowledge_items i
WHERE n.source_table = 'knowledge_items'
  AND n.source_id::text = i.id::text
  AND i.content_type = 'offer'
  AND n.node_type <> 'offer';

-- Tags and generic technical mirrors are auxiliary metadata. Existing
-- guard-created persona -> tag edges and stale knowledge_item tree edges
-- must not participate in the primary tree or main visualization.
UPDATE public.knowledge_edges e
SET
  metadata = jsonb_set(
    jsonb_set(
      jsonb_set(
        COALESCE(e.metadata, '{}'::jsonb),
        '{primary_tree}',
        'false'::jsonb,
        true
      ),
      '{graph_layer}',
      '"auxiliary"'::jsonb,
      true
    ),
    '{visual_hidden}',
    'true'::jsonb,
    true
  ),
  updated_at = now()
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE src.id = e.source_node_id
  AND tgt.id = e.target_node_id
  AND (
    src.node_type IN ('tag', 'mention', 'knowledge_item', 'kb_entry')
    OR tgt.node_type IN ('tag', 'mention', 'knowledge_item', 'kb_entry')
  )
  AND COALESCE((e.metadata->>'primary_tree')::boolean, false) = true;
