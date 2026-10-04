-- Control-plane only. No new tables; immutable operation receipts use system_events.
-- Apply separately after Lead review. All editor writes converge on this CAS RPC.

-- Bundle snapshots own explicit edges; suppress the legacy auto-parent trigger.
CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL
     OR NEW.node_type IN ('persona', 'embed', 'embedded', 'gallery', 'tag', 'mention')
     OR COALESCE(NEW.metadata, '{}'::jsonb) ? 'graph_json_id'
     OR (NEW.source_table = 'graph_bundle' AND COALESCE(NEW.metadata, '{}'::jsonb) ? 'graph_json_node_id') THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
      AND e.relation_type IN (
        'belongs_to_persona', 'contains', 'part_of_campaign', 'about_product',
        'briefed_by', 'answers_question', 'supports_copy', 'uses_asset', 'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id, node_type, slug, title, metadata, status
  ) VALUES (
    NEW.persona_id, 'persona', 'self', 'Persona',
    '{"role":"root"}'::jsonb, 'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id, source_node_id, target_node_id, relation_type, weight, metadata
  ) VALUES (
    NEW.persona_id, persona_node_id, NEW.id, 'belongs_to_persona', 1,
    '{"primary_tree":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type) DO NOTHING;

  RETURN NEW;
END;
$$;

-- Receipts and activation lineage survive restarts and retention jobs.
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
    'graph_projection_withdrawn',
    'graph_editor_committed',
    'graph_publication_activated_v1'
  ) THEN
    RAISE EXCEPTION 'canonical graph events are immutable: %', OLD.id
      USING ERRCODE = '55000';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.event_type IN ('graph_editor_committed', 'graph_publication_activated_v1') THEN
    RAISE EXCEPTION 'canonical graph events must be inserted, never updated' USING ERRCODE = '55000';
  END IF;
  RETURN OLD;
END;
$$;


