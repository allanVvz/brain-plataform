-- Migration 134: transactional GraphBundle draft ledger on existing
-- system_events (no new table).
CREATE INDEX IF NOT EXISTS idx_system_events_graph_bundle_draft_revision
  ON public.system_events (entity_id, ((payload->>'revision')::bigint) DESC)
  WHERE entity_type = 'graph_bundle_draft' AND event_type = 'graph_bundle_draft_snapshot';

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_events_graph_bundle_draft_idempotency
  ON public.system_events (entity_id, (payload->>'idempotency_key'))
  WHERE entity_type = 'graph_bundle_draft'
    AND event_type = 'graph_bundle_draft_snapshot'
    AND nullif(payload->>'idempotency_key', '') IS NOT NULL;

CREATE OR REPLACE FUNCTION public.commit_graph_bundle_draft_snapshot(
  p_draft_ref uuid,
  p_persona_id uuid,
  p_expected_revision bigint,
  p_expected_checksum text,
  p_payload jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
DECLARE
  v_current public.system_events%ROWTYPE;
  v_existing public.system_events%ROWTYPE;
  v_inserted public.system_events%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_draft_ref::text));
  SELECT * INTO v_existing FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft'
     AND event_type = 'graph_bundle_draft_snapshot'
     AND entity_id = p_draft_ref::text
     AND payload->>'idempotency_key' = p_payload->>'idempotency_key'
   ORDER BY created_at DESC LIMIT 1;
  IF FOUND THEN
    IF coalesce(v_existing.payload->>'request_fingerprint', '') <>
       coalesce(p_payload->>'request_fingerprint', '') THEN
      RAISE EXCEPTION 'draft idempotency key reused' USING ERRCODE = '40001';
    END IF;
    RETURN v_existing.payload;
  END IF;

  SELECT * INTO v_current FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft'
     AND event_type = 'graph_bundle_draft_snapshot'
     AND entity_id = p_draft_ref::text
   ORDER BY (payload->>'revision')::bigint DESC LIMIT 1 FOR UPDATE;
  IF p_expected_revision = 0 THEN
    IF FOUND THEN RAISE EXCEPTION 'draft already exists' USING ERRCODE = '40001'; END IF;
  ELSIF NOT FOUND
    OR (v_current.payload->>'revision')::bigint <> p_expected_revision
    OR v_current.payload->>'draft_checksum' <> p_expected_checksum THEN
    RAISE EXCEPTION 'draft CAS conflict' USING ERRCODE = '40001';
  END IF;

  INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload)
  VALUES ('graph_bundle_draft_snapshot', 'graph_bundle_draft', p_draft_ref::text, p_persona_id, p_payload)
  RETURNING * INTO v_inserted;
  RETURN v_inserted.payload;
END;
$$;

GRANT EXECUTE ON FUNCTION public.commit_graph_bundle_draft_snapshot(uuid,uuid,bigint,text,jsonb) TO service_role, brain_control_plane;
REVOKE ALL ON FUNCTION public.commit_graph_bundle_draft_snapshot(uuid,uuid,bigint,text,jsonb) FROM PUBLIC, anon, authenticated;

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_events_graph_bundle_publish_idempotency
  ON public.system_events (entity_id, event_type, (payload->>'idempotency_key'))
  WHERE entity_type = 'graph_bundle_draft_publication'
    AND nullif(payload->>'idempotency_key', '') IS NOT NULL;

