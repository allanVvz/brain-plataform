-- Atomically activate destination-scoped RAG rows and withdraw prior/legacy rows.

CREATE OR REPLACE FUNCTION public.activate_graph_projection_v2(
  p_persona_slug text,
  p_brand_slug text,
  p_graph_version bigint,
  p_graph_checksum text,
  p_operation_id text,
  p_projections jsonb,
  p_source text DEFAULT 'graph_projector'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_commit public.system_events%ROWTYPE;
  v_persona_id uuid;
  v_activation_id uuid;
BEGIN
  PERFORM pg_advisory_xact_lock(
    hashtextextended('graph-v2:' || p_persona_slug || ':' || COALESCE(p_brand_slug, ''), 0)
  );

  SELECT * INTO v_commit
  FROM public.system_events
  WHERE event_type = 'graph_version_committed'
    AND payload->>'persona_slug' = p_persona_slug
    AND COALESCE(payload->>'brand_slug', '') = COALESCE(p_brand_slug, '')
    AND (payload->>'version')::bigint = p_graph_version
  LIMIT 1;
  IF NOT FOUND OR v_commit.payload->>'checksum' <> p_graph_checksum THEN
    RAISE EXCEPTION 'committed graph version/checksum not found' USING ERRCODE = '23503';
  END IF;
  v_persona_id := v_commit.persona_id;

  -- A v2.1 activation owns the complete active RAG surface for the persona.
  -- Legacy persona-wide rows and previous action versions become historical.
  UPDATE public.knowledge_rag_entries
  SET status = 'withdrawn',
      projection_status = 'withdrawn',
      metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{active}', 'false'::jsonb, true),
      updated_at = now()
  WHERE persona_id = v_persona_id
    AND status IN ('active', 'approved', 'validated', 'embedded')
    AND NOT (
      graph_version = p_graph_version
      AND action_node_id IS NOT NULL
      AND destination_id IS NOT NULL
    );

  UPDATE public.knowledge_rag_chunks c
  SET projection_status = 'withdrawn',
      metadata = jsonb_set(COALESCE(c.metadata, '{}'::jsonb), '{active}', 'false'::jsonb, true)
  FROM public.knowledge_rag_entries e
  WHERE c.rag_entry_id = e.id
    AND e.persona_id = v_persona_id
    AND e.projection_status = 'withdrawn';

  UPDATE public.knowledge_rag_links
  SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{active}', 'false'::jsonb, true)
  WHERE persona_id = v_persona_id
    AND (
      graph_version IS DISTINCT FROM p_graph_version
      OR action_node_id IS NULL
      OR destination_id IS NULL
    );

  UPDATE public.knowledge_rag_entries
  SET status = 'active',
      projection_status = 'published',
      metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{active}', 'true'::jsonb, true),
      updated_at = now()
  WHERE persona_id = v_persona_id
    AND graph_version = p_graph_version
    AND action_node_id IS NOT NULL
    AND destination_id IS NOT NULL;

  UPDATE public.knowledge_rag_chunks c
  SET projection_status = 'published',
      metadata = jsonb_set(COALESCE(c.metadata, '{}'::jsonb), '{active}', 'true'::jsonb, true)
  FROM public.knowledge_rag_entries e
  WHERE c.rag_entry_id = e.id
    AND e.persona_id = v_persona_id
    AND e.graph_version = p_graph_version
    AND e.action_node_id IS NOT NULL
    AND e.destination_id IS NOT NULL;

  UPDATE public.knowledge_rag_links
  SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{active}', 'true'::jsonb, true)
  WHERE persona_id = v_persona_id
    AND graph_version = p_graph_version
    AND action_node_id IS NOT NULL
    AND destination_id IS NOT NULL;

  SELECT id INTO v_activation_id
  FROM public.system_events
  WHERE event_type = 'graph_version_activated'
    AND payload->>'persona_slug' = p_persona_slug
    AND COALESCE(payload->>'brand_slug', '') = COALESCE(p_brand_slug, '')
    AND (payload->>'version')::bigint = p_graph_version
  LIMIT 1;
  IF v_activation_id IS NOT NULL THEN
    RETURN jsonb_build_object(
      'operation_id', p_operation_id, 'graph_version', p_graph_version,
      'checksum', p_graph_checksum, 'status', 'published', 'idempotent_replay', true
    );
  END IF;

  v_activation_id := gen_random_uuid();
  INSERT INTO public.system_events (
    id, event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    v_activation_id,
    'graph_version_activated',
    'graph_document',
    p_persona_slug || ':' || COALESCE(p_brand_slug, 'default') || ':v' || p_graph_version,
    v_persona_id,
    v_commit.payload || jsonb_build_object(
      'graph_json', jsonb_set(v_commit.payload->'graph_json', '{status}', '"published"'::jsonb, true),
      'operation_id', p_operation_id,
      'projections', COALESCE(p_projections, '{}'::jsonb),
      'activated_at', now()
    ),
    'info',
    p_source
  );

  RETURN jsonb_build_object(
    'operation_id', p_operation_id, 'graph_version', p_graph_version,
    'checksum', p_graph_checksum, 'status', 'published',
    'activation_event_id', v_activation_id, 'idempotent_replay', false
  );
END;
$$;

REVOKE ALL ON FUNCTION public.activate_graph_projection_v2(text,text,bigint,text,text,jsonb,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.activate_graph_projection_v2(text,text,bigint,text,text,jsonb,text)
  TO service_role;
