-- Generic GraphRAG conversational runtime v3.
-- knowledge_nodes/knowledge_edges remain the editable source.  Every row in
-- graph_publications is an immutable compiled snapshot of those tables.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.graph_publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE RESTRICT,
  version bigint NOT NULL CHECK (version > 0),
  checksum text NOT NULL CHECK (checksum LIKE 'sha256:%'),
  document_json jsonb NOT NULL CHECK (jsonb_typeof(document_json) = 'object'),
  status text NOT NULL DEFAULT 'building'
    CHECK (status IN ('building', 'compiled', 'active', 'failed', 'rolled_back')),
  activated_at timestamptz,
  compiler_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (persona_id, version),
  UNIQUE (persona_id, checksum)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_publications_one_active
  ON public.graph_publications(persona_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_graph_publications_lookup
  ON public.graph_publications(persona_id, status, version DESC);

CREATE TABLE IF NOT EXISTS public.graph_node_coordinates (
  publication_id uuid NOT NULL REFERENCES public.graph_publications(id) ON DELETE CASCADE,
  node_id text NOT NULL,
  branch_anchor_node_id text,
  path_node_ids text[] NOT NULL DEFAULT '{}',
  path_edge_ids text[] NOT NULL DEFAULT '{}',
  depth integer NOT NULL CHECK (depth >= 0),
  path_checksum text NOT NULL CHECK (path_checksum LIKE 'sha256:%'),
  PRIMARY KEY (publication_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_graph_coordinates_branch
  ON public.graph_node_coordinates(publication_id, branch_anchor_node_id, depth);
CREATE INDEX IF NOT EXISTS idx_graph_coordinates_path_gin
  ON public.graph_node_coordinates USING gin(path_node_ids);

CREATE TABLE IF NOT EXISTS public.graph_branch_memberships (
  publication_id uuid NOT NULL REFERENCES public.graph_publications(id) ON DELETE CASCADE,
  branch_node_id text NOT NULL,
  node_id text NOT NULL,
  graph_distance integer NOT NULL CHECK (graph_distance >= 0),
  inclusion_reason text NOT NULL,
  structural_weight numeric(9,6) NOT NULL DEFAULT 1 CHECK (structural_weight >= 0),
  PRIMARY KEY (publication_id, branch_node_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_graph_memberships_node
  ON public.graph_branch_memberships(publication_id, node_id, branch_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_memberships_distance
  ON public.graph_branch_memberships(publication_id, branch_node_id, graph_distance);

CREATE TABLE IF NOT EXISTS public.graph_branch_contracts (
  publication_id uuid NOT NULL REFERENCES public.graph_publications(id) ON DELETE CASCADE,
  branch_node_id text NOT NULL,
  path_checksum text NOT NULL CHECK (path_checksum LIKE 'sha256:%'),
  closure_checksum text NOT NULL CHECK (closure_checksum LIKE 'sha256:%'),
  contract_json jsonb NOT NULL CHECK (jsonb_typeof(contract_json) = 'object'),
  compiler_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (publication_id, branch_node_id)
);

CREATE TABLE IF NOT EXISTS public.conversation_ledgers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE RESTRICT,
  lead_ref bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  active_branch_node_id text,
  publication_id uuid NOT NULL REFERENCES public.graph_publications(id) ON DELETE RESTRICT,
  graph_checksum text NOT NULL CHECK (graph_checksum LIKE 'sha256:%'),
  revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
  asked_question_node_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (persona_id, lead_ref)
);
CREATE INDEX IF NOT EXISTS idx_conversation_ledgers_publication
  ON public.conversation_ledgers(publication_id, active_branch_node_id);

CREATE TABLE IF NOT EXISTS public.conversation_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ledger_id uuid NOT NULL REFERENCES public.conversation_ledgers(id) ON DELETE CASCADE,
  field_key text NOT NULL,
  owner_node_id text NOT NULL,
  status text NOT NULL
    CHECK (status IN ('known', 'unknown', 'declined', 'needs_confirmation', 'invalid')),
  value_json jsonb,
  source_message_id text NOT NULL,
  evidence_span text,
  confidence numeric(5,4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  revision bigint NOT NULL CHECK (revision > 0),
  supersedes_fact_id uuid REFERENCES public.conversation_facts(id) ON DELETE SET NULL,
  is_current boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ledger_id, field_key, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_facts_current
  ON public.conversation_facts(ledger_id, field_key) WHERE is_current;
CREATE INDEX IF NOT EXISTS idx_conversation_facts_source
  ON public.conversation_facts(ledger_id, source_message_id);

CREATE TABLE IF NOT EXISTS public.conversation_turn_proofs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_inbound_id text NOT NULL UNIQUE,
  ledger_id uuid REFERENCES public.conversation_ledgers(id) ON DELETE SET NULL,
  publication_id uuid NOT NULL REFERENCES public.graph_publications(id) ON DELETE RESTRICT,
  retrieval_trace jsonb NOT NULL DEFAULT '{}'::jsonb,
  model_proposal jsonb NOT NULL DEFAULT '{}'::jsonb,
  proof_result jsonb NOT NULL DEFAULT '{}'::jsonb,
  repair_result jsonb NOT NULL DEFAULT '{}'::jsonb,
  final_decision jsonb NOT NULL DEFAULT '{}'::jsonb,
  outbound_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversation_turn_proofs_publication
  ON public.conversation_turn_proofs(publication_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_turn_proofs_ledger
  ON public.conversation_turn_proofs(ledger_id, created_at DESC);

ALTER TABLE public.knowledge_rag_entries
  ADD COLUMN IF NOT EXISTS publication_id uuid REFERENCES public.graph_publications(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_graph_node_id text;

ALTER TABLE public.knowledge_rag_chunks
  ADD COLUMN IF NOT EXISTS publication_id uuid REFERENCES public.graph_publications(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_graph_node_id text,
  ADD COLUMN IF NOT EXISTS branch_anchor_node_id text,
  ADD COLUMN IF NOT EXISTS path_checksum text,
  ADD COLUMN IF NOT EXISTS chunk_kind text NOT NULL DEFAULT 'content',
  ADD COLUMN IF NOT EXISTS chunk_checksum text,
  ADD COLUMN IF NOT EXISTS search_document tsvector
    GENERATED ALWAYS AS (
      to_tsvector('simple', coalesce(chunk_summary, '') || ' ' || coalesce(chunk_text, ''))
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_rag_entries_publication_node
  ON public.knowledge_rag_entries(persona_id, publication_id, source_graph_node_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_publication_branch
  ON public.knowledge_rag_chunks(persona_id, publication_id, branch_anchor_node_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_graph_node
  ON public.knowledge_rag_chunks(publication_id, source_graph_node_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_search_document
  ON public.knowledge_rag_chunks USING gin(search_document);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw
  ON public.knowledge_rag_chunks USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

CREATE OR REPLACE FUNCTION public.graph_publication_immutable_v3()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.persona_id IS DISTINCT FROM OLD.persona_id
     OR NEW.version IS DISTINCT FROM OLD.version
     OR NEW.checksum IS DISTINCT FROM OLD.checksum
     OR NEW.document_json IS DISTINCT FROM OLD.document_json
     OR NEW.compiler_version IS DISTINCT FROM OLD.compiler_version
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'compiled graph publication content is immutable'
      USING ERRCODE = '55000';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_graph_publication_immutable_v3 ON public.graph_publications;
CREATE TRIGGER trg_graph_publication_immutable_v3
  BEFORE UPDATE ON public.graph_publications
  FOR EACH ROW EXECUTE FUNCTION public.graph_publication_immutable_v3();

CREATE OR REPLACE FUNCTION public.activate_graph_publication_v3(p_publication_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_publication public.graph_publications%ROWTYPE;
  v_branch_count integer;
  v_contract_count integer;
  v_required_chunks integer;
  v_embedded_chunks integer;
BEGIN
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

  SELECT count(DISTINCT branch_node_id) INTO v_branch_count
  FROM public.graph_branch_memberships WHERE publication_id = p_publication_id;
  SELECT count(*) INTO v_contract_count
  FROM public.graph_branch_contracts WHERE publication_id = p_publication_id;
  IF v_branch_count = 0 OR v_contract_count <> v_branch_count THEN
    RAISE EXCEPTION 'branch contracts are incomplete (% contracts / % branches)',
      v_contract_count, v_branch_count;
  END IF;

  SELECT count(*), count(*) FILTER (WHERE embedding IS NOT NULL AND embedded_at IS NOT NULL)
    INTO v_required_chunks, v_embedded_chunks
  FROM public.knowledge_rag_chunks
  WHERE publication_id = p_publication_id
    AND projection_status IN ('active', 'projected', 'ready');
  IF v_required_chunks = 0 OR v_required_chunks <> v_embedded_chunks THEN
    RAISE EXCEPTION 'required embeddings are incomplete (% embedded / % chunks)',
      v_embedded_chunks, v_required_chunks;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtext(v_publication.persona_id::text));
  UPDATE public.graph_publications
  SET status = 'rolled_back'
  WHERE persona_id = v_publication.persona_id
    AND status = 'active'
    AND id <> p_publication_id;
  UPDATE public.graph_publications
  SET status = 'active', activated_at = coalesce(activated_at, now())
  WHERE id = p_publication_id;

  RETURN jsonb_build_object(
    'publication_id', p_publication_id,
    'persona_id', v_publication.persona_id,
    'version', v_publication.version,
    'checksum', v_publication.checksum,
    'status', 'active',
    'chunk_count', v_required_chunks
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.rollback_graph_publication_v3(
  p_persona_id uuid,
  p_target_version bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_id uuid;
BEGIN
  SELECT id INTO v_id FROM public.graph_publications
  WHERE persona_id = p_persona_id AND version = p_target_version
  FOR UPDATE;
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'target graph publication not found' USING ERRCODE = 'P0002';
  END IF;
  RETURN public.activate_graph_publication_v3(v_id);
END;
$$;

-- Bounded Postgres hybrid retrieval.  The FTS component is normalized like a
-- BM25 saturation score; the vector and structural components are computed in
-- the same query, after the mandatory persona/publication/branch filter.
CREATE OR REPLACE FUNCTION public.graph_hybrid_search_v3(
  p_persona_id uuid,
  p_publication_id uuid,
  p_branch_node_id text,
  p_query text,
  p_query_embedding vector(1536) DEFAULT NULL,
  p_active_path_node_ids text[] DEFAULT '{}',
  p_missing_fields text[] DEFAULT '{}',
  p_limit integer DEFAULT 40
)
RETURNS TABLE (
  chunk_id uuid,
  rag_entry_id uuid,
  source_node_id text,
  chunk_text text,
  chunk_summary text,
  chunk_kind text,
  metadata jsonb,
  graph_distance integer,
  bm25_score double precision,
  vector_score double precision,
  path_overlap_score double precision,
  missing_field_score double precision,
  priority_score double precision,
  structural_score double precision,
  hybrid_score double precision
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
  WITH query AS (
    SELECT CASE WHEN btrim(coalesce(p_query, '')) = '' THEN NULL
      ELSE websearch_to_tsquery('simple', p_query) END AS tsq
  ), eligible AS (
    SELECT c.*, m.graph_distance, m.structural_weight,
      CASE WHEN q.tsq IS NULL THEN 0::double precision
        ELSE ts_rank_cd(c.search_document, q.tsq, 32)::double precision END AS lexical,
      CASE WHEN p_query_embedding IS NULL OR c.embedding IS NULL THEN 0::double precision
        ELSE greatest(0::double precision, (1 - (c.embedding <=> p_query_embedding))::double precision) END AS semantic,
      CASE WHEN cardinality(p_active_path_node_ids) = 0 THEN 0::double precision
        ELSE coalesce((SELECT count(*)::double precision / cardinality(p_active_path_node_ids)
          FROM unnest(p_active_path_node_ids) p(node_id)
          WHERE c.metadata->'path_node_ids' ? p.node_id), 0) END AS path_overlap,
      CASE WHEN cardinality(p_missing_fields) = 0 THEN 0::double precision
        WHEN coalesce(c.metadata->>'field_key', '') = ANY(p_missing_fields) THEN 1::double precision
        WHEN EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(c.metadata->'field_keys', '[]'::jsonb)) f(value)
          WHERE f.value = ANY(p_missing_fields)) THEN 1::double precision
        ELSE 0::double precision END AS missing_relevance,
      least(1::double precision, greatest(0::double precision,
        coalesce((c.metadata->>'priority')::double precision, 0.5))) AS priority
    FROM public.knowledge_rag_chunks c
    JOIN public.graph_branch_memberships m
      ON m.publication_id = c.publication_id
     AND m.branch_node_id = p_branch_node_id
     AND m.node_id = c.source_graph_node_id
    CROSS JOIN query q
    WHERE c.persona_id = p_persona_id
      AND c.publication_id = p_publication_id
      AND c.branch_anchor_node_id = p_branch_node_id
      AND c.projection_status IN ('active', 'projected', 'ready')
  ), scored AS (
    SELECT e.*,
      (1.0 / (1.0 + e.graph_distance))::double precision AS structural,
      (0.32 * e.semantic + 0.25 * e.lexical + 0.14 * e.path_overlap
       + 0.14 * e.missing_relevance + 0.08 * e.priority
       + 0.07 * (e.structural_weight::double precision / (1.0 + e.graph_distance)))::double precision AS total
    FROM eligible e
    WHERE e.lexical > 0 OR e.semantic > 0 OR e.missing_relevance > 0 OR e.graph_distance <= 1
  )
  SELECT id, rag_entry_id, source_graph_node_id, scored.chunk_text,
    scored.chunk_summary, scored.chunk_kind, scored.metadata, scored.graph_distance,
    lexical, semantic, path_overlap, missing_relevance, priority, structural, total
  FROM scored
  ORDER BY total DESC, graph_distance ASC, id
  LIMIT greatest(1, least(coalesce(p_limit, 40), 200));
$$;

-- Commit the factual ledger and proof exactly once for one canonical inbound.
-- Transport/outbox idempotency remains owned by lead_buffer; callers pass the
-- resulting outbound id into this atomic audit commit.
CREATE OR REPLACE FUNCTION public.commit_graph_turn_v3(
  p_canonical_inbound_id text,
  p_persona_id uuid,
  p_lead_ref bigint,
  p_publication_id uuid,
  p_graph_checksum text,
  p_active_branch_node_id text,
  p_asked_question_node_ids text[],
  p_expected_revision bigint,
  p_facts jsonb,
  p_retrieval_trace jsonb,
  p_model_proposal jsonb,
  p_proof_result jsonb,
  p_repair_result jsonb,
  p_final_decision jsonb,
  p_outbound_id text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_existing public.conversation_turn_proofs%ROWTYPE;
  v_ledger public.conversation_ledgers%ROWTYPE;
  v_fact jsonb;
  v_previous uuid;
  v_next_revision bigint;
BEGIN
  IF nullif(btrim(p_canonical_inbound_id), '') IS NULL THEN
    RAISE EXCEPTION 'canonical inbound id is required';
  END IF;
  SELECT * INTO v_existing FROM public.conversation_turn_proofs
  WHERE canonical_inbound_id = p_canonical_inbound_id FOR UPDATE;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'state', 'completed', 'deduplicated', true,
      'proof_id', v_existing.id, 'ledger_id', v_existing.ledger_id,
      'outbound_id', v_existing.outbound_id
    );
  END IF;

  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text || ':' || p_lead_ref::text));
  SELECT * INTO v_ledger FROM public.conversation_ledgers
  WHERE persona_id = p_persona_id AND lead_ref = p_lead_ref FOR UPDATE;
  IF NOT FOUND THEN
    IF coalesce(p_expected_revision, 0) <> 0 THEN
      RAISE EXCEPTION 'ledger revision conflict: expected %, current absent', p_expected_revision
        USING ERRCODE = '40001';
    END IF;
    INSERT INTO public.conversation_ledgers(
      persona_id, lead_ref, active_branch_node_id, publication_id,
      graph_checksum, revision, asked_question_node_ids
    ) VALUES (
      p_persona_id, p_lead_ref, p_active_branch_node_id, p_publication_id,
      p_graph_checksum, 1, coalesce(p_asked_question_node_ids, '{}')
    ) RETURNING * INTO v_ledger;
  ELSE
    IF v_ledger.revision <> coalesce(p_expected_revision, v_ledger.revision) THEN
      RAISE EXCEPTION 'ledger revision conflict: expected %, current %',
        p_expected_revision, v_ledger.revision USING ERRCODE = '40001';
    END IF;
    UPDATE public.conversation_ledgers SET
      active_branch_node_id = p_active_branch_node_id,
      publication_id = p_publication_id,
      graph_checksum = p_graph_checksum,
      revision = revision + 1,
      asked_question_node_ids = coalesce(p_asked_question_node_ids, '{}'),
      updated_at = now()
    WHERE id = v_ledger.id RETURNING * INTO v_ledger;
  END IF;

  FOR v_fact IN SELECT value FROM jsonb_array_elements(coalesce(p_facts, '[]'::jsonb)) LOOP
    IF nullif(v_fact->>'field_key', '') IS NULL
       OR nullif(v_fact->>'owner_node_id', '') IS NULL
       OR nullif(v_fact->>'source_message_id', '') IS NULL THEN
      RAISE EXCEPTION 'fact is missing field_key, owner_node_id or source_message_id';
    END IF;
    SELECT id INTO v_previous FROM public.conversation_facts
      WHERE ledger_id = v_ledger.id AND field_key = v_fact->>'field_key' AND is_current
      FOR UPDATE;
    IF v_previous IS NOT NULL THEN
      UPDATE public.conversation_facts SET is_current = false, updated_at = now()
      WHERE id = v_previous;
    END IF;
    SELECT coalesce(max(revision), 0) + 1 INTO v_next_revision
      FROM public.conversation_facts
      WHERE ledger_id = v_ledger.id AND field_key = v_fact->>'field_key';
    INSERT INTO public.conversation_facts(
      ledger_id, field_key, owner_node_id, status, value_json,
      source_message_id, evidence_span, confidence, revision, supersedes_fact_id
    ) VALUES (
      v_ledger.id, v_fact->>'field_key', v_fact->>'owner_node_id',
      v_fact->>'status', v_fact->'value', v_fact->>'source_message_id',
      v_fact->>'evidence_span', nullif(v_fact->>'confidence', '')::numeric,
      v_next_revision, v_previous
    );
    v_previous := NULL;
  END LOOP;

  INSERT INTO public.conversation_turn_proofs(
    canonical_inbound_id, ledger_id, publication_id, retrieval_trace,
    model_proposal, proof_result, repair_result, final_decision, outbound_id
  ) VALUES (
    p_canonical_inbound_id, v_ledger.id, p_publication_id,
    coalesce(p_retrieval_trace, '{}'::jsonb), coalesce(p_model_proposal, '{}'::jsonb),
    coalesce(p_proof_result, '{}'::jsonb), coalesce(p_repair_result, '{}'::jsonb),
    coalesce(p_final_decision, '{}'::jsonb), p_outbound_id
  ) RETURNING * INTO v_existing;

  RETURN jsonb_build_object(
    'state', 'completed', 'deduplicated', false,
    'proof_id', v_existing.id, 'ledger_id', v_ledger.id,
    'ledger_revision', v_ledger.revision, 'outbound_id', p_outbound_id
  );
END;
$$;

ALTER TABLE public.graph_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_node_coordinates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_branch_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_branch_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_ledgers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_turn_proofs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.graph_publications FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.graph_node_coordinates FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.graph_branch_memberships FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.graph_branch_contracts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.conversation_ledgers FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.conversation_facts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.conversation_turn_proofs FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.graph_publications TO service_role;
GRANT ALL ON TABLE public.graph_node_coordinates TO service_role;
GRANT ALL ON TABLE public.graph_branch_memberships TO service_role;
GRANT ALL ON TABLE public.graph_branch_contracts TO service_role;
GRANT ALL ON TABLE public.conversation_ledgers TO service_role;
GRANT ALL ON TABLE public.conversation_facts TO service_role;
GRANT ALL ON TABLE public.conversation_turn_proofs TO service_role;
GRANT EXECUTE ON FUNCTION public.activate_graph_publication_v3(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.rollback_graph_publication_v3(uuid, bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.graph_hybrid_search_v3(uuid, uuid, text, text, vector, text[], text[], integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_v3(text, uuid, bigint, uuid, text, text, text[], bigint, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb, text) TO service_role;

REVOKE ALL ON FUNCTION public.activate_graph_publication_v3(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rollback_graph_publication_v3(uuid, bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.graph_hybrid_search_v3(uuid, uuid, text, text, vector, text[], text[], integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.commit_graph_turn_v3(text, uuid, bigint, uuid, text, text, text[], bigint, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb, text) FROM PUBLIC, anon, authenticated;