CREATE OR REPLACE FUNCTION public.checkpoint_graph_bundle_draft_publication(
  p_draft_ref uuid,
  p_persona_id uuid,
  p_publication_id uuid,
  p_runtime_checksum text,
  p_expected_active_publication_id uuid,
  p_expected_active_checksum text,
  p_draft_revision bigint,
  p_draft_checksum text,
  p_idempotency_key text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
DECLARE
  v_existing public.system_events%ROWTYPE;
  v_publication public.graph_publications%ROWTYPE;
  v_active public.graph_publications%ROWTYPE;
  v_payload jsonb;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text));
  SELECT * INTO v_existing FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft_publication'
     AND event_type = 'graph_bundle_draft_publication_staged'
     AND entity_id = p_draft_ref::text
     AND payload->>'idempotency_key' = p_idempotency_key
   LIMIT 1;
  IF FOUND THEN
    IF v_existing.payload->>'publication_id' <> p_publication_id::text
       OR v_existing.payload->>'runtime_checksum' <> p_runtime_checksum
       OR v_existing.payload->>'draft_checksum' <> p_draft_checksum THEN
      RAISE EXCEPTION 'publish idempotency key reused' USING ERRCODE = '40001';
    END IF;
    RETURN v_existing.payload;
  END IF;

  SELECT * INTO v_publication FROM public.graph_publications
   WHERE id = p_publication_id FOR UPDATE;
  IF NOT FOUND OR v_publication.persona_id <> p_persona_id
     OR v_publication.checksum <> p_runtime_checksum
     OR v_publication.status NOT IN ('compiled', 'active') THEN
    RAISE EXCEPTION 'staged publication mismatch' USING ERRCODE = '40001';
  END IF;
  SELECT * INTO v_active FROM public.graph_publications
   WHERE persona_id = p_persona_id AND status = 'active' FOR UPDATE;
  IF NOT FOUND OR v_active.id <> p_expected_active_publication_id
     OR v_active.checksum <> p_expected_active_checksum THEN
    RAISE EXCEPTION 'active publication CAS conflict' USING ERRCODE = '40001';
  END IF;

  v_payload := jsonb_build_object(
    'draft_ref', p_draft_ref, 'persona_id', p_persona_id,
    'publication_id', p_publication_id, 'runtime_checksum', p_runtime_checksum,
    'expected_active_publication_id', p_expected_active_publication_id,
    'expected_active_checksum', p_expected_active_checksum,
    'draft_revision', p_draft_revision, 'draft_checksum', p_draft_checksum,
    'idempotency_key', p_idempotency_key, 'state', 'staged'
  );
  INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload)
  VALUES ('graph_bundle_draft_publication_staged', 'graph_bundle_draft_publication',
          p_draft_ref::text, p_persona_id, v_payload);
  RETURN v_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.activate_graph_bundle_draft_publication(
  p_draft_ref uuid,
  p_persona_id uuid,
  p_publication_id uuid,
  p_runtime_checksum text,
  p_idempotency_key text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
DECLARE
  v_stage public.system_events%ROWTYPE;
  v_existing public.system_events%ROWTYPE;
  v_active public.graph_publications%ROWTYPE;
  v_draft public.system_events%ROWTYPE;
  v_activation jsonb;
  v_payload jsonb;
  v_closed jsonb;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text));
  SELECT * INTO v_existing FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft_publication'
     AND event_type = 'graph_bundle_draft_publication_activated'
     AND entity_id = p_draft_ref::text
     AND payload->>'idempotency_key' = p_idempotency_key
   LIMIT 1;
  IF FOUND THEN RETURN v_existing.payload; END IF;

  SELECT * INTO v_stage FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft_publication'
     AND event_type = 'graph_bundle_draft_publication_staged'
     AND entity_id = p_draft_ref::text
     AND payload->>'idempotency_key' = p_idempotency_key
   LIMIT 1 FOR UPDATE;
  IF NOT FOUND OR v_stage.payload->>'publication_id' <> p_publication_id::text
     OR v_stage.payload->>'runtime_checksum' <> p_runtime_checksum
     OR v_stage.persona_id <> p_persona_id THEN
    RAISE EXCEPTION 'publish checkpoint missing or stale' USING ERRCODE = '40001';
  END IF;

  SELECT * INTO v_active FROM public.graph_publications
   WHERE persona_id = p_persona_id AND status = 'active' FOR UPDATE;
  IF FOUND AND v_active.id = p_publication_id AND v_active.checksum = p_runtime_checksum THEN
    v_activation := jsonb_build_object(
      'publication_id', p_publication_id, 'persona_id', p_persona_id,
      'checksum', p_runtime_checksum, 'status', 'active'
    );
  ELSE
    IF NOT FOUND OR v_active.id::text <> v_stage.payload->>'expected_active_publication_id'
       OR v_active.checksum <> v_stage.payload->>'expected_active_checksum' THEN
      RAISE EXCEPTION 'active publication CAS conflict' USING ERRCODE = '40001';
    END IF;
    v_activation := public.activate_graph_publication_v3(p_publication_id);
  END IF;

  v_payload := v_stage.payload || jsonb_build_object(
    'state', 'active', 'activation', v_activation
  );
  INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload)
  VALUES ('graph_bundle_draft_publication_activated', 'graph_bundle_draft_publication',
          p_draft_ref::text, p_persona_id, v_payload);

  SELECT * INTO v_draft FROM public.system_events
   WHERE entity_type = 'graph_bundle_draft'
     AND event_type = 'graph_bundle_draft_snapshot'
     AND entity_id = p_draft_ref::text
   ORDER BY (payload->>'revision')::bigint DESC LIMIT 1 FOR UPDATE;
  IF FOUND AND v_draft.payload->>'state' = 'draft' THEN
    v_closed := v_draft.payload || jsonb_build_object(
      'revision', (v_draft.payload->>'revision')::bigint + 1,
      'state', 'published', 'publication_id', p_publication_id,
      'published_runtime_checksum', p_runtime_checksum,
      'idempotency_key', 'published:' || p_idempotency_key,
      'request_fingerprint', encode(digest(v_payload::text, 'sha256'), 'hex')
    );
    INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload)
    VALUES ('graph_bundle_draft_snapshot', 'graph_bundle_draft', p_draft_ref::text,
            p_persona_id, v_closed);
  END IF;
  RETURN v_payload;
END;
$$;

GRANT EXECUTE ON FUNCTION public.checkpoint_graph_bundle_draft_publication(uuid,uuid,uuid,text,uuid,text,bigint,text,text)
  TO service_role, brain_control_plane;
GRANT EXECUTE ON FUNCTION public.activate_graph_bundle_draft_publication(uuid,uuid,uuid,text,text)
  TO service_role, brain_control_plane;
REVOKE ALL ON FUNCTION public.checkpoint_graph_bundle_draft_publication(uuid,uuid,uuid,text,uuid,text,bigint,text,text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.activate_graph_bundle_draft_publication(uuid,uuid,uuid,text,text)
  FROM PUBLIC, anon, authenticated;
