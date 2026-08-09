-- Adds support for more than one simultaneously-selected service/product per
-- appointment conversation (v3 runtime). Today `conversation_ledgers.
-- active_branch_node_id` is a scalar column and `conversation_facts` has one
-- unique index per (ledger_id, field_key) -- a customer asking for a second
-- service (e.g. "higienização interna" + "polimento técnico") always
-- overwrites the first "servico" fact instead of adding to it. This is
-- confirmed structural, not a prompt gap: see
-- docs/handoffs and the 2026-08-09 live investigation.
--
-- This migration is purely additive: `active_branch_node_id` keeps its
-- existing type/meaning (the branch in dialogue focus for this turn); no
-- existing row, index, or caller is changed by this file alone. The runtime
-- (graph_agent_runtime_v3.py) only writes to conversation_ledger_branches
-- and relies on the new fact uniqueness when a persona's compiled contract
-- declares the well-known "mais_servicos" field -- personas that don't
-- declare it (every appointment persona except Aurora, today) are
-- byte-for-byte unaffected.

CREATE TABLE IF NOT EXISTS public.conversation_ledger_branches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ledger_id uuid NOT NULL REFERENCES public.conversation_ledgers(id) ON DELETE CASCADE,
  branch_anchor_node_id text NOT NULL,
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'completed', 'dropped')),
  added_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE (ledger_id, branch_anchor_node_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_ledger_branches_ledger
  ON public.conversation_ledger_branches(ledger_id, state);

-- Was `(ledger_id, field_key) WHERE is_current` -- one current value per
-- field per ledger, full stop. A field genuinely owned by a branch (e.g.
-- "servico", owner_node_id = the branch anchor itself) must be able to have
-- one current value PER OWNER once more than one branch can be active at
-- once, while a persona-wide field (e.g. "nome_cliente", owner_node_id =
-- the persona node) still naturally stays a singleton because every branch
-- shares that same owner_node_id. owner_node_id already exists on every
-- fact (added for the cross-branch-leak fix, commit 6538461) so this is a
-- pure widening of the uniqueness scope, not a new column.
DROP INDEX IF EXISTS idx_conversation_facts_current;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_facts_current_v2
  ON public.conversation_facts(ledger_id, field_key, owner_node_id) WHERE is_current;

-- commit_graph_turn_v3's per-fact "supersede the current row" lookup must
-- match the same (ledger_id, field_key, owner_node_id) scope as the new
-- unique index above -- otherwise committing a second branch's "servico"
-- fact would still incorrectly retire the first branch's still-active
-- "servico" fact (same field_key, different owner_node_id).
CREATE OR REPLACE FUNCTION public.commit_graph_turn_v3(p_canonical_inbound_id text, p_persona_id uuid, p_lead_ref bigint, p_publication_id uuid, p_graph_checksum text, p_active_branch_node_id text, p_asked_question_node_ids text[], p_expected_revision bigint, p_facts jsonb, p_retrieval_trace jsonb, p_model_proposal jsonb, p_proof_result jsonb, p_repair_result jsonb, p_final_decision jsonb, p_outbound_id text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
      AND owner_node_id = v_fact->>'owner_node_id'
    ORDER BY revision DESC LIMIT 1 FOR UPDATE;
    IF v_previous IS NOT NULL AND v_previous_is_current THEN
      UPDATE public.conversation_facts SET is_current = false, updated_at = now()
      WHERE id = v_previous;
    END IF;
    SELECT coalesce(max(revision), 0) + 1 INTO v_next_revision
      FROM public.conversation_facts
      WHERE ledger_id = v_ledger.id AND field_key = v_fact->>'field_key'
        AND owner_node_id = v_fact->>'owner_node_id';
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
$function$;

ALTER TABLE public.conversation_ledger_branches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.conversation_ledger_branches FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.conversation_ledger_branches TO service_role;
