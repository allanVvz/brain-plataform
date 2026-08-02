-- Record projection events idempotently without emitting unique-key errors on replay.

CREATE OR REPLACE FUNCTION public.record_graph_projection_event_v2(
  p_persona_slug text,
  p_projection jsonb,
  p_source text DEFAULT 'graph_projector'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_persona_id uuid;
  v_existing_id uuid;
  v_event_id uuid;
  v_action_node_id text := NULLIF(p_projection->>'action_node_id', '');
  v_graph_version bigint;
BEGIN
  IF NULLIF(btrim(p_persona_slug), '') IS NULL
     OR v_action_node_id IS NULL
     OR COALESCE(p_projection->>'graph_version', '') !~ '^[0-9]+$' THEN
    RAISE EXCEPTION 'persona, action_node_id and graph_version are required'
      USING ERRCODE = '22023';
  END IF;
  v_graph_version := (p_projection->>'graph_version')::bigint;

  SELECT id INTO v_persona_id
  FROM public.personas
  WHERE slug = p_persona_slug
  LIMIT 1;
  IF v_persona_id IS NULL THEN
    RAISE EXCEPTION 'persona not found: %', p_persona_slug USING ERRCODE = '23503';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('graph-projection:' || p_persona_slug || ':' || v_action_node_id || ':' || v_graph_version, 0)
  );
  SELECT id INTO v_existing_id
  FROM public.system_events
  WHERE event_type = 'graph_projection_published'
    AND payload->>'persona_slug' = p_persona_slug
    AND payload->>'action_node_id' = v_action_node_id
    AND (payload->>'graph_version')::bigint = v_graph_version
  LIMIT 1;
  IF v_existing_id IS NOT NULL THEN
    RETURN jsonb_build_object('event_id', v_existing_id, 'idempotent_replay', true);
  END IF;

  v_event_id := gen_random_uuid();
  INSERT INTO public.system_events (
    id, event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    v_event_id,
    'graph_projection_published',
    'graph_projection',
    p_projection->>'projection_id',
    v_persona_id,
    p_projection,
    'info',
    p_source
  );
  RETURN jsonb_build_object('event_id', v_event_id, 'idempotent_replay', false);
END;
$$;

REVOKE ALL ON FUNCTION public.record_graph_projection_event_v2(text,jsonb,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_graph_projection_event_v2(text,jsonb,text)
  TO service_role;
