-- Scope conversation runtime reads to the current journey, carry only fields
-- explicitly published with carry_over=true, and expose one terminal commit
-- count to the direct WA Validator. No table or destructive repair is added.

CREATE OR REPLACE FUNCTION public.maybe_open_next_conversation_journey_v1(
  p_journey_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_origin public.conversation_journeys%ROWTYPE;
  v_next public.conversation_journeys%ROWTYPE;
  v_origin_ledger public.conversation_ledgers%ROWTYPE;
  v_next_ledger public.conversation_ledgers%ROWTYPE;
  v_carry_count integer:=0;
BEGIN
  SELECT * INTO v_origin FROM public.conversation_journeys
   WHERE id=p_journey_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'journey not found' USING ERRCODE='P0002';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended(v_origin.persona_id::text||':'||v_origin.lead_ref::text,0)
  );
  IF v_origin.qualification_confirmed_at IS NULL OR NOT EXISTS (
    SELECT 1 FROM public.sales_conversions c WHERE c.journey_id=v_origin.id
      AND c.conversion_type='purchase' AND c.completed_at IS NOT NULL
  ) THEN
    RETURN jsonb_build_object(
      'new_journey_created',false,'origin_journey',to_jsonb(v_origin)
    );
  END IF;

  SELECT * INTO v_next FROM public.conversation_journeys
   WHERE previous_journey_id=v_origin.id ORDER BY sequence LIMIT 1;
  IF NOT FOUND THEN
    UPDATE public.conversation_journeys SET
      is_current=false,state='closed',closed_at=coalesce(closed_at,now()),updated_at=now()
     WHERE persona_id=v_origin.persona_id AND lead_ref=v_origin.lead_ref AND is_current;
    INSERT INTO public.conversation_journeys(
      persona_id,lead_ref,sequence,previous_journey_id,publication_id,
      graph_checksum,opening_reason
    ) VALUES (
      v_origin.persona_id,v_origin.lead_ref,v_origin.sequence+1,v_origin.id,
      v_origin.publication_id,v_origin.graph_checksum,'qualified_purchase_completed'
    ) RETURNING * INTO v_next;

    SELECT * INTO v_origin_ledger FROM public.conversation_ledgers
     WHERE journey_id=v_origin.id FOR UPDATE;
    INSERT INTO public.conversation_ledgers(
      persona_id,lead_ref,active_branch_node_id,publication_id,graph_checksum,
      revision,asked_question_node_ids,journey_id
    ) VALUES (
      v_next.persona_id,v_next.lead_ref,NULL,v_next.publication_id,
      v_next.graph_checksum,0,'{}',v_next.id
    ) RETURNING * INTO v_next_ledger;

    IF v_origin_ledger.id IS NOT NULL THEN
      INSERT INTO public.conversation_facts(
        ledger_id,field_key,owner_node_id,status,value_json,source_message_id,
        evidence_span,confidence,revision,supersedes_fact_id,is_current
      )
      SELECT v_next_ledger.id,f.field_key,f.owner_node_id,f.status,f.value_json,
             f.source_message_id,f.evidence_span,f.confidence,1,NULL,true
        FROM public.conversation_facts f
       WHERE f.ledger_id=v_origin_ledger.id AND f.is_current
         AND EXISTS (
           SELECT 1
             FROM public.graph_publications gp
             CROSS JOIN LATERAL jsonb_array_elements(
               coalesce(gp.document_json->'common_contract'->'fields','[]'::jsonb)
             ) common_field
            WHERE gp.id=v_next.publication_id
              AND common_field->>'key'=f.field_key
              AND common_field->>'owner_node_id'=f.owner_node_id
              AND coalesce((common_field->>'carry_over')::boolean,false)
         );
      GET DIAGNOSTICS v_carry_count=ROW_COUNT;
    END IF;
    UPDATE public.conversation_journeys SET
      metadata=metadata||jsonb_build_object(
        'carry_over_fact_count',v_carry_count,
        'carry_over_source_journey_id',v_origin.id
      ),updated_at=now()
     WHERE id=v_next.id RETURNING * INTO v_next;
    RETURN jsonb_build_object(
      'new_journey_created',true,'origin_journey',to_jsonb(v_origin),
      'new_journey',to_jsonb(v_next),'carry_over_fact_count',v_carry_count
    );
  END IF;
  RETURN jsonb_build_object(
    'new_journey_created',false,'origin_journey',to_jsonb(v_origin),
    'new_journey',to_jsonb(v_next),
    'carry_over_fact_count',coalesce((v_next.metadata->>'carry_over_fact_count')::integer,0)
  );
END $$;