-- Preserve all v3.3 FAQ projection gates; fix lock ordering and record lineage.
CREATE OR REPLACE FUNCTION public.activate_graph_publication_v3(p_publication_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_publication public.graph_publications%ROWTYPE;
  v_previous_id uuid;
  v_branch_count integer;
  v_contract_count integer;
  v_coordinate_count integer;
  v_membership_count integer;
  v_expected_coordinates integer;
  v_expected_memberships integer;
  v_expected_entries integer;
  v_expected_chunks integer;
  v_entry_count integer;
  v_chunk_count integer;
  v_embedded_chunks integer;
  v_missing_faq_projections integer := 0;
BEGIN
  -- Persona advisory lock must precede every publication FOR UPDATE.
  PERFORM pg_advisory_xact_lock(hashtext(persona_id::text))
  FROM public.graph_publications WHERE id = p_publication_id;
  SELECT * INTO v_publication
  FROM public.graph_publications
  WHERE id = p_publication_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'graph publication not found' USING ERRCODE = 'P0002';
  END IF;
  IF v_publication.status NOT IN ('compiled', 'active', 'rolled_back') THEN
    RAISE EXCEPTION 'graph publication is not activatable: %', v_publication.status;
  END IF;

  SELECT count(*)::integer INTO v_expected_coordinates
  FROM jsonb_object_keys(coalesce(v_publication.document_json->'coordinates', '{}'::jsonb));
  SELECT count(*)::integer INTO v_expected_memberships
  FROM jsonb_each(coalesce(v_publication.document_json->'branch_memberships', '{}'::jsonb)) branch
  CROSS JOIN LATERAL jsonb_object_keys(branch.value);
  v_expected_entries := coalesce(
    (v_publication.document_json->'projection_manifest'->>'entry_count')::integer, 0
  );
  v_expected_chunks := coalesce(
    (v_publication.document_json->'projection_manifest'->>'chunk_count')::integer, 0
  );

  SELECT count(*) INTO v_coordinate_count
  FROM public.graph_node_coordinates WHERE publication_id = p_publication_id;
  SELECT count(*), count(DISTINCT branch_node_id)
    INTO v_membership_count, v_branch_count
  FROM public.graph_branch_memberships WHERE publication_id = p_publication_id;
  SELECT count(*) INTO v_contract_count
  FROM public.graph_branch_contracts WHERE publication_id = p_publication_id;
  IF v_expected_coordinates = 0 OR v_coordinate_count <> v_expected_coordinates THEN
    RAISE EXCEPTION 'graph coordinates are incomplete (% actual / % expected)',
      v_coordinate_count, v_expected_coordinates;
  END IF;
  IF v_expected_memberships = 0 OR v_membership_count <> v_expected_memberships THEN
    RAISE EXCEPTION 'branch memberships are incomplete (% actual / % expected)',
      v_membership_count, v_expected_memberships;
  END IF;
  IF v_branch_count = 0 OR v_contract_count <> v_branch_count THEN
    RAISE EXCEPTION 'branch contracts are incomplete (% contracts / % branches)',
      v_contract_count, v_branch_count;
  END IF;

  SELECT count(*) INTO v_entry_count
  FROM public.knowledge_rag_entries
  WHERE publication_id = p_publication_id
    AND projection_status IN ('ready', 'published');
  SELECT count(*), count(*) FILTER (WHERE embedding IS NOT NULL AND embedded_at IS NOT NULL)
    INTO v_chunk_count, v_embedded_chunks
  FROM public.knowledge_rag_chunks
  WHERE publication_id = p_publication_id
    AND projection_status IN ('ready', 'published');
  IF v_expected_entries = 0 OR v_entry_count <> v_expected_entries THEN
    RAISE EXCEPTION 'RAG entries are incomplete (% actual / % expected)',
      v_entry_count, v_expected_entries;
  END IF;
  IF v_expected_chunks = 0 OR v_chunk_count <> v_expected_chunks
     OR v_chunk_count <> v_embedded_chunks THEN
    RAISE EXCEPTION 'required embeddings are incomplete (% embedded / % actual / % expected)',
      v_embedded_chunks, v_chunk_count, v_expected_chunks;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM public.knowledge_rag_chunks c
    LEFT JOIN public.graph_branch_memberships m
      ON m.publication_id = c.publication_id
     AND m.branch_node_id = c.branch_anchor_node_id
     AND m.node_id = c.source_graph_node_id
    WHERE c.publication_id = p_publication_id AND m.node_id IS NULL
  ) THEN
    RAISE EXCEPTION 'RAG chunk exists outside compiled branch membership';
  END IF;

  IF v_publication.document_json->>'faq_projection_contract' = 'v1' THEN
    WITH expected AS (
      SELECT branch.key AS branch_node_id, faq.value AS faq_node_id
      FROM jsonb_each(coalesce(v_publication.document_json->'branch_contracts', '{}'::jsonb)) branch
      CROSS JOIN LATERAL jsonb_array_elements_text(
        coalesce(branch.value->'eligible_faq_node_ids', '[]'::jsonb)
      ) faq(value)
    )
    SELECT count(*) INTO v_missing_faq_projections
    FROM expected e
    WHERE NOT EXISTS (
      SELECT 1 FROM public.graph_branch_memberships m
      WHERE m.publication_id = p_publication_id
        AND m.branch_node_id = e.branch_node_id AND m.node_id = e.faq_node_id
    ) OR NOT EXISTS (
      SELECT 1 FROM public.knowledge_rag_entries r
      WHERE r.publication_id = p_publication_id
        AND r.source_graph_node_id = e.faq_node_id
        AND r.projection_status IN ('ready', 'published')
    ) OR NOT EXISTS (
      SELECT 1 FROM public.knowledge_rag_chunks c
      WHERE c.publication_id = p_publication_id
        AND c.branch_anchor_node_id = e.branch_node_id
        AND c.source_graph_node_id = e.faq_node_id
        AND c.chunk_kind = 'faq'
        AND nullif(btrim(c.metadata->>'faq_question'), '') IS NOT NULL
        AND nullif(btrim(c.metadata->>'faq_answer'), '') IS NOT NULL
        AND c.metadata->>'faq_projection_contract' = 'v1'
        AND c.projection_status IN ('ready', 'published')
        AND c.embedding IS NOT NULL AND c.embedded_at IS NOT NULL
    );
    IF v_missing_faq_projections > 0 THEN
      RAISE EXCEPTION 'FAQ projections are incomplete (% branch/FAQ pairs missing)',
        v_missing_faq_projections;
    END IF;
  END IF;

  SELECT id INTO v_previous_id FROM public.graph_publications
  WHERE persona_id = v_publication.persona_id AND status = 'active';
  UPDATE public.graph_publications
  SET status = 'rolled_back'
  WHERE persona_id = v_publication.persona_id AND status = 'active' AND id <> p_publication_id;
  UPDATE public.graph_publications
  SET status = 'active', activated_at = coalesce(activated_at, now())
  WHERE id = p_publication_id;

  IF v_previous_id IS DISTINCT FROM p_publication_id THEN
    INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload, created_at)
    VALUES ('graph_publication_activated_v1', 'graph_publication', p_publication_id::text,
      v_publication.persona_id, jsonb_build_object('previous_publication_id', v_previous_id), clock_timestamp());
  END IF;

  RETURN jsonb_build_object(
    'publication_id', p_publication_id, 'persona_id', v_publication.persona_id,
    'version', v_publication.version, 'checksum', v_publication.checksum,
    'status', 'active', 'entry_count', v_entry_count, 'chunk_count', v_chunk_count,
    'faq_projection_contract', v_publication.document_json->>'faq_projection_contract'
  );
