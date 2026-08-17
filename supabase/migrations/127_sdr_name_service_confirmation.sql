-- Persist safe confirmation candidates and isolate service ranking from general RAG.
-- Production application and historical repair remain separately authorized.

ALTER TABLE public.conversation_facts
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.conversation_facts
  DROP CONSTRAINT IF EXISTS conversation_facts_metadata_object;
ALTER TABLE public.conversation_facts
  ADD CONSTRAINT conversation_facts_metadata_object
  CHECK (jsonb_typeof(metadata) = 'object');

CREATE OR REPLACE FUNCTION public.commit_graph_turn_v3(p_canonical_inbound_id text, p_persona_id uuid, p_lead_ref bigint, p_publication_id uuid, p_graph_checksum text, p_active_branch_node_id text, p_asked_question_node_ids text[], p_expected_revision bigint, p_facts jsonb, p_retrieval_trace jsonb, p_model_proposal jsonb, p_proof_result jsonb, p_repair_result jsonb, p_final_decision jsonb, p_outbound_id text DEFAULT NULL::text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_existing public.conversation_turn_proofs%ROWTYPE;
  v_ledger public.conversation_ledgers%ROWTYPE;
  v_fact jsonb; v_previous uuid; v_previous_is_current boolean;
  v_switched_previous uuid; v_next_revision bigint; v_invalidated_keys text[];
  v_previous_branch text;
  v_branch_action text;
  v_branch text;
  v_proven_active text[];
BEGIN
  SELECT coalesce(
    (SELECT operation->>'action'
       FROM jsonb_array_elements(coalesce(p_proof_result->'applied_service_operations','[]'::jsonb)) operation
      WHERE operation->>'action'='drop' LIMIT 1),
    'keep'
  ) INTO v_branch_action;
  IF nullif(btrim(p_canonical_inbound_id),'') IS NULL THEN
    RAISE EXCEPTION 'canonical inbound id is required';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text||':'||p_lead_ref::text));
  SELECT * INTO v_existing FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id=p_canonical_inbound_id FOR UPDATE;
  IF FOUND THEN
    RETURN jsonb_build_object('state','completed','deduplicated',true,
      'proof_id',v_existing.id,'ledger_id',v_existing.ledger_id,
      'outbound_id',v_existing.outbound_id);
  END IF;

  SELECT l.* INTO v_ledger FROM public.conversation_ledgers l
    JOIN public.conversation_journeys j ON j.id=l.journey_id AND j.is_current
   WHERE l.persona_id=p_persona_id AND l.lead_ref=p_lead_ref FOR UPDATE;
  IF NOT FOUND THEN
    IF coalesce(p_expected_revision,0)<>0 THEN
      RAISE EXCEPTION 'conversation_ledger_revision_cas: expected %, current absent',p_expected_revision
        USING ERRCODE='P0001',DETAIL='conversation_ledger_revision_cas';
    END IF;
    INSERT INTO public.conversation_ledgers(
      persona_id,lead_ref,active_branch_node_id,publication_id,
      graph_checksum,revision,asked_question_node_ids
    ) VALUES (
      p_persona_id,p_lead_ref,p_active_branch_node_id,p_publication_id,
      p_graph_checksum,1,coalesce(p_asked_question_node_ids,'{}')
    ) RETURNING * INTO v_ledger;
  ELSE
    v_previous_branch:=v_ledger.active_branch_node_id;
    IF v_ledger.revision<>coalesce(p_expected_revision,v_ledger.revision) THEN
      RAISE EXCEPTION 'conversation_ledger_revision_cas: expected %, current %',
        p_expected_revision,v_ledger.revision
        USING ERRCODE='P0001',DETAIL='conversation_ledger_revision_cas';
    END IF;
    IF v_ledger.publication_id<>p_publication_id THEN
      SELECT coalesce(array_agg(value),'{}'::text[]) INTO v_invalidated_keys
        FROM jsonb_array_elements_text(coalesce(p_retrieval_trace->'invalidated_fact_keys','[]'::jsonb));
      UPDATE public.conversation_facts SET is_current=false,updated_at=now()
       WHERE ledger_id=v_ledger.id AND is_current AND field_key=ANY(v_invalidated_keys);
    END IF;
    UPDATE public.conversation_ledgers SET
      active_branch_node_id=p_active_branch_node_id,publication_id=p_publication_id,
      graph_checksum=p_graph_checksum,revision=revision+1,
      asked_question_node_ids=coalesce(p_asked_question_node_ids,'{}'),updated_at=now()
     WHERE id=v_ledger.id RETURNING * INTO v_ledger;
  END IF;

  FOR v_fact IN SELECT value FROM jsonb_array_elements(coalesce(p_facts,'[]'::jsonb)) LOOP
    IF nullif(v_fact->>'field_key','') IS NULL
       OR nullif(v_fact->>'owner_node_id','') IS NULL
       OR nullif(v_fact->>'source_message_id','') IS NULL THEN
      RAISE EXCEPTION 'fact is missing field_key, owner_node_id or source_message_id';
    END IF;
    v_previous:=NULL; v_previous_is_current:=NULL; v_switched_previous:=NULL;
    SELECT id,is_current INTO v_previous,v_previous_is_current
      FROM public.conversation_facts
     WHERE ledger_id=v_ledger.id AND field_key=v_fact->>'field_key'
       AND owner_node_id=v_fact->>'owner_node_id'
     ORDER BY revision DESC LIMIT 1 FOR UPDATE;
    IF v_branch_action='drop' AND v_previous_branch IS NOT NULL
       AND v_previous_branch IS DISTINCT FROM p_active_branch_node_id
       AND v_fact->>'owner_node_id'=p_active_branch_node_id THEN
      SELECT id INTO v_switched_previous FROM public.conversation_facts
       WHERE ledger_id=v_ledger.id AND field_key=v_fact->>'field_key'
         AND owner_node_id=v_previous_branch AND is_current
       ORDER BY revision DESC LIMIT 1 FOR UPDATE;
      IF v_switched_previous IS NOT NULL THEN
        UPDATE public.conversation_facts SET is_current=false,updated_at=now()
         WHERE id=v_switched_previous;
      END IF;
    END IF;
    IF v_previous IS NOT NULL AND v_previous_is_current THEN
      UPDATE public.conversation_facts SET is_current=false,updated_at=now()
       WHERE id=v_previous;
    END IF;
    SELECT coalesce(max(revision),0)+1 INTO v_next_revision
      FROM public.conversation_facts
     WHERE ledger_id=v_ledger.id AND field_key=v_fact->>'field_key';
    INSERT INTO public.conversation_facts(
      ledger_id,field_key,owner_node_id,status,value_json,source_message_id,
      evidence_span,confidence,metadata,revision,supersedes_fact_id
    ) VALUES (
      v_ledger.id,v_fact->>'field_key',v_fact->>'owner_node_id',v_fact->>'status',
      v_fact->'value',v_fact->>'source_message_id',v_fact->>'evidence_span',
      nullif(v_fact->>'confidence','')::numeric,coalesce(v_fact->'metadata','{}'::jsonb),
      v_next_revision,coalesce(v_previous,v_switched_previous)
    );
  END LOOP;

  IF jsonb_typeof(p_proof_result->'next_active_branch_node_ids')='array' THEN
    SELECT coalesce(array_agg(value),'{}'::text[]) INTO v_proven_active
      FROM jsonb_array_elements_text(p_proof_result->'next_active_branch_node_ids');
    IF (cardinality(v_proven_active)=0 AND p_active_branch_node_id IS NOT NULL)
       OR (cardinality(v_proven_active)>0 AND (
           p_active_branch_node_id IS NULL
           OR p_active_branch_node_id<>ALL(v_proven_active)
       )) THEN
      RAISE EXCEPTION 'branch focus invariant failed' USING ERRCODE='23514';
    END IF;
    UPDATE public.conversation_ledger_branches SET state='dropped',completed_at=now()
     WHERE ledger_id=v_ledger.id AND state='active'
       AND branch_anchor_node_id<>ALL(v_proven_active);
    FOREACH v_branch IN ARRAY v_proven_active LOOP
      INSERT INTO public.conversation_ledger_branches(
        ledger_id,branch_anchor_node_id,state
      ) VALUES (v_ledger.id,v_branch,'active')
      ON CONFLICT (ledger_id,branch_anchor_node_id) DO UPDATE
        SET state='active',completed_at=NULL;
    END LOOP;
  END IF;

  INSERT INTO public.conversation_turn_proofs(
    canonical_inbound_id,ledger_id,publication_id,retrieval_trace,model_proposal,
    proof_result,repair_result,final_decision,outbound_id
  ) VALUES (
    p_canonical_inbound_id,v_ledger.id,p_publication_id,
    coalesce(p_retrieval_trace,'{}'::jsonb),coalesce(p_model_proposal,'{}'::jsonb),
    coalesce(p_proof_result,'{}'::jsonb),coalesce(p_repair_result,'{}'::jsonb),
    coalesce(p_final_decision,'{}'::jsonb),p_outbound_id
  ) RETURNING * INTO v_existing;
  RETURN jsonb_build_object('state','completed','deduplicated',false,
    'proof_id',v_existing.id,'ledger_id',v_ledger.id,
    'ledger_revision',v_ledger.revision,'outbound_id',p_outbound_id);
