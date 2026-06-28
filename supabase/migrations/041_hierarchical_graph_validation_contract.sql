-- 041_hierarchical_graph_validation_contract.sql
-- Enforce canonical top-down hierarchy and FAQ->Embed gate.
-- Additive, idempotent, and rollback-friendly.

-- 1) Explicit edge semantics
ALTER TABLE public.knowledge_edges
  ADD COLUMN IF NOT EXISTS edge_type TEXT;

UPDATE public.knowledge_edges e
SET edge_type = CASE
  WHEN COALESCE((e.metadata->>'primary_tree')::boolean, false) = true THEN 'main'
  WHEN r.edge_kind = 'primary' THEN 'main'
  ELSE 'reference'
END
FROM public.knowledge_relation_type_registry r
WHERE e.relation_type = r.relation_type
  AND e.edge_type IS NULL;

UPDATE public.knowledge_edges
SET edge_type = 'reference'
WHERE edge_type IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.check_constraints
    WHERE constraint_schema = 'public'
      AND constraint_name = 'knowledge_edges_edge_type_check'
  ) THEN
    ALTER TABLE public.knowledge_edges
      ADD CONSTRAINT knowledge_edges_edge_type_check
      CHECK (edge_type IN ('main', 'reference'));
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_edge_type
  ON public.knowledge_edges(edge_type);

-- Demote duplicate active main parents before adding uniqueness index.
WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY target_node_id
      ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id
    ) AS rn
  FROM public.knowledge_edges
  WHERE edge_type = 'main'
    AND COALESCE((metadata->>'active')::boolean, true) = true
)
UPDATE public.knowledge_edges e
SET metadata = jsonb_strip_nulls(
      COALESCE(e.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', false,
        'primary_tree', false,
        'visual_hidden', true,
        'demoted_from', 'migration_041_main_parent_uniqueness'
      )
    ),
    updated_at = now()
FROM ranked r
WHERE e.id = r.id
  AND r.rn > 1;

-- One active main parent per child node.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_main_parent_per_child
  ON public.knowledge_edges(target_node_id)
  WHERE edge_type = 'main'
    AND COALESCE((metadata->>'active')::boolean, true) = true;

-- 2) Validation registry for allowed edges
CREATE TABLE IF NOT EXISTS public.knowledge_allowed_edges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  edge_type TEXT NOT NULL CHECK (edge_type IN ('main','reference')),
  requires_source_status TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  rationale TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_type, target_type, edge_type)
);

INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, rationale)
VALUES
  ('persona', 'brand', 'main', NULL, 'Canonical root edge'),
  ('brand', 'briefing', 'main', NULL, 'Canonical hierarchy'),
  ('briefing', 'campaign', 'main', NULL, 'Canonical hierarchy'),
  ('campaign', 'audience', 'main', NULL, 'Canonical hierarchy'),
  ('audience', 'product_group', 'main', NULL, 'Canonical hierarchy'),
  ('product_group', 'product', 'main', NULL, 'Canonical hierarchy'),
  ('product', 'offer', 'main', NULL, 'Canonical hierarchy'),
  ('offer', 'copy', 'main', NULL, 'Canonical hierarchy'),
  ('copy', 'faq', 'main', NULL, 'Canonical hierarchy'),
  ('faq', 'embed', 'main', 'approved', 'Only approved FAQ can create embed')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  rationale = EXCLUDED.rationale,
  active = true,
  updated_at = now();

-- Reference edges are flexible but cannot target embed except approved FAQ.
INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, rationale)
VALUES
  ('faq', 'embed', 'reference', 'approved', 'Reference publication to embed still requires approved FAQ')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  rationale = EXCLUDED.rationale,
  active = true,
  updated_at = now();

-- 3) Validation events + snapshots
CREATE TABLE IF NOT EXISTS public.graph_validation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id UUID REFERENCES public.personas(id) ON DELETE SET NULL,
  edge_id UUID REFERENCES public.knowledge_edges(id) ON DELETE SET NULL,
  source_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  target_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  edge_type TEXT,
  relation_type TEXT,
  error_code TEXT NOT NULL,
  message TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_validation_events_persona_created
  ON public.graph_validation_events(persona_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_validation_events_error_code
  ON public.graph_validation_events(error_code, created_at DESC);

CREATE TABLE IF NOT EXISTS public.graph_validation_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  snapshot_type TEXT NOT NULL DEFAULT 'pre_migration'
    CHECK (snapshot_type IN ('pre_migration','post_migration','manual')),
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_validation_snapshots_persona
  ON public.graph_validation_snapshots(persona_id, created_at DESC);

-- 4) Canonicalize embedded -> embed node type alias
INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical)
VALUES
  ('embed', 'Embed', 'Embedding publication node generated from approved FAQ.', 100, 0.40, '#a3a3a3', 'cpu', 100, true)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  canonical = true,
  active = true,
  updated_at = now();

UPDATE public.knowledge_node_type_registry
SET alias_of = 'embed',
    canonical = false,
    deprecated_at = COALESCE(deprecated_at, now()),
    updated_at = now()
WHERE node_type = 'embedded';

