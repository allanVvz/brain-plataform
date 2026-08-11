-- Hotfix: a model reply must never become dispatchable before its durable
-- graph proof exists. Also fixes fact revision allocation across owners and
-- serializes/coalesces inbound bursts per lead without adding storage.

-- Migration 103 expanded both handoff RPCs with a defaulted handoff level but
-- left their old overloads installed. PostgreSQL cannot resolve legacy calls
-- against an old exact signature plus a new defaulted signature. The expanded
-- RPCs preserve the legacy call contract through their defaults, so remove only
-- the superseded overloads (no data is affected).
DROP FUNCTION IF EXISTS public.handoff_whatsapp_lead(bigint);
DROP FUNCTION IF EXISTS public.handoff_whatsapp_lead_state(bigint, jsonb, text);

ALTER TABLE public.lead_buffer
  DROP CONSTRAINT IF EXISTS lead_buffer_status_check;
ALTER TABLE public.lead_buffer
  ADD CONSTRAINT lead_buffer_status_check CHECK (status IN (
    'received', 'buffered', 'processing', 'awaiting_proof', 'pending_send',
    'sent', 'delivered', 'read', 'failed', 'retry', 'dead_letter',
    'waiting_human', 'ignored'
  ));

-- Migration 105 widened current-fact uniqueness to owner scope, but allocated
-- revisions in that same scope. The older immutable history constraint remains
-- (ledger_id, field_key, revision), so changing service owner attempted revision
-- 1 again. Allocate the sequence globally for the field while retaining the
-- owner-scoped current-row lookup.
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
    RETURN jsonb_build_object('state', 'completed', 'deduplicated', true,
      'proof_id', v_existing.id, 'ledger_id', v_existing.ledger_id,
      'outbound_id', v_existing.outbound_id);
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
      FROM jsonb_array_elements_text(coalesce(p_retrieval_trace->'invalidated_fact_keys', '[]'::jsonb));
      UPDATE public.conversation_facts SET is_current = false, updated_at = now()
       WHERE ledger_id = v_ledger.id AND is_current AND field_key = ANY(v_invalidated_keys);
    END IF;
    UPDATE public.conversation_ledgers SET
      active_branch_node_id = p_active_branch_node_id,
      publication_id = p_publication_id, graph_checksum = p_graph_checksum,
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

  RETURN jsonb_build_object('state', 'completed', 'deduplicated', false,
    'proof_id', v_existing.id, 'ledger_id', v_ledger.id,
    'ledger_revision', v_ledger.revision, 'outbound_id', p_outbound_id);
END;
$function$;