END $$;

CREATE OR REPLACE FUNCTION public.graph_service_rank_v3(
  p_persona_id uuid,p_publication_id uuid,p_query_embedding vector(1536),
  p_limit integer DEFAULT 8
) RETURNS TABLE(
  branch_anchor_node_id text,score double precision,snippet text,chunk_id uuid
) LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH ranked AS (
    SELECT c.branch_anchor_node_id,c.id,
      greatest(0,1-(c.embedding<=>p_query_embedding))::double precision score,
      left(coalesce(c.chunk_summary,c.chunk_text,''),240) snippet,
      row_number() OVER (
        PARTITION BY c.branch_anchor_node_id
        ORDER BY c.embedding<=>p_query_embedding,c.id
      ) position
      FROM public.knowledge_rag_chunks c
     WHERE c.persona_id=p_persona_id AND c.publication_id=p_publication_id
       AND c.source_graph_node_id=c.branch_anchor_node_id
       AND c.embedding IS NOT NULL
       AND c.projection_status IN ('ready','published')
  )
  SELECT ranked.branch_anchor_node_id,ranked.score,ranked.snippet,ranked.id
    FROM ranked WHERE position=1
   ORDER BY score DESC,branch_anchor_node_id
   LIMIT greatest(1,least(coalesce(p_limit,8),32));
