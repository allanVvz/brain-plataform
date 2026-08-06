-- Graph JSON v2.1 publication grants may project any validated graph node to
-- its protected Embedded action. Manual/reference edges keep the historical
-- FAQ-only rule. Both endpoints and the edge must prove the same graph id.

CREATE OR REPLACE FUNCTION public.validate_knowledge_edge_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  src_type TEXT;
  tgt_type TEXT;
  src_status TEXT;
  src_graph_id TEXT;
  tgt_graph_id TEXT;
  src_order INT;
  tgt_order INT;
  existing_parent UUID;
  allowed_row public.knowledge_allowed_edges%ROWTYPE;
  existing_cycle BOOLEAN;
  err_code TEXT;
  err_message TEXT;
  err_details JSONB;
BEGIN
  SELECT n.node_type, n.status, n.metadata->>'graph_json_id'
    INTO src_type, src_status, src_graph_id
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.source_node_id;

  SELECT n.node_type, n.metadata->>'graph_json_id'
    INTO tgt_type, tgt_graph_id
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.target_node_id;

  IF src_type IS NULL OR tgt_type IS NULL THEN
    RAISE EXCEPTION 'Graph validation failed: missing source or target node';
  END IF;

  IF tgt_type = 'embed'
     AND NEW.relation_type = 'publishes_to'
     AND nullif(NEW.metadata->>'graph_json_id', '') IS NOT NULL
     AND NEW.metadata->>'graph_json_id' = src_graph_id
     AND NEW.metadata->>'graph_json_id' = tgt_graph_id
     AND nullif(NEW.metadata->>'graph_json_edge_id', '') IS NOT NULL
     AND src_status IN ('approved', 'validated', 'active', 'ativo') THEN
    RETURN NEW;
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
        'Invalid edge: %s cannot connect directly to EMBED. Expected an approved FAQ or a same-document Graph JSON publication grant.',
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
