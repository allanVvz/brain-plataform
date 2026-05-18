-- 026_approved_knowledge_snapshots_n8n_bridge.sql
-- Canonical approved snapshot bridge:
-- knowledge_nodes/edges -> approved_knowledge_snapshots -> knowledge_rag_entries/chunks.
-- The N8N flow remains the RAG consumer; this migration only gives the
-- backend a durable validation and lineage target.

CREATE TABLE IF NOT EXISTS public.approved_knowledge_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  root_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  source_node_id uuid NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,

  source_table text NOT NULL DEFAULT 'knowledge_nodes',
  source_id uuid,
  artifact_id uuid REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,

  content_type text NOT NULL,
  title text NOT NULL,
  slug text NOT NULL,
  canonical_key text NOT NULL,
  content_hash text NOT NULL,

  hierarchy_path jsonb NOT NULL DEFAULT '[]'::jsonb,
  hierarchy_summary text,
  approved_summary text NOT NULL,
  approved_markdown text NOT NULL,

  parent_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  brand_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  briefing_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  campaign_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  audience_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  product_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  faq_context jsonb NOT NULL DEFAULT '{}'::jsonb,

  rag_entry_id uuid REFERENCES public.knowledge_rag_entries(id) ON DELETE SET NULL,

  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','pending_validation','approved','active','rejected','stale')),

  approved_by uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  approved_at timestamptz,

  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (persona_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_approved_snapshots_persona
  ON public.approved_knowledge_snapshots(persona_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_source_node
  ON public.approved_knowledge_snapshots(source_node_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_status
  ON public.approved_knowledge_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_type
  ON public.approved_knowledge_snapshots(content_type);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_rag_entry
  ON public.approved_knowledge_snapshots(rag_entry_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_hierarchy_path
  ON public.approved_knowledge_snapshots USING gin(hierarchy_path);

ALTER TABLE public.approved_knowledge_snapshots ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.approved_knowledge_snapshots IS
  'Canonical approved tree snapshots that bridge the semantic graph to RAG entries/chunks for N8N retrieval validation.';

-- Protected terminal nodes are visual/publication destinations, not children
-- of the primary semantic tree. Keep the trigger for real knowledge nodes only.
CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type IN ('persona', 'embedded', 'gallery') THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
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

-- Soft-disable legacy terminal primary edges that were created by the old guard.
UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'disabled_from', '026_approved_knowledge_snapshots_n8n_bridge',
    'disabled_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND src.node_type = 'persona'
  AND tgt.node_type IN ('embedded', 'gallery')
  AND e.relation_type = 'belongs_to_persona';
