-- 042_bra20_graph_validation_hardening_draft.sql
-- Draft only: review before apply in QA/PROD.
-- Purpose: harden hierarchical graph validation contracts for BRA-20.

BEGIN;

-- 1) Ensure hierarchy node types include canonical embed.
INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical, active)
VALUES
  ('embed', 'Embed', 'Embedding publication node generated from approved FAQ.', 100, 0.40, '#a3a3a3', 'cpu', 100, true, true)
ON CONFLICT (node_type) DO UPDATE SET
  canonical = true,
  active = true,
  updated_at = now();

-- 2) Ensure allowed-edge matrix exists for strict hierarchy and FAQ->embed gate.
INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, active, rationale)
VALUES
  ('persona', 'brand', 'main', NULL, true, 'Canonical hierarchy'),
  ('brand', 'briefing', 'main', NULL, true, 'Canonical hierarchy'),
  ('briefing', 'campaign', 'main', NULL, true, 'Canonical hierarchy'),
  ('campaign', 'audience', 'main', NULL, true, 'Canonical hierarchy'),
  ('audience', 'product_group', 'main', NULL, true, 'Canonical hierarchy'),
  ('product_group', 'product', 'main', NULL, true, 'Canonical hierarchy'),
  ('product', 'offer', 'main', NULL, true, 'Canonical hierarchy'),
  ('offer', 'copy', 'main', NULL, true, 'Canonical hierarchy'),
  ('copy', 'faq', 'main', NULL, true, 'Canonical hierarchy'),
  ('faq', 'embed', 'main', 'approved', true, 'Only approved FAQ can publish to embed'),
  ('faq', 'embed', 'reference', 'approved', true, 'Only approved FAQ can reference embed')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  active = true,
  rationale = EXCLUDED.rationale,
  updated_at = now();

-- 3) Preserve state snapshots before strict validation adoption.
INSERT INTO public.graph_validation_snapshots(persona_id, snapshot_type, payload)
SELECT
  n.persona_id,
  'manual',
  jsonb_build_object(
    'reason', 'migration_042_pre_hardening',
    'nodes', count(DISTINCT n.id),
    'edges', count(DISTINCT e.id),
    'captured_at', now()
  )
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_edges e ON e.persona_id = n.persona_id
GROUP BY n.persona_id;

-- 4) Validation function patch with explicit main-parent uniqueness code.
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
  existing_parent UUID;
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
    SELECT e.id INTO existing_parent
    FROM public.knowledge_edges e
    WHERE e.target_node_id = NEW.target_node_id
      AND e.edge_type = 'main'
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
      AND (TG_OP <> 'UPDATE' OR e.id <> NEW.id)
    LIMIT 1;

    IF existing_parent IS NOT NULL AND COALESCE((NEW.metadata->>'active')::boolean, true) = true THEN
      err_code := 'MULTIPLE_ACTIVE_MAIN_PARENTS';
      err_message := 'Invalid main edge: child node already has an active main parent.';
      err_details := jsonb_build_object(
        'existing_parent_edge_id', existing_parent,
        'target_node_id', NEW.target_node_id
      );
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    SELECT * INTO allowed_row
    FROM public.knowledge_allowed_edges
    WHERE source_type = src_type
      AND target_type = tgt_type
      AND edge_type = 'main'
      AND active = true
    LIMIT 1;

    IF allowed_row.id IS NULL THEN
      err_code := 'INVALID_MAIN_EDGE';
      err_message := format('Invalid edge: %s cannot connect directly to %s.', upper(src_type), upper(tgt_type));
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'edge_type', NEW.edge_type);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    SELECT sort_order INTO src_order FROM public.knowledge_node_type_registry WHERE node_type = src_type;
    SELECT sort_order INTO tgt_order FROM public.knowledge_node_type_registry WHERE node_type = tgt_type;
    IF src_order IS NOT NULL AND tgt_order IS NOT NULL AND src_order >= tgt_order THEN
      err_code := 'MAIN_EDGE_BACKWARD';
      err_message := 'Invalid main edge direction: source must be above target in hierarchy.';
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'source_order', src_order, 'target_order', tgt_order);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

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
      SELECT EXISTS (SELECT 1 FROM walk WHERE target_node_id = NEW.source_node_id)
      INTO existing_cycle;

      IF existing_cycle THEN
        err_code := 'MAIN_EDGE_CYCLE';
        err_message := 'Invalid main edge: cycle detected.';
        err_details := jsonb_build_object('source_node_id', NEW.source_node_id, 'target_node_id', NEW.target_node_id);
        INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
        VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
        RAISE EXCEPTION '%', err_message;
      END IF;
    END IF;
  END IF;

  IF tgt_type = 'embed' THEN
    IF src_type <> 'faq' THEN
      err_code := 'EMBED_SOURCE_NOT_FAQ';
      err_message := format(
        'Invalid edge: %s cannot connect directly to EMBED. Expected path: PRODUCT -> FAQ -> EMBED with FAQ.status = approved.',
        upper(src_type)
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'edge_type', NEW.edge_type);
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

COMMIT;

-- Rollback (manual):
-- 1) DROP TRIGGER trg_validate_knowledge_edge_contract ON public.knowledge_edges;
-- 2) Optionally restore prior validate_knowledge_edge_contract() body from migration 041.
-- 3) Keep graph_validation_events/snapshots to preserve audit history.
