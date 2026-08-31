-- Function-only exactly-once hardening for model-owned conversation turns.
-- No table, destructive cleanup, publication or binding mutation is included.
-- Applying this migration requires its own explicit production authorization.

CREATE OR REPLACE FUNCTION public.commit_graph_turn_and_outbox_v5(
  p_turn jsonb,
  p_outbound_buffer jsonb DEFAULT NULL,
  p_outbound_message jsonb DEFAULT NULL,
  p_result jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public,pg_temp
AS $$
DECLARE
  v_canonical_id text:=nullif(p_turn->>'canonical_inbound_id','');
  v_existing public.conversation_turn_proofs%ROWTYPE;
  v_effective_turn jsonb;
  v_effective_proof jsonb;
  v_asked_question_ids jsonb;
  v_asked_field_keys jsonb;
  v_result jsonb;
  v_outbound_status text;
  v_message text;
  v_detail text;
  v_original_hint text;
  v_sqlstate text;
  v_reason_class text;
  v_retry_hint text;
BEGIN
  IF v_canonical_id IS NULL
     OR nullif(p_turn->>'persona_id','') IS NULL
     OR nullif(p_turn->>'binding_id','') IS NULL
     OR nullif(p_turn->>'correlation_id','') IS NULL THEN
    RAISE EXCEPTION 'turn identity is incomplete' USING ERRCODE='23514';
  END IF;

  -- The canonical inbound is the lock and replay key. The lookup happens
  -- before any outbox creation, including journey_action=none.
  PERFORM pg_advisory_xact_lock(hashtextextended(v_canonical_id,0));
  SELECT * INTO v_existing
    FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id=v_canonical_id
   FOR UPDATE;
  IF FOUND THEN
    IF v_existing.outbound_id IS NOT NULL THEN
      SELECT status INTO v_outbound_status
        FROM public.lead_buffer
       WHERE id=v_existing.outbound_id::uuid;
    END IF;
    RETURN jsonb_build_object(
      'state','completed',
      'deduplicated',true,
      'canonical_inbound_id',v_canonical_id,
      'proof_id',v_existing.id,
      'ledger_id',v_existing.ledger_id,
      'journey_action',coalesce(v_existing.final_decision->>'journey_action',p_turn->>'journey_action','continue'),
      'outbound_buffer_id',v_existing.outbound_id,
      'outbound_status',v_outbound_status
    );
  END IF;

  IF p_outbound_buffer IS NOT NULL AND NOT coalesce(
    (p_turn->'proof_result'->>'delivery_authorized')::boolean,
    (p_turn->'proof_result'->>'valid')::boolean,
    false
  ) THEN
    RAISE EXCEPTION 'outbound delivery is not authorized by proof'
      USING ERRCODE='23514';
  END IF;

  -- Only an actually created outbound can spend a question. The legacy node
  -- ids remain in parallel while new consumers read semantic field keys.
  v_asked_question_ids:=CASE WHEN p_outbound_buffer IS NULL THEN '[]'::jsonb
    ELSE coalesce(p_turn->'proof_result'->'asked_question_node_ids','[]'::jsonb) END;
  v_asked_field_keys:=CASE WHEN p_outbound_buffer IS NULL THEN '[]'::jsonb
    ELSE coalesce(p_turn->'proof_result'->'asked_field_keys','[]'::jsonb) END;
  v_effective_proof:=coalesce(p_turn->'proof_result','{}'::jsonb)
    ||jsonb_build_object(
      'asked_question_node_ids',v_asked_question_ids,
      'asked_field_keys',v_asked_field_keys,
      'model_reply_preserved',coalesce((p_turn->'proof_result'->>'model_reply_preserved')::boolean,true)
    );
  v_effective_turn:=p_turn||jsonb_build_object('proof_result',v_effective_proof);

  v_result:=public.commit_graph_turn_and_outbox_v4(
    v_effective_turn,p_outbound_buffer,p_outbound_message,p_result
  );
  UPDATE public.conversation_turn_proofs
     SET proof_result=v_effective_proof
   WHERE canonical_inbound_id=v_canonical_id;
  RETURN coalesce(v_result,'{}'::jsonb)||jsonb_build_object('deduplicated',false);

EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS
    v_message=MESSAGE_TEXT,
    v_detail=PG_EXCEPTION_DETAIL,
    v_original_hint=PG_EXCEPTION_HINT,
    v_sqlstate=RETURNED_SQLSTATE;
  v_reason_class:=CASE
    WHEN v_message ILIKE '%identity%' OR v_message ILIKE '%persona%'
      OR v_message ILIKE '%binding%' THEN 'identity_scope_violation'
    WHEN v_message ILIKE '%proof%' OR v_message ILIKE '%delivery%authorized%'
      THEN 'delivery_authorization'
    WHEN v_message ILIKE '%outbound%' OR v_sqlstate='23505'
      THEN 'exactly_once_conflict'
    WHEN v_message ILIKE '%revision%' OR v_message ILIKE '%CAS%'
      THEN 'ledger_cas_conflict'
    WHEN v_message ILIKE '%journey%' THEN 'journey_state_conflict'
    ELSE 'commit_constraint_violation'
  END;
  v_retry_hint:=CASE v_reason_class
    WHEN 'identity_scope_violation' THEN 'do_not_retry_cross_scope'
    WHEN 'delivery_authorization' THEN 'repair_model_once_then_hold'
    WHEN 'exactly_once_conflict' THEN 'lookup_existing_proof_before_retry'
    WHEN 'ledger_cas_conflict' THEN 'reload_ledger_then_retry_same_canonical_inbound'
    ELSE 'retry_same_canonical_inbound'
  END;
  RAISE EXCEPTION 'conversation commit rejected'
    USING ERRCODE='P0001',
      DETAIL=jsonb_build_object(
        'reason_class',v_reason_class,
        'original_sqlstate',v_sqlstate,
        'detail',left(coalesce(v_detail,v_message,''),500)
      )::text,
      HINT=coalesce(nullif(v_original_hint,''),v_retry_hint);
END;
$$;

REVOKE ALL ON FUNCTION public.commit_graph_turn_and_outbox_v5(jsonb,jsonb,jsonb,jsonb)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v5(jsonb,jsonb,jsonb,jsonb)
  TO service_role,brain_runtime;

CREATE OR REPLACE FUNCTION public.release_conversation_commit_for_retry_v1(
  p_canonical_inbound_id text,
  p_reason text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public,pg_temp
AS $$
DECLARE
  v_inbound public.lead_buffer%ROWTYPE;
  v_existing public.conversation_turn_proofs%ROWTYPE;
  v_commit_status text;
BEGIN
  IF nullif(p_canonical_inbound_id,'') IS NULL THEN
    RAISE EXCEPTION 'canonical inbound id is required' USING ERRCODE='23514';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_canonical_inbound_id,0));
  SELECT * INTO v_existing
    FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id=p_canonical_inbound_id
   FOR UPDATE;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'updated',false,
      'status','completed',
      'deduplicated',true,
      'proof_id',v_existing.id,
      'outbound_id',v_existing.outbound_id
    );
  END IF;

  SELECT * INTO v_inbound
    FROM public.lead_buffer
   WHERE id::text=p_canonical_inbound_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'canonical inbound not found' USING ERRCODE='23514';
  END IF;

  v_commit_status:=coalesce(v_inbound.payload->'conversation_commit'->>'status','');
  IF v_commit_status='completed' THEN
    RETURN jsonb_build_object(
      'updated',false,
      'status','completed',
      'deduplicated',true,
      'attempt_count',v_inbound.attempt_count,
      'max_attempts',v_inbound.max_attempts
    );
  END IF;

  UPDATE public.lead_buffer
     SET payload=(coalesce(v_inbound.payload,'{}'::jsonb)
           - 'conversation_commit'
           - 'decision_attempt_started_at'
           - 'decision_attempt_worker')
           ||jsonb_build_object(
             'last_conversation_failure',jsonb_build_object(
               'reason',left(coalesce(p_reason,'technical_failure'),1000),
               'retryable',true
             )
           ),
         updated_at=now()
   WHERE id=v_inbound.id;

  RETURN jsonb_build_object(
    'updated',true,
    'status','retry',
    'deduplicated',false,
    'attempt_count',v_inbound.attempt_count,
    'max_attempts',v_inbound.max_attempts
  );
END;
$$;

REVOKE ALL ON FUNCTION public.release_conversation_commit_for_retry_v1(text,text)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.release_conversation_commit_for_retry_v1(text,text)
  TO service_role,brain_runtime;