UPDATE public.knowledge_nodes
SET node_type = 'embed',
    metadata = COALESCE(metadata, '{}'::jsonb)
      || jsonb_build_object('legacy_node_type', 'embedded', 'canonicalized_at', now()::text),
    updated_at = now()
WHERE node_type = 'embedded';

-- 5) Validation function and trigger
CREATE OR REPLACE FUNCTION public.validate_knowledge_edge_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  src_type TEXT;
  tgt_type TEXT;
  src_status TEXT;
  src_order INT;
  tgt_order INT;
  allowed_row public.knowledge_allowed_edges%ROWTYPE;
  existing_cycle BOOLEAN;
  err_code TEXT;
  err_message TEXT;
  err_details JSONB;
BEGIN
  SELECT n.node_type, n.status INTO src_type, src_status
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.source_node_id;

  SELECT n.node_type INTO tgt_type
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.target_node_id;

  IF src_type IS NULL OR tgt_type IS NULL THEN
    RAISE EXCEPTION 'Graph validation failed: missing source or target node';
  END IF;

  IF NEW.edge_type = 'main' THEN
    SELECT * INTO allowed_row
    FROM public.knowledge_allowed_edges
    WHERE source_type = src_type
      AND target_type = tgt_type
      AND edge_type = 'main'
      AND active = true
    LIMIT 1;

    IF allowed_row.id IS NULL THEN
      err_code := 'INVALID_MAIN_EDGE';
      err_message := format(
        'Invalid edge: %s cannot connect directly to %s. Expected canonical top-down hierarchy.',
        upper(src_type), upper(tgt_type)
      );
      err_details := jsonb_build_object(
        'source_type', src_type,
        'target_type', tgt_type,
        'edge_type', NEW.edge_type
      );
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    -- Main hierarchy direction cannot move backward.
    SELECT sort_order INTO src_order FROM public.knowledge_node_type_registry WHERE node_type = src_type;
    SELECT sort_order INTO tgt_order FROM public.knowledge_node_type_registry WHERE node_type = tgt_type;
    IF src_order IS NOT NULL AND tgt_order IS NOT NULL AND src_order >= tgt_order THEN
      err_code := 'MAIN_EDGE_BACKWARD';
      err_message := format(
        'Invalid main edge direction: %s (%s) cannot point to %s (%s).',
        upper(src_type), src_order, upper(tgt_type), tgt_order
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'source_order', src_order, 'target_order', tgt_order);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    -- Cycle check only for active main edges.
    IF COALESCE((NEW.metadata->>'active')::boolean, true) = true THEN
      WITH RECURSIVE walk AS (
        SELECT e.target_node_id
        FROM public.knowledge_edges e
        WHERE e.source_node_id = NEW.target_node_id
          AND e.edge_type = 'main'
          AND COALESCE((e.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e.id <> NEW.id)
        UNION ALL
        SELECT e2.target_node_id
        FROM public.knowledge_edges e2
        JOIN walk w ON w.target_node_id = e2.source_node_id
        WHERE e2.edge_type = 'main'
          AND COALESCE((e2.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e2.id <> NEW.id)
      )
      SELECT EXISTS (
        SELECT 1 FROM walk WHERE target_node_id = NEW.source_node_id
      ) INTO existing_cycle;

      IF existing_cycle THEN
        err_code := 'MAIN_EDGE_CYCLE';
        err_message := format('Cycle detected: main edge %s -> %s would create a loop.', NEW.source_node_id, NEW.target_node_id);
        err_details := jsonb_build_object('source_node_id', NEW.source_node_id, 'target_node_id', NEW.target_node_id, 'edge_type', NEW.edge_type);
        INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
        VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
        RAISE EXCEPTION '%', err_message;
      END IF;
    END IF;
  END IF;

  -- Embed target guard for both main/reference.
  IF tgt_type = 'embed' THEN
    IF src_type <> 'faq' THEN
      err_code := 'EMBED_SOURCE_NOT_FAQ';
      err_message := format(
        'Invalid edge: %s cannot connect directly to EMBED. Expected path: PRODUCT -> FAQ -> EMBED with FAQ.status = approved.',
        upper(src_type)
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    IF COALESCE(src_status, '') <> 'approved' THEN
      err_code := 'FAQ_NOT_APPROVED_FOR_EMBED';
      err_message := 'Invalid edge: FAQ must be approved before EMBED creation.';
      err_details := jsonb_build_object('source_status', src_status, 'required_status', 'approved');
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_knowledge_edge_contract ON public.knowledge_edges;
CREATE TRIGGER trg_validate_knowledge_edge_contract
BEFORE INSERT OR UPDATE ON public.knowledge_edges
FOR EACH ROW
EXECUTE FUNCTION public.validate_knowledge_edge_contract();

-- 6) Snapshot existing state before runtime starts rejecting new writes.
INSERT INTO public.graph_validation_snapshots(persona_id, snapshot_type, payload)
SELECT
  n.persona_id,
  'pre_migration',
  jsonb_build_object(
    'nodes', count(DISTINCT n.id),
    'edges', count(DISTINCT e.id),
    'main_edges', count(DISTINCT CASE WHEN e.edge_type = 'main' THEN e.id END),
    'captured_at', now()
  )
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_edges e
  ON e.persona_id = n.persona_id
GROUP BY n.persona_id;