END;
$$;



CREATE UNIQUE INDEX IF NOT EXISTS graph_editor_receipt_key
ON public.system_events (persona_id, (payload->>'idempotency_key'))
WHERE event_type = 'graph_editor_committed';

CREATE OR REPLACE FUNCTION public.graph_editor_receipt_v1(
  p_persona_id uuid, p_actor text, p_idempotency_key text,
  p_operation text, p_base_publication_id uuid, p_request_hash text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_payload jsonb;
BEGIN
  IF p_persona_id IS NULL OR nullif(btrim(p_actor), '') IS NULL
     OR nullif(btrim(p_idempotency_key), '') IS NULL OR length(p_idempotency_key) > 128
     OR p_operation IS NULL OR p_operation NOT IN ('save', 'revert', 'publish')
     OR (p_base_publication_id IS NULL AND p_operation <> 'publish') OR p_request_hash IS NULL
     OR p_request_hash !~ '^sha256:[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'graph_editor_invalid_request' USING ERRCODE = '22023';
  END IF;
  SELECT payload INTO v_payload FROM public.system_events
  WHERE persona_id = p_persona_id AND event_type = 'graph_editor_committed'
    AND payload->>'idempotency_key' = p_idempotency_key;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF v_payload->>'actor' IS DISTINCT FROM p_actor
     OR v_payload->>'operation' IS DISTINCT FROM p_operation
     OR v_payload->>'base_publication_id' IS DISTINCT FROM p_base_publication_id::text
     OR v_payload->>'request_hash' IS DISTINCT FROM p_request_hash THEN
    RAISE EXCEPTION 'graph_editor_idempotency_conflict' USING ERRCODE = '40001';
  END IF;
  RETURN v_payload->'result';
END;
$$;

ALTER TABLE public.graph_publications
  ADD COLUMN IF NOT EXISTS editor_lease_token uuid,
  ADD COLUMN IF NOT EXISTS editor_lease_until timestamptz;
ALTER TABLE public.graph_node_coordinates ADD COLUMN IF NOT EXISTS editor_lease_token uuid;
ALTER TABLE public.graph_branch_memberships ADD COLUMN IF NOT EXISTS editor_lease_token uuid;
ALTER TABLE public.graph_branch_contracts ADD COLUMN IF NOT EXISTS editor_lease_token uuid;

CREATE OR REPLACE FUNCTION public.guard_graph_publication_lease_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE v_publication uuid; v_token uuid; v_expected uuid; v_status text;
BEGIN
  IF TG_TABLE_NAME IN ('knowledge_rag_entries','knowledge_rag_chunks') THEN
    v_publication := NEW.publication_id;
    v_token := nullif(NEW.metadata->>'editor_lease_token','')::uuid;
  ELSE
    v_publication := NEW.publication_id;
    v_token := NEW.editor_lease_token;
  END IF;
  IF v_publication IS NULL THEN RETURN NEW; END IF;
  IF v_token IS NULL THEN
    RAISE EXCEPTION 'graph_publication_lease_required' USING ERRCODE = '40001';
  END IF;
  SELECT editor_lease_token, status INTO v_expected, v_status
  FROM public.graph_publications WHERE id = v_publication FOR SHARE;
  IF v_status IS DISTINCT FROM 'building' OR v_token IS DISTINCT FROM v_expected THEN
    RAISE EXCEPTION 'graph_publication_lease_lost' USING ERRCODE = '40001';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_graph_publication_lease_coordinates ON public.graph_node_coordinates;
CREATE TRIGGER trg_graph_publication_lease_coordinates BEFORE INSERT OR UPDATE ON public.graph_node_coordinates
FOR EACH ROW EXECUTE FUNCTION public.guard_graph_publication_lease_v1();
DROP TRIGGER IF EXISTS trg_graph_publication_lease_memberships ON public.graph_branch_memberships;
CREATE TRIGGER trg_graph_publication_lease_memberships BEFORE INSERT OR UPDATE ON public.graph_branch_memberships
FOR EACH ROW EXECUTE FUNCTION public.guard_graph_publication_lease_v1();
DROP TRIGGER IF EXISTS trg_graph_publication_lease_contracts ON public.graph_branch_contracts;
CREATE TRIGGER trg_graph_publication_lease_contracts BEFORE INSERT OR UPDATE ON public.graph_branch_contracts
FOR EACH ROW EXECUTE FUNCTION public.guard_graph_publication_lease_v1();
DROP TRIGGER IF EXISTS trg_graph_publication_lease_rag_entries ON public.knowledge_rag_entries;
CREATE TRIGGER trg_graph_publication_lease_rag_entries BEFORE INSERT OR UPDATE ON public.knowledge_rag_entries
FOR EACH ROW EXECUTE FUNCTION public.guard_graph_publication_lease_v1();
DROP TRIGGER IF EXISTS trg_graph_publication_lease_rag_chunks ON public.knowledge_rag_chunks;
CREATE TRIGGER trg_graph_publication_lease_rag_chunks BEFORE INSERT OR UPDATE ON public.knowledge_rag_chunks
FOR EACH ROW EXECUTE FUNCTION public.guard_graph_publication_lease_v1();

CREATE OR REPLACE FUNCTION public.reserve_graph_publication_v1(p_persona_id uuid, p_document jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_publication public.graph_publications%ROWTYPE; v_node jsonb;
  v_existing public.knowledge_nodes%ROWTYPE; v_token uuid := gen_random_uuid();
BEGIN
  IF p_persona_id IS NULL OR p_document->'persona'->>'id' IS DISTINCT FROM p_persona_id::text
     OR coalesce(p_document->>'checksum', '') !~ '^sha256:[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'graph_editor_persona_scope_mismatch' USING ERRCODE = '22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text));
  SELECT * INTO v_publication FROM public.graph_publications
  WHERE persona_id = p_persona_id AND checksum = p_document->>'checksum' FOR UPDATE;
  IF FOUND THEN
    IF v_publication.document_json IS DISTINCT FROM p_document THEN
      RAISE EXCEPTION 'graph_publication_checksum_collision' USING ERRCODE = '23505';
    END IF;
    IF v_publication.status IN ('compiled','active','rolled_back') THEN
      RETURN jsonb_build_object('publication',to_jsonb(v_publication),'owned',false,'lease_token',NULL);
    END IF;
    IF v_publication.status = 'building' AND v_publication.editor_lease_until > clock_timestamp() THEN
      RAISE EXCEPTION 'graph_candidate_build_in_progress' USING ERRCODE = '40001';
    END IF;
    UPDATE public.graph_publications SET status='building', editor_lease_token=v_token,
      editor_lease_until=clock_timestamp()+interval '15 minutes'
    WHERE id=v_publication.id RETURNING * INTO v_publication;
  ELSE
    FOR v_node IN SELECT value FROM jsonb_array_elements(p_document->'nodes') LOOP
      SELECT * INTO v_existing FROM public.knowledge_nodes WHERE id=(v_node->>'projection_node_id')::uuid;
      IF FOUND THEN
        IF v_existing.persona_id IS DISTINCT FROM p_persona_id THEN
          RAISE EXCEPTION 'graph_editor_projection_scope_mismatch' USING ERRCODE = '22023';
        END IF;
      ELSE
        INSERT INTO public.knowledge_nodes(id,persona_id,node_type,slug,title,status,source_table,metadata)
        VALUES ((v_node->>'projection_node_id')::uuid,p_persona_id,v_node->>'node_type',v_node->>'slug',
          v_node->>'title','pending_validation','graph_bundle',
          jsonb_build_object('graph_json_node_id',v_node->>'id','editor_staging',true));
      END IF;
    END LOOP;
    INSERT INTO public.graph_publications(persona_id,version,checksum,document_json,status,compiler_version,
      editor_lease_token,editor_lease_until)
    SELECT p_persona_id,coalesce(max(version),0)+1,p_document->>'checksum',p_document,'building',
      p_document->>'compiler_version',v_token,clock_timestamp()+interval '15 minutes'
    FROM public.graph_publications WHERE persona_id=p_persona_id RETURNING * INTO v_publication;
  END IF;
  RETURN jsonb_build_object('publication',to_jsonb(v_publication),'owned',true,'lease_token',v_token);
