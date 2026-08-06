-- Serialize proof commits before the idempotency read and invalidate only the
-- facts explicitly found incompatible with a newly activated publication.

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
  v_previous_is_current boolean;
  v_next_revision bigint;
  v_invalidated_keys text[];
BEGIN
  IF nullif(btrim(p_canonical_inbound_id), '') IS NULL THEN
    RAISE EXCEPTION 'canonical inbound id is required';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text || ':' || p_lead_ref::text));
  SELECT * INTO v_existing FROM public.conversation_turn_proofs
  WHERE canonical_inbound_id = p_canonical_inbound_id FOR UPDATE;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'state', 'completed', 'deduplicated', true,
      'proof_id', v_existing.id, 'ledger_id', v_existing.ledger_id,
      'outbound_id', v_existing.outbound_id
    );
  END IF;

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
    IF v_ledger.publication_id <> p_publication_id THEN
      SELECT coalesce(array_agg(value), '{}'::text[]) INTO v_invalidated_keys
      FROM jsonb_array_elements_text(
        coalesce(p_retrieval_trace->'invalidated_fact_keys', '[]'::jsonb)
      );
      UPDATE public.conversation_facts
      SET is_current = false, updated_at = now()
      WHERE ledger_id = v_ledger.id AND is_current
        AND field_key = ANY(v_invalidated_keys);
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
    SELECT id, is_current INTO v_previous, v_previous_is_current
    FROM public.conversation_facts
    WHERE ledger_id = v_ledger.id AND field_key = v_fact->>'field_key'
    ORDER BY revision DESC LIMIT 1 FOR UPDATE;
    IF v_previous IS NOT NULL AND v_previous_is_current THEN
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
    v_previous_is_current := NULL;
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

GRANT EXECUTE ON FUNCTION public.commit_graph_turn_v3(text, uuid, bigint, uuid, text, text, text[], bigint, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb, text) TO service_role;
REVOKE ALL ON FUNCTION public.commit_graph_turn_v3(text, uuid, bigint, uuid, text, text, text[], bigint, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb, text) FROM PUBLIC, anon, authenticated;