$$;

CREATE OR REPLACE FUNCTION public.conversation_carry_over_facts_v1(p_journey_id uuid)
RETURNS SETOF public.conversation_facts
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT f.* FROM public.conversation_facts f
    JOIN public.conversation_ledgers l ON l.id=f.ledger_id
   WHERE l.journey_id=p_journey_id AND f.is_current AND f.status='known'
     AND coalesce(f.metadata->'confirmation'->>'transition','confirmed')
         NOT IN ('pending','rejected');
$$;

CREATE OR REPLACE FUNCTION public.repair_sdr_false_service_fact_v1(
  p_ledger_id uuid,p_fact_id uuid,p_expected_revision bigint,p_apply boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_ledger public.conversation_ledgers%ROWTYPE;
  v_fact public.conversation_facts%ROWTYPE;
  v_authorized boolean; v_next_focus text; v_active_after text[];
BEGIN
  SELECT * INTO v_ledger FROM public.conversation_ledgers WHERE id=p_ledger_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger not found' USING ERRCODE='P0002'; END IF;
  IF v_ledger.revision<>p_expected_revision THEN
    RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001';
  END IF;
  SELECT * INTO v_fact FROM public.conversation_facts
   WHERE id=p_fact_id AND ledger_id=p_ledger_id AND is_current
     AND field_key='servico' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'current service fact not found' USING ERRCODE='P0002'; END IF;
  SELECT EXISTS (
    SELECT 1 FROM public.conversation_turn_proofs proof,
      jsonb_array_elements(coalesce(proof.proof_result->'applied_service_operations','[]'::jsonb)) operation
     WHERE proof.ledger_id=p_ledger_id
       AND operation->>'branch_anchor_node_id'=v_fact.owner_node_id
       AND operation->>'evidence_type' IN ('exact_catalog','confirmed_candidate')
  ) INTO v_authorized;
  IF v_authorized THEN
    RETURN jsonb_build_object('changed',false,'apply',p_apply,'ledger_id',p_ledger_id,
      'fact_id',p_fact_id,'revision',v_ledger.revision,'reason','authorized_service_evidence');
  END IF;
  SELECT array_agg(branch_anchor_node_id ORDER BY added_at),
         (array_agg(branch_anchor_node_id ORDER BY added_at DESC))[1]
    INTO v_active_after,v_next_focus
    FROM public.conversation_ledger_branches
   WHERE ledger_id=p_ledger_id AND state='active'
     AND branch_anchor_node_id<>v_fact.owner_node_id;
  IF NOT p_apply THEN
    RETURN jsonb_build_object('changed',false,'apply',false,'ledger_id',p_ledger_id,
      'fact_id',p_fact_id,'revision',v_ledger.revision,
      'false_branch_node_id',v_fact.owner_node_id,
      'next_active_branch_node_ids',coalesce(to_jsonb(v_active_after),'[]'::jsonb),
      'next_active_branch_node_id',v_next_focus,'reason','service_without_authorized_evidence');
  END IF;
  UPDATE public.conversation_facts SET is_current=false,updated_at=now() WHERE id=p_fact_id;
  UPDATE public.conversation_ledger_branches SET state='dropped',completed_at=now()
   WHERE ledger_id=p_ledger_id AND branch_anchor_node_id=v_fact.owner_node_id AND state='active';
  UPDATE public.conversation_ledgers SET active_branch_node_id=v_next_focus,
    revision=revision+1,updated_at=now()
   WHERE id=p_ledger_id AND revision=p_expected_revision;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001'; END IF;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,source,payload)
  VALUES ('sdr_false_service_fact_repaired','conversation_ledger',p_ledger_id,
    v_ledger.persona_id,'migration_127_repair',jsonb_build_object(
      'fact_id',p_fact_id,'false_branch_node_id',v_fact.owner_node_id,
      'previous_revision',p_expected_revision,'revision',p_expected_revision+1,
      'next_active_branch_node_ids',coalesce(to_jsonb(v_active_after),'[]'::jsonb),
      'next_active_branch_node_id',v_next_focus));
  RETURN jsonb_build_object('changed',true,'apply',true,'ledger_id',p_ledger_id,
    'fact_id',p_fact_id,'previous_revision',p_expected_revision,
    'revision',p_expected_revision+1,'next_active_branch_node_id',v_next_focus,
    'reason','service_without_authorized_evidence');
END $$;

REVOKE ALL ON FUNCTION public.graph_service_rank_v3(uuid,uuid,vector,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.conversation_carry_over_facts_v1(uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.repair_sdr_false_service_fact_v1(uuid,uuid,bigint,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.graph_service_rank_v3(uuid,uuid,vector,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.conversation_carry_over_facts_v1(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.repair_sdr_false_service_fact_v1(uuid,uuid,bigint,boolean) TO service_role;
