-- Graph JSON v2.1 immutable event store and atomic version allocation.
-- No new table: canonical versions remain in public.system_events.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_graph_v2_committed_scope_version
  ON public.system_events (
    (payload->>'persona_slug'),
    (COALESCE(payload->>'brand_slug', '')),
    (((payload->>'version')::bigint))
  )
  WHERE event_type = 'graph_version_committed';

CREATE UNIQUE INDEX IF NOT EXISTS uniq_graph_v2_activated_scope_version
  ON public.system_events (
    (payload->>'persona_slug'),
    (COALESCE(payload->>'brand_slug', '')),
    (((payload->>'version')::bigint))
  )
  WHERE event_type = 'graph_version_activated';

CREATE UNIQUE INDEX IF NOT EXISTS uniq_graph_v2_commit_idempotency
  ON public.system_events (
    (payload->>'persona_slug'),
    (COALESCE(payload->>'brand_slug', '')),
    (payload->>'idempotency_key')
  )
  WHERE event_type = 'graph_version_committed'
    AND NULLIF(payload->>'idempotency_key', '') IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_graph_v2_projection_action_version
  ON public.system_events (
    (payload->>'persona_slug'),
    (payload->>'action_node_id'),
    (((payload->>'graph_version')::bigint))
  )
  WHERE event_type = 'graph_projection_published';

CREATE OR REPLACE FUNCTION public.prevent_canonical_graph_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF OLD.event_type IN (
    'graph_version_committed',
    'graph_version_activated',
    'graph_projection_published',
    'graph_projection_failed',
    'graph_projection_withdrawn'
  ) THEN
    RAISE EXCEPTION 'canonical graph events are immutable: %', OLD.id
      USING ERRCODE = '55000';
  END IF;
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_canonical_graph_event_mutation
  ON public.system_events;
CREATE TRIGGER trg_prevent_canonical_graph_event_mutation
BEFORE UPDATE OR DELETE ON public.system_events
FOR EACH ROW EXECUTE FUNCTION public.prevent_canonical_graph_event_mutation();

CREATE OR REPLACE FUNCTION public.commit_graph_version_v2(
  p_persona_slug text,
  p_brand_slug text,
  p_expected_version bigint,
  p_idempotency_key text,
  p_reason text,
  p_graph_json jsonb,
  p_content_checksum text,
  p_source text DEFAULT 'graph_documents.commit',
  p_authored_by text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_persona_id uuid;
  v_current_version bigint;
  v_next_version bigint;
  v_operation_id uuid;
  v_existing public.system_events%ROWTYPE;
  v_graph jsonb;
BEGIN
  IF NULLIF(btrim(p_persona_slug), '') IS NULL THEN
    RAISE EXCEPTION 'persona_slug is required' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
    RAISE EXCEPTION 'idempotency_key is required' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'reason is required' USING ERRCODE = '22023';
  END IF;
  IF p_expected_version IS NULL OR p_expected_version < 0 THEN
    RAISE EXCEPTION 'expected_version is required' USING ERRCODE = '22023';
  END IF;

  SELECT id INTO v_persona_id
  FROM public.personas
  WHERE slug = p_persona_slug
  LIMIT 1;
  IF v_persona_id IS NULL THEN
    RAISE EXCEPTION 'persona not found: %', p_persona_slug USING ERRCODE = '23503';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('graph-v2:' || p_persona_slug || ':' || COALESCE(p_brand_slug, ''), 0)
  );

  SELECT * INTO v_existing
  FROM public.system_events
  WHERE event_type = 'graph_version_committed'
    AND payload->>'persona_slug' = p_persona_slug
    AND COALESCE(payload->>'brand_slug', '') = COALESCE(p_brand_slug, '')
    AND payload->>'idempotency_key' = p_idempotency_key
  ORDER BY created_at DESC
  LIMIT 1;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'operation_id', v_existing.id,
      'graph_version', (v_existing.payload->>'version')::bigint,
      'checksum', v_existing.payload->>'checksum',
      'status', 'committed',
      'idempotent_replay', true
    );
  END IF;

  SELECT COALESCE(MAX((payload->>'version')::bigint), 0)
    INTO v_current_version
  FROM public.system_events
  WHERE entity_type = 'graph_document'
    AND event_type IN ('graph_version_committed', 'graph_document_published')
    AND payload->>'persona_slug' = p_persona_slug
    AND COALESCE(payload->>'brand_slug', '') = COALESCE(p_brand_slug, '')
    AND (payload->>'version') ~ '^[0-9]+$';

  IF v_current_version <> p_expected_version THEN
    RAISE EXCEPTION 'GRAPH_VERSION_CONFLICT expected=% current=%',
      p_expected_version, v_current_version
      USING ERRCODE = '40001';
  END IF;

  v_next_version := v_current_version + 1;
  v_operation_id := gen_random_uuid();
  v_graph := jsonb_set(
    jsonb_set(
      jsonb_set(p_graph_json, '{graph_version}', to_jsonb(v_next_version), true),
      '{status}', '"committed"'::jsonb, true
    ),
    '{content_checksum}', to_jsonb(p_content_checksum), true
  );
  v_graph := jsonb_set(
    v_graph,
    '{provenance}',
    COALESCE(v_graph->'provenance', '{}'::jsonb) || jsonb_build_object(
      'source', p_source,
      'authored_by', p_authored_by,
      'base_version', p_expected_version,
      'reason', p_reason,
      'created_at', now()
    ),
    true
  );

  INSERT INTO public.system_events (
    id, event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    v_operation_id,
    'graph_version_committed',
    'graph_document',
    p_persona_slug || ':' || COALESCE(p_brand_slug, 'default') || ':v' || v_next_version,
    v_persona_id,
    jsonb_build_object(
      'persona_slug', p_persona_slug,
      'brand_slug', p_brand_slug,
      'version', v_next_version,
      'checksum', p_content_checksum,
      'graph_json', v_graph,
      'idempotency_key', p_idempotency_key,
      'reason', p_reason,
      'published_by', p_authored_by,
      'source', p_source,
      'operation_id', v_operation_id,
      'committed_at', now()
    ),
    'info',
    p_source
  );

  RETURN jsonb_build_object(
    'operation_id', v_operation_id,
    'graph_version', v_next_version,
    'checksum', p_content_checksum,
    'status', 'committed',
    'idempotent_replay', false
  );
END;
$$;

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

REVOKE ALL ON FUNCTION public.commit_graph_version_v2(text,text,bigint,text,text,jsonb,text,text,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commit_graph_version_v2(text,text,bigint,text,text,jsonb,text,text,text)
  TO service_role;
REVOKE ALL ON FUNCTION public.activate_graph_projection_v2(text,text,bigint,text,text,jsonb,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.activate_graph_projection_v2(text,text,bigint,text,text,jsonb,text)
  TO service_role;
