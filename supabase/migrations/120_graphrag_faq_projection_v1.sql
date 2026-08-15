-- GraphRAG v3.3: fail-closed FAQ projection and internal FAQ retrieval.
-- No table is introduced. Publications without faq_projection_contract=v1
-- remain activatable so an older immutable release can still be rolled back.

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

  PERFORM pg_advisory_xact_lock(hashtext(v_publication.persona_id::text));
  UPDATE public.graph_publications
  SET status = 'rolled_back'
  WHERE persona_id = v_publication.persona_id AND status = 'active' AND id <> p_publication_id;
  UPDATE public.graph_publications
  SET status = 'active', activated_at = coalesce(activated_at, now())
  WHERE id = p_publication_id;

  RETURN jsonb_build_object(
    'publication_id', p_publication_id, 'persona_id', v_publication.persona_id,
    'version', v_publication.version, 'checksum', v_publication.checksum,
    'status', 'active', 'entry_count', v_entry_count, 'chunk_count', v_chunk_count,
    'faq_projection_contract', v_publication.document_json->>'faq_projection_contract'
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.graph_faq_search_v3(
  p_persona_id uuid,
  p_publication_id uuid,
  p_branch_node_id text,
  p_query text,
  p_query_embedding vector(1536) DEFAULT NULL,
  p_eligible_faq_node_ids text[] DEFAULT '{}',
  p_limit integer DEFAULT 64
)
RETURNS TABLE (
  chunk_id uuid,
  faq_node_id text,
  question text,
  aliases jsonb,
  chunk_text text,
  semantic_score double precision,
  lexical_score double precision,
  faq_score double precision,
  metadata jsonb
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  WITH query AS (
    SELECT CASE WHEN btrim(coalesce(p_query, '')) = '' THEN NULL
      ELSE websearch_to_tsquery('simple', p_query) END AS tsq
  ), eligible AS (
    SELECT c.*,
      CASE WHEN p_query_embedding IS NULL OR c.embedding IS NULL THEN 0::double precision
        ELSE greatest(0::double precision,
          (1 - (c.embedding <=> p_query_embedding))::double precision) END AS semantic,
      CASE WHEN q.tsq IS NULL THEN 0::double precision
        ELSE ts_rank_cd(c.search_document, q.tsq, 32)::double precision END AS lexical
    FROM public.knowledge_rag_chunks c
    JOIN public.graph_publications p
      ON p.id = c.publication_id
     AND p.persona_id = p_persona_id
     AND p.status = 'active'
    JOIN public.graph_branch_memberships m
      ON m.publication_id = c.publication_id
     AND m.branch_node_id = p_branch_node_id
     AND m.node_id = c.source_graph_node_id
    CROSS JOIN query q
    WHERE c.persona_id = p_persona_id
      AND c.publication_id = p_publication_id
      AND c.branch_anchor_node_id = p_branch_node_id
      AND c.chunk_kind = 'faq'
      AND c.source_graph_node_id = ANY(coalesce(p_eligible_faq_node_ids, '{}'))
      AND coalesce(
        p.document_json->'branch_contracts'->p_branch_node_id->'eligible_faq_node_ids',
        '[]'::jsonb
      ) ? c.source_graph_node_id
      AND c.projection_status IN ('ready', 'published')
  )
  SELECT e.id, e.source_graph_node_id, e.metadata->>'faq_question',
    coalesce(e.metadata->'faq_aliases', '[]'::jsonb), e.chunk_text,
    e.semantic, e.lexical, greatest(e.semantic, e.lexical), e.metadata
  FROM eligible e
  ORDER BY greatest(e.semantic, e.lexical) DESC, e.id
  LIMIT greatest(1, least(coalesce(p_limit, 64), 200));
$$;

GRANT EXECUTE ON FUNCTION public.activate_graph_publication_v3(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.graph_faq_search_v3(uuid, uuid, text, text, vector, text[], integer) TO service_role;
REVOKE ALL ON FUNCTION public.activate_graph_publication_v3(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.graph_faq_search_v3(uuid, uuid, text, text, vector, text[], integer) FROM PUBLIC, anon, authenticated;