-- The only transition that releases an agent outbound. It verifies one proof,
-- releases that exact outbox row and completes the canonical inbound commit in
-- the same transaction. A failed ledger/proof commit leaves awaiting_proof inert.
CREATE OR REPLACE FUNCTION public.finalize_proven_conversation_turn(
  p_inbound_buffer_id uuid, p_binding_id uuid, p_lead_ref bigint,
  p_correlation_id text, p_outbound_id uuid, p_result jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_inbound public.lead_buffer%ROWTYPE;
  v_outbound public.lead_buffer%ROWTYPE;
  v_proof_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_binding_id::text || ':' || p_lead_ref::text));
  SELECT * INTO v_inbound FROM public.lead_buffer WHERE id = p_inbound_buffer_id FOR UPDATE;
  SELECT * INTO v_outbound FROM public.lead_buffer WHERE id = p_outbound_id FOR UPDATE;
  IF v_inbound.id IS NULL OR v_inbound.direction <> 'inbound'
     OR v_inbound.channel_binding_id <> p_binding_id OR v_inbound.lead_ref <> p_lead_ref THEN
    RAISE EXCEPTION 'canonical inbound identity mismatch' USING ERRCODE = '23514';
  END IF;
  IF v_outbound.id IS NULL OR v_outbound.direction <> 'outbound'
     OR v_outbound.channel_binding_id <> p_binding_id OR v_outbound.lead_ref <> p_lead_ref THEN
    RAISE EXCEPTION 'outbound identity mismatch' USING ERRCODE = '23514';
  END IF;
  SELECT count(*) INTO v_proof_count FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id = p_inbound_buffer_id::text
     AND outbound_id = p_outbound_id::text
     AND coalesce((proof_result->>'valid')::boolean, false);
  IF v_proof_count <> 1 THEN
    RAISE EXCEPTION 'outbound requires exactly one valid turn proof, found %', v_proof_count
      USING ERRCODE = '23514';
  END IF;
  IF v_outbound.status = 'awaiting_proof' THEN
    UPDATE public.lead_buffer SET status = 'pending_send', available_at = now(),
      locked_at = NULL, locked_by = NULL, updated_at = now()
     WHERE id = p_outbound_id;
  ELSIF v_outbound.status NOT IN ('pending_send','processing','sent','delivered','read') THEN
    RAISE EXCEPTION 'outbound cannot be released from status %', v_outbound.status
      USING ERRCODE = '23514';
  END IF;
  UPDATE public.lead_buffer SET
    payload = jsonb_set(coalesce(payload, '{}'::jsonb), '{conversation_commit}',
      jsonb_build_object('status','completed','binding_id',p_binding_id,
        'lead_ref',p_lead_ref,'correlation_id',p_correlation_id,
        'completed_at',now(),'result',coalesce(p_result,'{}'::jsonb)), true),
    status = 'sent', locked_at = NULL, locked_by = NULL, updated_at = now()
   WHERE id = p_inbound_buffer_id;
  RETURN jsonb_build_object('ok', true, 'state', 'completed',
    'inbound_id', p_inbound_buffer_id, 'outbound_id', p_outbound_id,
    'outbound_status', CASE WHEN v_outbound.status = 'awaiting_proof' THEN 'pending_send' ELSE v_outbound.status END);
END;
$$;