CREATE OR REPLACE FUNCTION public.graph_turn_context_batch_v3(
  p_persona_id uuid,p_lead_ref bigint,p_message_limit integer DEFAULT 8
)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH publication AS (
    SELECT * FROM public.graph_publications
     WHERE persona_id=p_persona_id AND status='active' LIMIT 1
  ), journey AS (
    SELECT * FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current LIMIT 1
  ), ledger AS (
    SELECT l.* FROM public.conversation_ledgers l JOIN journey j ON j.id=l.journey_id
     WHERE l.persona_id=p_persona_id AND l.lead_ref=p_lead_ref LIMIT 1
  ), facts AS (
    SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.field_key,f.revision),'[]'::jsonb) value
      FROM public.conversation_facts f JOIN ledger l ON l.id=f.ledger_id WHERE f.is_current
  ), branches AS (
    SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.added_at),'[]'::jsonb) value
      FROM public.conversation_ledger_branches b JOIN ledger l ON l.id=b.ledger_id
     WHERE b.state='active'
  ), messages AS (
    SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.created_at,m.id),'[]'::jsonb) value FROM (
      SELECT id,lead_id,role,content,direction,external_message_id,created_at
        FROM public.messages WHERE lead_id=p_lead_ref
       ORDER BY created_at DESC,id DESC
       LIMIT greatest(1,least(coalesce(p_message_limit,8),20))
    ) m
  ) SELECT jsonb_build_object(
    'publication',(SELECT to_jsonb(publication) FROM publication),
    'journey',(SELECT to_jsonb(journey) FROM journey),
    'ledger',(SELECT to_jsonb(ledger) FROM ledger),
    'facts',(SELECT value FROM facts),'branches',(SELECT value FROM branches),
    'messages',(SELECT value FROM messages));
$$;

CREATE OR REPLACE FUNCTION public.audit_conversation_turn_v3(p_inbound_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH inbound AS (
    SELECT * FROM public.lead_buffer WHERE id=p_inbound_id
  ), proof AS (
    SELECT * FROM public.conversation_turn_proofs
     WHERE canonical_inbound_id=p_inbound_id::text
  ), outbound AS (
    SELECT b.* FROM public.lead_buffer b JOIN proof p ON p.outbound_id=b.id::text
  ) SELECT jsonb_build_object(
    'inbound_id',p_inbound_id,
    'inbound_count',(SELECT count(*) FROM inbound),
    'decision_count',(SELECT count(*) FROM proof WHERE final_decision<>'{}'::jsonb),
    'proof_count',(SELECT count(*) FROM proof),
    'valid_proof_count',(SELECT count(*) FROM proof WHERE coalesce((proof_result->>'valid')::boolean,false)),
    'terminal_count',(SELECT count(*) FROM inbound WHERE coalesce(
      payload->'conversation_commit'->>'status',payload->'conversation_commit'->>'state'
    )='completed'),
    'outbound_count',(SELECT count(*) FROM outbound),
    'outbound_status',(SELECT status FROM outbound LIMIT 1),
    'outbound_released_after_proof',coalesce((
      SELECT o.updated_at>=p.created_at FROM outbound o JOIN proof p ON p.outbound_id=o.id::text LIMIT 1
    ),true),
    'commit_state',(SELECT coalesce(
      payload->'conversation_commit'->>'status',payload->'conversation_commit'->>'state'
    ) FROM inbound LIMIT 1),
    'active_branch_node_id',(SELECT l.active_branch_node_id FROM proof p JOIN public.conversation_ledgers l ON l.id=p.ledger_id LIMIT 1),
    'ledger_revision',(SELECT l.revision FROM proof p JOIN public.conversation_ledgers l ON l.id=p.ledger_id LIMIT 1),
    'current_fact_count',(SELECT count(*) FROM proof p JOIN public.conversation_facts f ON f.ledger_id=p.ledger_id AND f.is_current),
    'prompt_tokens',(SELECT (retrieval_trace->'token_usage'->>'prompt_tokens')::integer FROM proof LIMIT 1),
    'prompt_estimated_tokens',(SELECT (retrieval_trace->'token_usage'->>'prompt_estimated_tokens')::integer FROM proof LIMIT 1),
    'model_calls',(SELECT (retrieval_trace->'token_usage'->>'model_calls')::integer FROM proof LIMIT 1),
    'repair_calls',(SELECT (retrieval_trace->'token_usage'->>'repair_calls')::integer FROM proof LIMIT 1),
    'deterministic_branch_match',(SELECT coalesce((retrieval_trace->>'deterministic_branch_match')::boolean,false) FROM proof LIMIT 1)
  );
$$;

REVOKE ALL ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.audit_conversation_turn_v3(uuid)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.audit_conversation_turn_v3(uuid)
  TO service_role;
