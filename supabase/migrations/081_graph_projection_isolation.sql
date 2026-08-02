-- Isolate reconstructible projections by action destination and graph version.

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical, active)
VALUES
  ('action', 'Action destination', 'Projection-only node for Gallery, Embedded and Marketing destinations.', 100, 0.40, '#a3a3a3', 'share-2', 100, true, true)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  canonical = EXCLUDED.canonical,
  active = true,
  updated_at = now();

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types,
   default_weight, directional, sort_order, edge_kind, primary_one_to_one, canonical, active)
VALUES
  ('contains', 'contém', 'contido por', '{}', '{}', 0.90, true, 300, 'primary', false, true, true),
  ('targets', 'direciona para', 'alvo de', '{}', '{}', 0.85, true, 301, 'secondary', false, true, true),
  ('represents', 'representa', 'representado por', '{}', '{}', 0.90, true, 302, 'secondary', false, true, true),
  ('uses_asset', 'usa asset', 'usado por', '{}', '{asset}', 0.85, true, 303, 'secondary', false, true, true),
  ('supports', 'apoia', 'apoiado por', '{}', '{}', 0.80, true, 304, 'secondary', false, true, true),
  ('answers', 'responde', 'respondido por', '{faq}', '{}', 1.00, true, 305, 'secondary', false, true, true),
  ('applies_to', 'aplica-se a', 'regido por', '{}', '{}', 0.90, true, 306, 'secondary', false, true, true),
  ('derived_from', 'derivado de', 'origem de', '{}', '{}', 0.65, true, 307, 'secondary', false, true, true),
  ('references', 'referencia', 'referenciado por', '{}', '{}', 0.55, true, 308, 'secondary', false, true, true),
  ('publishes_to', 'publica em', 'recebe publicação', '{}', '{action}', 1.00, true, 309, 'secondary', false, true, true)
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
  canonical = EXCLUDED.canonical,
  active = true,
  updated_at = now();

ALTER TABLE public.knowledge_rag_entries
  ADD COLUMN IF NOT EXISTS action_node_id text,
  ADD COLUMN IF NOT EXISTS destination_id text,
  ADD COLUMN IF NOT EXISTS graph_version bigint,
  ADD COLUMN IF NOT EXISTS graph_checksum text,
  ADD COLUMN IF NOT EXISTS projection_status text NOT NULL DEFAULT 'published';

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_projection_status_check;
ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_projection_status_check
  CHECK (projection_status IN ('pending','building','published','withdrawn','failed'));

ALTER TABLE public.knowledge_rag_chunks
  ADD COLUMN IF NOT EXISTS action_node_id text,
  ADD COLUMN IF NOT EXISTS destination_id text,
  ADD COLUMN IF NOT EXISTS graph_version bigint,
  ADD COLUMN IF NOT EXISTS graph_checksum text,
  ADD COLUMN IF NOT EXISTS source_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS projection_status text NOT NULL DEFAULT 'published';

ALTER TABLE public.knowledge_rag_chunks
  DROP CONSTRAINT IF EXISTS knowledge_rag_chunks_projection_status_check;
ALTER TABLE public.knowledge_rag_chunks
  ADD CONSTRAINT knowledge_rag_chunks_projection_status_check
  CHECK (projection_status IN ('pending','building','published','withdrawn','failed'));

ALTER TABLE public.knowledge_rag_links
  ADD COLUMN IF NOT EXISTS action_node_id text,
  ADD COLUMN IF NOT EXISTS destination_id text,
  ADD COLUMN IF NOT EXISTS graph_version bigint,
  ADD COLUMN IF NOT EXISTS graph_checksum text;

UPDATE public.knowledge_rag_entries
SET graph_version = NULLIF(metadata->>'graph_version', '')::bigint,
    graph_checksum = NULLIF(metadata->>'graph_checksum', ''),
    action_node_id = NULLIF(metadata->>'action_node_id', ''),
    destination_id = NULLIF(metadata->>'destination_id', '')
WHERE graph_version IS NULL
  AND COALESCE(metadata->>'graph_version', '') ~ '^[0-9]+$';

UPDATE public.knowledge_rag_chunks c
SET graph_version = e.graph_version,
    graph_checksum = e.graph_checksum,
    action_node_id = e.action_node_id,
    destination_id = e.destination_id,
    source_node_id = e.source_node_id
FROM public.knowledge_rag_entries e
WHERE e.id = c.rag_entry_id;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_rag_entry_action_version_source
  ON public.knowledge_rag_entries(persona_id, action_node_id, graph_version, source_node_id)
  WHERE action_node_id IS NOT NULL AND graph_version IS NOT NULL AND source_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rag_entries_action_version_status
  ON public.knowledge_rag_entries(persona_id, action_node_id, graph_version, projection_status);
CREATE INDEX IF NOT EXISTS idx_rag_entries_destination
  ON public.knowledge_rag_entries(persona_id, destination_id, graph_version);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_action_version_status
  ON public.knowledge_rag_chunks(persona_id, action_node_id, graph_version, projection_status);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_node
  ON public.knowledge_rag_chunks(source_node_id);
CREATE INDEX IF NOT EXISTS idx_rag_links_action_version
  ON public.knowledge_rag_links(persona_id, action_node_id, graph_version);

CREATE OR REPLACE FUNCTION public.validate_knowledge_edge_persona_v2()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_source_persona uuid;
  v_target_persona uuid;
BEGIN
  SELECT persona_id INTO v_source_persona FROM public.knowledge_nodes WHERE id = NEW.source_node_id;
  SELECT persona_id INTO v_target_persona FROM public.knowledge_nodes WHERE id = NEW.target_node_id;
  IF v_source_persona IS DISTINCT FROM v_target_persona
     OR NEW.persona_id IS DISTINCT FROM v_source_persona THEN
    RAISE EXCEPTION 'cross-persona knowledge edge is forbidden'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_knowledge_edge_persona_v2 ON public.knowledge_edges;
CREATE TRIGGER trg_validate_knowledge_edge_persona_v2
BEFORE INSERT OR UPDATE OF persona_id, source_node_id, target_node_id
ON public.knowledge_edges
FOR EACH ROW EXECUTE FUNCTION public.validate_knowledge_edge_persona_v2();

COMMENT ON COLUMN public.knowledge_rag_entries.action_node_id IS
  'Stable Graph JSON action node id that authorized this projection.';
COMMENT ON COLUMN public.knowledge_rag_entries.destination_id IS
  'Consumer destination id, e.g. dataset:sdr-aurora.';