-- Final transaction boundary for GraphRAG v3. All called functions participate
-- in this RPC's transaction: ledger/facts/proof, branch set, inert outbox,
-- proof-authorized release and inbound completion either all commit or all roll
-- back. p_turn is a technical envelope, never commercial policy.
CREATE OR REPLACE FUNCTION public.commit_graph_turn_and_outbox_v3(
  p_turn jsonb, p_outbound_buffer jsonb DEFAULT NULL,
  p_outbound_message jsonb DEFAULT NULL, p_result jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_graph jsonb;
  v_envelope jsonb;
  v_outbound_id uuid;
  v_final_result jsonb;
  v_branch text;
BEGIN
  IF nullif(p_turn->>'canonical_inbound_id','') IS NULL
     OR nullif(p_turn->>'binding_id','') IS NULL
     OR nullif(p_turn->>'correlation_id','') IS NULL THEN
    RAISE EXCEPTION 'turn identity is incomplete' USING ERRCODE='23514';
  END IF;
  IF p_outbound_buffer IS NOT NULL THEN
    IF p_outbound_message IS NULL OR p_outbound_buffer->>'status' <> 'awaiting_proof' THEN
      RAISE EXCEPTION 'v3 outbound must be created awaiting_proof' USING ERRCODE='23514';
    END IF;
    IF NOT coalesce((p_turn->'proof_result'->>'valid')::boolean, false) THEN
      RAISE EXCEPTION 'v3 outbound requires a valid proof result' USING ERRCODE='23514';
    END IF;
    v_envelope := public.enqueue_whatsapp_envelope(p_outbound_buffer,p_outbound_message);
    IF coalesce((v_envelope->>'deduplicated')::boolean, false) THEN
      RAISE EXCEPTION 'v3 atomic commit refuses a preexisting outbound envelope'
        USING ERRCODE='23514';
    END IF;
    v_outbound_id := (v_envelope->>'buffer_id')::uuid;
  END IF;

  v_graph := public.commit_graph_turn_v3(
    p_turn->>'canonical_inbound_id', (p_turn->>'persona_id')::uuid,
    (p_turn->>'lead_ref')::bigint, (p_turn->>'publication_id')::uuid,
    p_turn->>'graph_checksum', nullif(p_turn->>'active_branch_node_id',''),
    ARRAY(SELECT jsonb_array_elements_text(coalesce(p_turn->'asked_question_node_ids','[]'::jsonb))),
    coalesce((p_turn->>'expected_revision')::bigint,0),
    coalesce(p_turn->'facts','[]'::jsonb), coalesce(p_turn->'retrieval_trace','{}'::jsonb),
    coalesce(p_turn->'model_proposal','{}'::jsonb), coalesce(p_turn->'proof_result','{}'::jsonb),
    coalesce(p_turn->'repair_result','{}'::jsonb), coalesce(p_turn->'final_decision','{}'::jsonb),
    v_outbound_id::text
  );

  FOR v_branch IN SELECT jsonb_array_elements_text(coalesce(p_turn->'active_branch_node_ids','[]'::jsonb)) LOOP
    INSERT INTO public.conversation_ledger_branches(ledger_id,branch_anchor_node_id,state)
    VALUES ((v_graph->>'ledger_id')::uuid,v_branch,'active')
    ON CONFLICT (ledger_id,branch_anchor_node_id) DO UPDATE
      SET state='active',completed_at=NULL;
  END LOOP;

  v_final_result := coalesce(p_result,'{}'::jsonb) || jsonb_build_object(
    'graph_turn',v_graph,'outbound_buffer_id',v_outbound_id);
  IF v_outbound_id IS NOT NULL AND coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN
    UPDATE public.lead_buffer SET status='sent',updated_at=now() WHERE id=v_outbound_id;
    UPDATE public.messages SET status='sent'
     WHERE channel_binding_id=(p_turn->>'binding_id')::uuid
       AND correlation_id=p_outbound_message->>'correlation_id';
    PERFORM public.complete_conversation_commit(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_final_result);
  ELSIF v_outbound_id IS NOT NULL THEN
    PERFORM public.finalize_proven_conversation_turn(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_outbound_id,v_final_result);
  ELSE
    PERFORM public.complete_conversation_commit(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_final_result);
  END IF;
  RETURN jsonb_build_object('state','completed','graph_turn',v_graph,
    'outbound_buffer_id',v_outbound_id,
    'outbound_status',CASE
      WHEN v_outbound_id IS NULL THEN NULL
      WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN 'sent'
      ELSE 'pending_send' END);
END;
$$;

-- Rank all branch anchors in one SQL call. The initial package receives only
-- the compact top result per anchor; full chunks are fetched for the selected
-- branch in phase B.
CREATE OR REPLACE FUNCTION public.graph_branch_rank_v3(
  p_persona_id uuid, p_publication_id uuid, p_query text,
  p_query_embedding vector(1536) DEFAULT NULL, p_limit integer DEFAULT 8
)
RETURNS TABLE(branch_anchor_node_id text, score double precision, snippet text, chunk_id uuid)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
  WITH query AS (
    SELECT CASE WHEN btrim(coalesce(p_query, '')) = '' THEN NULL
      ELSE websearch_to_tsquery('simple', p_query) END AS tsq
  ), scored AS (
    SELECT c.branch_anchor_node_id, c.id,
      left(coalesce(c.chunk_summary, c.chunk_text, ''), 240) AS snippet,
      (0.56 * CASE WHEN q.tsq IS NULL THEN 0 ELSE ts_rank_cd(c.search_document, q.tsq, 32) END
       + 0.44 * CASE WHEN p_query_embedding IS NULL OR c.embedding IS NULL THEN 0
          ELSE greatest(0, 1 - (c.embedding <=> p_query_embedding)) END)::double precision AS total,
      row_number() OVER (PARTITION BY c.branch_anchor_node_id ORDER BY
        (0.56 * CASE WHEN q.tsq IS NULL THEN 0 ELSE ts_rank_cd(c.search_document, q.tsq, 32) END
         + 0.44 * CASE WHEN p_query_embedding IS NULL OR c.embedding IS NULL THEN 0
            ELSE greatest(0, 1 - (c.embedding <=> p_query_embedding)) END) DESC, c.id) AS rn
    FROM public.knowledge_rag_chunks c CROSS JOIN query q
    WHERE c.persona_id = p_persona_id AND c.publication_id = p_publication_id
      AND c.projection_status IN ('active','projected','ready')
  )
  SELECT scored.branch_anchor_node_id, scored.total, scored.snippet, scored.id
    FROM scored WHERE rn = 1 AND total > 0
   ORDER BY total DESC, branch_anchor_node_id
   LIMIT greatest(1, least(coalesce(p_limit, 8), 32));
$$;

CREATE OR REPLACE FUNCTION public.audit_conversation_turn_v3(p_inbound_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  WITH inbound AS (
    SELECT * FROM public.lead_buffer WHERE id=p_inbound_id
  ), proof AS (
    SELECT * FROM public.conversation_turn_proofs
     WHERE canonical_inbound_id=p_inbound_id::text
  ), outbound AS (
    SELECT b.* FROM public.lead_buffer b JOIN proof p ON p.outbound_id=b.id::text
  )
  SELECT jsonb_build_object(
    'inbound_id',p_inbound_id,
    'inbound_count',(SELECT count(*) FROM inbound),
    'decision_count',(SELECT count(*) FROM proof WHERE final_decision <> '{}'::jsonb),
    'proof_count',(SELECT count(*) FROM proof),
    'valid_proof_count',(SELECT count(*) FROM proof WHERE coalesce((proof_result->>'valid')::boolean,false)),
    'outbound_count',(SELECT count(*) FROM outbound),
    'outbound_status',(SELECT status FROM outbound LIMIT 1),
    'outbound_released_after_proof',coalesce((SELECT o.updated_at>=p.created_at FROM outbound o JOIN proof p ON p.outbound_id=o.id::text LIMIT 1),true),
    'commit_state',(SELECT coalesce(
      payload->'conversation_commit'->>'status',
      payload->'conversation_commit'->>'state'
    ) FROM inbound LIMIT 1),
    'active_branch_node_id',(SELECT l.active_branch_node_id FROM proof p JOIN public.conversation_ledgers l ON l.id=p.ledger_id LIMIT 1),
    'ledger_revision',(SELECT l.revision FROM proof p JOIN public.conversation_ledgers l ON l.id=p.ledger_id LIMIT 1),
    'current_fact_count',(SELECT count(*) FROM proof p JOIN public.conversation_facts f ON f.ledger_id=p.ledger_id AND f.is_current),
    'prompt_tokens',(SELECT (retrieval_trace->'token_usage'->>'prompt_tokens')::integer FROM proof LIMIT 1),
    'prompt_estimated_tokens',(SELECT (retrieval_trace->'token_usage'->>'prompt_estimated_tokens')::integer FROM proof LIMIT 1),
    'model_calls',(SELECT (retrieval_trace->'token_usage'->>'model_calls')::integer FROM proof LIMIT 1),
    'repair_calls',(SELECT (retrieval_trace->'token_usage'->>'repair_calls')::integer FROM proof LIMIT 1)
    ,'deterministic_branch_match',(SELECT coalesce((retrieval_trace->>'deterministic_branch_match')::boolean,false) FROM proof LIMIT 1)
  );
$$;

-- Claim at most one row per batch/lead. Inbound rows observe a 4-second quiet
-- window; superseded rows in the same burst are retained as ignored/coalesced.
CREATE OR REPLACE FUNCTION public.claim_whatsapp_buffer(
  p_worker text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 60
)
RETURNS SETOF public.lead_buffer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- Serialize only the short lease allocation transaction. Processing still
  -- runs concurrently across different batch keys after this function returns.
  PERFORM pg_advisory_xact_lock(hashtext('claim_whatsapp_buffer:v2'));
  PERFORM public.quarantine_expired_whatsapp_attempts(p_lease_seconds);

  WITH waiting AS (
    SELECT b.*,
      lag(b.created_at) OVER (
        PARTITION BY coalesce(b.batch_key,b.id::text)
        ORDER BY b.created_at,b.id
      ) AS previous_created_at
    FROM public.lead_buffer b
    WHERE b.direction='inbound' AND b.status IN ('buffered','retry')
      AND b.available_at<=now() AND b.payload->'conversation_commit' IS NULL
  ), segmented AS (
    SELECT waiting.*,
      sum(CASE
        WHEN previous_created_at IS NULL
          OR created_at-previous_created_at>interval '4 seconds' THEN 1
        ELSE 0
      END) OVER (
        PARTITION BY coalesce(batch_key,id::text)
        ORDER BY created_at,id
      ) AS burst_number
    FROM waiting
  ), bursts AS (
    SELECT coalesce(batch_key,id::text) AS effective_batch_key,burst_number,
      (array_agg(id ORDER BY created_at DESC,id DESC))[1] AS canonical_id,
      string_agg(coalesce(payload->>'text',''),E'\n' ORDER BY created_at,id) AS aggregate_text,
      jsonb_agg(jsonb_build_object('buffer_id',id,'text',payload->>'text',
        'created_at',created_at) ORDER BY created_at,id) AS burst_messages
    FROM segmented
    GROUP BY coalesce(batch_key,id::text),burst_number
    HAVING count(*)>1 AND max(created_at)<=now()-interval '4 seconds'
  )
  UPDATE public.lead_buffer c SET payload=jsonb_set(
      jsonb_set(coalesce(c.payload,'{}'::jsonb),'{text}',to_jsonb(b.aggregate_text),true),
      '{burst_messages}',b.burst_messages,true),updated_at=now()
    FROM bursts b WHERE c.id=b.canonical_id;

  WITH waiting AS (
    SELECT b.*,
      lag(b.created_at) OVER (
        PARTITION BY coalesce(b.batch_key,b.id::text)
        ORDER BY b.created_at,b.id
      ) AS previous_created_at
    FROM public.lead_buffer b
    WHERE b.direction='inbound' AND b.status IN ('buffered','retry')
      AND b.available_at<=now() AND b.payload->'conversation_commit' IS NULL
  ), segmented AS (
    SELECT waiting.*,
      sum(CASE
        WHEN previous_created_at IS NULL
          OR created_at-previous_created_at>interval '4 seconds' THEN 1
        ELSE 0
      END) OVER (
        PARTITION BY coalesce(batch_key,id::text)
        ORDER BY created_at,id
      ) AS burst_number
    FROM waiting
  ), bursts AS (
    SELECT coalesce(batch_key,id::text) AS effective_batch_key,burst_number,
      (array_agg(id ORDER BY created_at DESC,id DESC))[1] AS canonical_id
    FROM segmented
    GROUP BY coalesce(batch_key,id::text),burst_number
    HAVING count(*)>1 AND max(created_at)<=now()-interval '4 seconds'
  ), canonical AS (
    SELECT s.id,b.canonical_id
    FROM segmented s JOIN bursts b
      ON b.effective_batch_key=coalesce(s.batch_key,s.id::text)
     AND b.burst_number=s.burst_number
    WHERE s.id<>b.canonical_id
  )
  UPDATE public.lead_buffer b SET status = 'ignored', locked_at = NULL, locked_by = NULL,
    payload = coalesce(b.payload,'{}'::jsonb) || jsonb_build_object(
      'coalesced', true, 'coalesced_into', canonical.canonical_id,
      'coalesced_at', now()), updated_at = now()
   FROM canonical WHERE b.id = canonical.id;

  RETURN QUERY
  WITH eligible AS (
    SELECT b.id, b.batch_key, b.available_at, b.created_at
      FROM public.lead_buffer b
     WHERE (((b.status IN ('buffered','retry','pending_send') AND b.available_at <= now())
          OR (b.status = 'processing' AND b.locked_at < now() - make_interval(secs => greatest(p_lease_seconds,1))
              AND NOT (coalesce(b.payload,'{}'::jsonb) ? 'decision_attempt_started_at'
                       OR coalesce(b.payload,'{}'::jsonb) ? 'provider_attempt_started_at')))
       AND b.status <> 'awaiting_proof'
       AND (b.direction <> 'inbound' OR b.created_at <= now() - interval '4 seconds')
       AND (
         b.direction <> 'outbound'
         OR coalesce(b.payload->>'sender_type','') <> 'agent'
         OR EXISTS (
           SELECT 1 FROM public.conversation_turn_proofs proof
            WHERE proof.outbound_id=b.id::text
              AND coalesce((proof.proof_result->>'valid')::boolean,false)
         )
       )
       AND NOT EXISTS (
         SELECT 1 FROM public.lead_buffer newer
          WHERE newer.direction='inbound'
            AND newer.status IN ('buffered','retry')
            AND coalesce(newer.batch_key,newer.id::text)=coalesce(b.batch_key,b.id::text)
            AND (newer.created_at,newer.id)>(b.created_at,b.id)
            AND newer.created_at<=b.created_at+interval '4 seconds'
       )
       AND NOT EXISTS (
         SELECT 1 FROM public.lead_buffer active
          WHERE active.batch_key = b.batch_key AND active.status = 'processing' AND active.id <> b.id
       ))
  ), candidates AS (
    SELECT e.id FROM eligible e
     WHERE NOT EXISTS (
       SELECT 1 FROM eligible prior
        WHERE coalesce(prior.batch_key,prior.id::text)=coalesce(e.batch_key,e.id::text)
          AND (prior.available_at,prior.created_at,prior.id) < (e.available_at,e.created_at,e.id)
     )
     ORDER BY e.available_at,e.created_at,e.id
     LIMIT greatest(p_limit,1)
  )
  UPDATE public.lead_buffer b SET status='processing', locked_at=now(), locked_by=p_worker,
    attempt_count=b.attempt_count+1, updated_at=now()
   FROM candidates WHERE b.id=candidates.id RETURNING b.*;
END;
$$;

-- Resume gives the first backlog burst its quiet window and processes later
-- rows only after the previous turn has committed.
CREATE OR REPLACE FUNCTION public.requeue_waiting_human_whatsapp_buffer(p_lead_ref bigint)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE v_count integer; v_resumed_at timestamptz := now();
BEGIN
  WITH locked AS (
    SELECT id,created_at FROM public.lead_buffer
     WHERE lead_ref=p_lead_ref AND direction='inbound' AND status='waiting_human'
       AND payload->'conversation_commit' IS NULL
     ORDER BY created_at,id FOR UPDATE SKIP LOCKED
  )
  UPDATE public.lead_buffer b SET status='retry',
    available_at=v_resumed_at + interval '4 seconds',
    locked_at=NULL,locked_by=NULL,
    payload=(coalesce(b.payload,'{}'::jsonb)
      - 'decision_attempt_started_at' - 'decision_attempt_worker'
      - 'provider_attempt_started_at' - 'provider_attempt_worker')
      || jsonb_build_object('resumed_at',v_resumed_at,
                            'resume_coalesce_until',v_resumed_at + interval '4 seconds'),
    updated_at=now()
   FROM locked WHERE b.id=locked.id;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.finalize_proven_conversation_turn(uuid,uuid,bigint,text,uuid,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.commit_graph_turn_and_outbox_v3(jsonb,jsonb,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.graph_branch_rank_v3(uuid,uuid,text,vector,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.audit_conversation_turn_v3(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_proven_conversation_turn(uuid,uuid,bigint,text,uuid,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v3(jsonb,jsonb,jsonb,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.graph_branch_rank_v3(uuid,uuid,text,vector,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.audit_conversation_turn_v3(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_whatsapp_buffer(text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.requeue_waiting_human_whatsapp_buffer(bigint) TO service_role;
