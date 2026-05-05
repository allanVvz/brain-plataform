-- 015_ensure_knowledge_node_primary_edge.sql
-- Ensure every persona-scoped knowledge node has a structural primary edge.

CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type = 'persona' THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
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
    '{"role":"root"}'::jsonb,
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
    '{"primary_tree":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type)
  DO NOTHING;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ensure_knowledge_node_primary_edge ON public.knowledge_nodes;

CREATE TRIGGER trg_ensure_knowledge_node_primary_edge
AFTER INSERT OR UPDATE OF persona_id, node_type
ON public.knowledge_nodes
FOR EACH ROW
EXECUTE FUNCTION public.ensure_knowledge_node_primary_edge();