END;
$$;

CREATE OR REPLACE FUNCTION public.finish_graph_publication_build_v1(
  p_publication_id uuid,p_lease_token uuid,p_failed boolean DEFAULT false
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public,pg_temp AS $$
DECLARE v_status text;
BEGIN
  UPDATE public.graph_publications SET status=CASE WHEN p_failed THEN 'failed' ELSE 'compiled' END,
    editor_lease_token=NULL,editor_lease_until=NULL
  WHERE id=p_publication_id AND status='building' AND editor_lease_token=p_lease_token
  RETURNING status INTO v_status;
  IF NOT FOUND THEN RAISE EXCEPTION 'graph_publication_lease_lost' USING ERRCODE = '40001'; END IF;
  RETURN NOT p_failed;
END;
$$;

-- JSON object encoders may collapse 1.0 into 1. Return the stored JSONB text
-- as a string so the Python compiler verifies the original numeric spelling.
CREATE OR REPLACE FUNCTION public.read_graph_editor_publication_v1(p_persona_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_row public.graph_publications%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM public.graph_publications WHERE persona_id=p_persona_id AND status='active';
  IF NOT FOUND THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('publication',to_jsonb(v_row)-'document_json',
    'document_text',v_row.document_json::text);
END;
$$;
REVOKE ALL ON FUNCTION public.read_graph_editor_publication_v1(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.read_graph_editor_publication_v1(uuid) TO service_role;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='brain_control_plane') THEN
    GRANT EXECUTE ON FUNCTION public.read_graph_editor_publication_v1(uuid) TO brain_control_plane;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.graph_editor_previous_v1(p_persona_id uuid, p_active_publication_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_previous uuid; v_row public.graph_publications%ROWTYPE;
BEGIN
  SELECT (payload->>'previous_publication_id')::uuid INTO v_previous
  FROM public.system_events WHERE persona_id = p_persona_id
    AND event_type = 'graph_publication_activated_v1' AND entity_id = p_active_publication_id::text
  ORDER BY created_at DESC, id DESC LIMIT 1;
  -- A legacy activation has no reliable predecessor: fail closed, never guess
  -- lineage from activated_at (which used to preserve the first activation).
  IF v_previous IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO v_row FROM public.graph_publications WHERE id = v_previous AND persona_id = p_persona_id;
  RETURN CASE WHEN FOUND THEN jsonb_build_object('id', v_row.id, 'version', v_row.version,
    'checksum', v_row.checksum, 'status', v_row.status, 'activated_at', v_row.activated_at) ELSE NULL END;
END;
$$;

CREATE OR REPLACE FUNCTION public.commit_graph_editor_v1(
  p_persona_id uuid, p_publication_id uuid, p_base_publication_id uuid,
  p_actor text, p_idempotency_key text, p_request_hash text,
  p_operation text, p_runtime_checksum text, p_audit jsonb DEFAULT '{}'
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_result jsonb; v_active uuid; v_previous jsonb; v_activation jsonb;
  v_candidate public.graph_publications%ROWTYPE; v_base_document jsonb; v_node jsonb; v_edge jsonb;
  v_source uuid; v_target uuid;
BEGIN
  IF p_persona_id IS NULL THEN
    RAISE EXCEPTION 'graph_editor_persona_scope_mismatch' USING ERRCODE = '22023';
  END IF;
  -- Same lock as the canonical activation and version reservation, before any
  -- publication row lock. Concurrent processes/containers share this gate.
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text));
  v_result := public.graph_editor_receipt_v1(p_persona_id, p_actor, p_idempotency_key,
    p_operation, p_base_publication_id, p_request_hash);
  IF v_result IS NOT NULL THEN RETURN v_result; END IF;
  SELECT id INTO v_active FROM public.graph_publications WHERE persona_id = p_persona_id AND status = 'active';
  IF v_active IS DISTINCT FROM p_base_publication_id THEN
    RAISE EXCEPTION 'graph_editor_base_not_active' USING ERRCODE = '40001';
  END IF;
  SELECT document_json INTO v_base_document FROM public.graph_publications WHERE id = v_active;
  SELECT * INTO v_candidate FROM public.graph_publications WHERE id = p_publication_id FOR UPDATE;
  IF NOT FOUND OR v_candidate.persona_id IS DISTINCT FROM p_persona_id
     OR v_candidate.checksum IS DISTINCT FROM p_runtime_checksum THEN
    RAISE EXCEPTION 'graph_editor_candidate_scope_or_checksum_mismatch' USING ERRCODE = '22023';
  END IF;
  IF v_candidate.status NOT IN ('compiled','active','rolled_back') THEN
    RAISE EXCEPTION 'graph_editor_candidate_not_ready' USING ERRCODE = '40001';
  END IF;
  IF p_operation = 'revert' THEN
    v_previous := public.graph_editor_previous_v1(p_persona_id, v_active);
    IF v_previous->>'id' IS DISTINCT FROM p_publication_id::text THEN
      RAISE EXCEPTION 'graph_editor_revert_target_not_previous' USING ERRCODE = '40001';
    END IF;
  END IF;
  -- Keep the canonical coordinates/memberships/contracts/embeddings/FAQ gates.
  -- Any later source/receipt error rolls activation back in this transaction.
  v_activation := public.activate_graph_publication_v3(p_publication_id);
  -- Nodes removed by this publication cease to be eligible. Never retire an
  -- unrelated conversation/asset/source node outside the replaced snapshot.
  UPDATE public.knowledge_nodes n SET status = 'pending_validation'
  WHERE n.persona_id = p_persona_id AND n.id IN (
    SELECT (value->>'projection_node_id')::uuid FROM jsonb_array_elements(v_base_document->'nodes')
  ) AND n.id NOT IN (
    SELECT (value->>'projection_node_id')::uuid FROM jsonb_array_elements(v_candidate.document_json->'nodes')
  );
  FOR v_node IN SELECT value FROM jsonb_array_elements(v_candidate.document_json->'nodes') LOOP
    IF EXISTS (SELECT 1 FROM public.knowledge_nodes WHERE id = (v_node->>'projection_node_id')::uuid
      AND persona_id IS DISTINCT FROM p_persona_id) THEN
      RAISE EXCEPTION 'graph_editor_projection_scope_mismatch' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.knowledge_nodes(id, persona_id, node_type, slug, title, summary, tags, status, source_table, metadata)
    VALUES ((v_node->>'projection_node_id')::uuid, p_persona_id, v_node->>'node_type', v_node->>'slug',
      v_node->>'title', coalesce(v_node->>'summary', ''),
      ARRAY(SELECT jsonb_array_elements_text(coalesce(v_node->'tags', '[]'))),
      v_node->>'status', 'graph_bundle', coalesce(v_node->'data', '{}') || jsonb_build_object('graph_json_node_id', v_node->>'id'))
    ON CONFLICT (id) DO UPDATE SET node_type = EXCLUDED.node_type, slug = EXCLUDED.slug,
      title = EXCLUDED.title, summary = EXCLUDED.summary, tags = EXCLUDED.tags,
      status = EXCLUDED.status, source_table = EXCLUDED.source_table, metadata = EXCLUDED.metadata || CASE WHEN knowledge_nodes.metadata ? 'graph_position'
        THEN jsonb_build_object('graph_position',knowledge_nodes.metadata->'graph_position') ELSE '{}'::jsonb END;
  END LOOP;
  -- Replace only edges from the base inventory. External edges arriving after
  -- preflight are preserved; IDs and audit history survive soft removal.
  UPDATE public.knowledge_edges SET metadata = coalesce(metadata, '{}') || '{"active":false}'::jsonb
  WHERE persona_id = p_persona_id AND coalesce((metadata->>'active')::boolean, true)
    AND (source_node_id, target_node_id, relation_type) IN (
      SELECT (v_base_document->'node_by_id'->(e->>'source')->>'projection_node_id')::uuid,
        (v_base_document->'node_by_id'->(e->>'target')->>'projection_node_id')::uuid, e->>'relation_type'
      FROM jsonb_array_elements(v_base_document->'edges') e
    );
  FOR v_edge IN SELECT value FROM jsonb_array_elements(v_candidate.document_json->'edges') LOOP
    v_source := (v_candidate.document_json->'node_by_id'->(v_edge->>'source')->>'projection_node_id')::uuid;
    v_target := (v_candidate.document_json->'node_by_id'->(v_edge->>'target')->>'projection_node_id')::uuid;
    IF v_source IS NULL OR v_target IS NULL OR EXISTS (
      SELECT 1 FROM public.knowledge_nodes WHERE id IN (v_source, v_target) AND persona_id IS DISTINCT FROM p_persona_id
    ) THEN RAISE EXCEPTION 'graph_editor_edge_scope_mismatch' USING ERRCODE = '22023'; END IF;
    INSERT INTO public.knowledge_edges(persona_id, source_node_id, target_node_id, relation_type, edge_type, weight, metadata)
    VALUES (p_persona_id, v_source, v_target, v_edge->>'relation_type',
      CASE WHEN (v_edge->>'primary')::boolean THEN 'main' ELSE 'reference' END,
      (v_edge->>'weight')::numeric,
      coalesce(v_edge->'metadata', '{}') || jsonb_build_object('active', true,
        'primary_tree', (v_edge->>'primary')::boolean, 'graph_json_edge_id', v_edge->>'id'))
    ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE SET
      persona_id = EXCLUDED.persona_id, edge_type = EXCLUDED.edge_type,
      weight = EXCLUDED.weight, metadata = EXCLUDED.metadata;
  END LOOP;
  v_result := jsonb_build_object('publication_id', p_publication_id, 'version', v_candidate.version) ||
    CASE WHEN p_operation = 'save' THEN jsonb_build_object('previous_publication_id', v_active)
    ELSE jsonb_build_object('reverted_from_publication_id', v_active) END;
  INSERT INTO public.system_events(event_type, entity_type, entity_id, persona_id, payload)
  VALUES ('graph_editor_committed', 'graph_publication', p_publication_id::text, p_persona_id,
    jsonb_build_object('actor', p_actor, 'idempotency_key', p_idempotency_key, 'request_hash', p_request_hash,
      'operation', p_operation, 'base_publication_id', p_base_publication_id,
      'result', v_result, 'activation', v_activation, 'audit', p_audit));
  RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION public.graph_editor_receipt_v1(uuid,text,text,text,uuid,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reserve_graph_publication_v1(uuid,jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finish_graph_publication_build_v1(uuid,uuid,boolean) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.graph_editor_previous_v1(uuid,uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.commit_graph_editor_v1(uuid,uuid,uuid,text,text,text,text,text,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.graph_editor_receipt_v1(uuid,text,text,text,uuid,text),
  public.reserve_graph_publication_v1(uuid,jsonb), public.graph_editor_previous_v1(uuid,uuid),
  public.finish_graph_publication_build_v1(uuid,uuid,boolean), public.commit_graph_editor_v1(uuid,uuid,uuid,text,text,text,text,text,jsonb) TO service_role;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brain_control_plane') THEN
    GRANT EXECUTE ON FUNCTION public.graph_editor_receipt_v1(uuid,text,text,text,uuid,text) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.reserve_graph_publication_v1(uuid,jsonb) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.finish_graph_publication_build_v1(uuid,uuid,boolean) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.graph_editor_previous_v1(uuid,uuid) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.commit_graph_editor_v1(uuid,uuid,uuid,text,text,text,text,text,jsonb) TO brain_control_plane;
  END IF;
END $$;

-- Only the transactional writer may activate. Old direct writers fail closed;
-- existing conversation/runtime reads remain compatible throughout cutover.
DO $restrict$ DECLARE v_role text; v_function regprocedure; BEGIN
  FOR v_function IN SELECT oid::regprocedure FROM pg_proc
    WHERE oid IN ('public.activate_graph_publication_v3(uuid)'::regprocedure,
                 'public.rollback_graph_publication_v3(uuid,bigint)'::regprocedure)
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', v_function);
    FOR v_role IN SELECT DISTINCT r.rolname FROM pg_proc p,
      LATERAL aclexplode(coalesce(p.proacl, acldefault('f',p.proowner))) a
      JOIN pg_roles r ON r.oid=a.grantee
      WHERE p.oid=v_function AND a.grantee <> p.proowner
    LOOP EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I',v_function,v_role); END LOOP;
  END LOOP;
END $restrict$;
REVOKE ALL ON FUNCTION public.activate_graph_publication_v3(uuid) FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;
REVOKE ALL ON FUNCTION public.rollback_graph_publication_v3(uuid,bigint) FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;
REVOKE ALL ON FUNCTION public.ensure_knowledge_node_primary_edge() FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;
REVOKE ALL ON FUNCTION public.prevent_canonical_graph_event_mutation() FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;
REVOKE ALL ON FUNCTION public.guard_graph_publication_lease_v1() FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;
-- Raw graph writes must not race a canonical publication snapshot. This trigger
-- runs as the caller: only the SECURITY DEFINER CAS owner may change inventory.
CREATE OR REPLACE FUNCTION public.guard_published_graph_source_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=public AS $$
DECLARE
  v_old jsonb := CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
  v_new jsonb := CASE WHEN TG_OP='DELETE' THEN '{}'::jsonb ELSE to_jsonb(NEW) END;
  v_persona uuid; v_protected boolean; v_position jsonb;
BEGIN
  IF (SELECT proowner FROM pg_proc WHERE oid='public.commit_graph_editor_v1(uuid,uuid,uuid,text,text,text,text,text,jsonb)'::regprocedure)
       = current_user::regrole::oid THEN
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
  END IF;
  -- A BEFORE ROW trigger may already hold its row lock. A nonblocking advisory
  -- acquisition avoids inversion with CAS (persona lock then source row locks).
  -- Success holds the lock until transaction end; contention fails closed.
  FOR v_persona IN
    SELECT DISTINCT persona_id FROM (
      SELECT nullif(v_old->>'persona_id','')::uuid AS persona_id
      UNION SELECT nullif(v_new->>'persona_id','')::uuid
      UNION SELECT n.persona_id FROM public.knowledge_nodes n
       WHERE n.id::text IN (v_old->>'source_node_id',v_old->>'target_node_id',v_new->>'source_node_id',v_new->>'target_node_id')
    ) scope WHERE persona_id IS NOT NULL ORDER BY persona_id
  LOOP
    IF NOT pg_try_advisory_xact_lock(hashtext(v_persona::text)) THEN
      RAISE EXCEPTION 'raw_published_graph_write_requires_editor' USING ERRCODE='40001';
    END IF;
  END LOOP;
  IF TG_TABLE_NAME='knowledge_nodes' THEN
    SELECT EXISTS(SELECT 1 FROM public.graph_publications p,
      LATERAL jsonb_array_elements(p.document_json->'nodes') n
      WHERE p.status='active' AND n->>'projection_node_id' IN (v_old->>'id',v_new->>'id')) INTO v_protected;
    IF v_protected AND TG_OP='UPDATE'
      AND (v_old-'metadata'-'updated_at')=(v_new-'metadata'-'updated_at')
      AND (coalesce(v_old->'metadata','{}')-'graph_position')=(coalesce(v_new->'metadata','{}')-'graph_position') THEN
      v_position:=v_new->'metadata'->'graph_position';
      IF v_position IS NULL OR (jsonb_typeof(v_position)='object'
        AND v_position ? 'x' AND v_position ? 'y'
        AND v_position-'x'-'y'='{}'::jsonb
        AND jsonb_typeof(v_position->'x')='number' AND jsonb_typeof(v_position->'y')='number') THEN
        RETURN NEW;
      END IF;
    END IF;
  ELSE
    -- Connections to unpublished conversations/assets remain ordinary writes.
    -- Either OLD or NEW published-to-published topology is protected.
    SELECT EXISTS(SELECT 1 FROM public.graph_publications p
      WHERE p.status='active' AND EXISTS(SELECT 1 FROM (VALUES
        (v_old->>'source_node_id',v_old->>'target_node_id'),
        (v_new->>'source_node_id',v_new->>'target_node_id')) endpoints(source_id,target_id)
        WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(p.document_json->'nodes') n WHERE n->>'projection_node_id'=endpoints.source_id)
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.document_json->'nodes') n WHERE n->>'projection_node_id'=endpoints.target_id))) INTO v_protected;
  END IF;
  IF v_protected THEN
    RAISE EXCEPTION 'raw_published_graph_write_requires_editor' USING ERRCODE='40001';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
DROP TRIGGER IF EXISTS guard_published_graph_source ON public.knowledge_nodes;
CREATE TRIGGER guard_published_graph_source BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_nodes
FOR EACH ROW EXECUTE FUNCTION public.guard_published_graph_source_v1();
DROP TRIGGER IF EXISTS guard_published_graph_source ON public.knowledge_edges;
CREATE TRIGGER guard_published_graph_source BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_edges
FOR EACH ROW EXECUTE FUNCTION public.guard_published_graph_source_v1();
REVOKE ALL ON FUNCTION public.guard_published_graph_source_v1() FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;

NOTIFY pgrst, 'reload schema';
