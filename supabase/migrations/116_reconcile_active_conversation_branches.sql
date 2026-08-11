-- Reconcile the complete active service set in the same transaction as the
-- graph ledger, proof and outbox commit. No new tables are introduced.

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
  v_active_branches text[];
  v_inbound public.lead_buffer%ROWTYPE;
  v_burst_version timestamptz;
  v_newer_count integer;
  v_member_ids uuid[];
BEGIN
  IF nullif(p_turn->>'canonical_inbound_id','') IS NULL
     OR nullif(p_turn->>'binding_id','') IS NULL
     OR nullif(p_turn->>'correlation_id','') IS NULL THEN
    RAISE EXCEPTION 'turn identity is incomplete' USING ERRCODE='23514';
  END IF;
  SELECT * INTO v_inbound FROM public.lead_buffer
   WHERE id=(p_turn->>'canonical_inbound_id')::uuid FOR UPDATE;
  IF v_inbound.id IS NULL THEN
    RAISE EXCEPTION 'canonical inbound not found' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(coalesce(v_inbound.batch_key,v_inbound.id::text)));
  v_burst_version := nullif(v_inbound.payload->>'burst_version','')::timestamptz;
  SELECT count(*) INTO v_newer_count FROM public.lead_buffer newer
   WHERE newer.direction='inbound' AND newer.status IN ('buffered','retry')
     AND coalesce(newer.batch_key,newer.id::text)=coalesce(v_inbound.batch_key,v_inbound.id::text)
     AND newer.id<>v_inbound.id
     AND (v_burst_version IS NULL OR newer.created_at>v_burst_version);
  IF v_newer_count>0 THEN
    UPDATE public.lead_buffer SET status='buffered',available_at=now()+interval '4 seconds',
      locked_at=NULL,locked_by=NULL,
      payload=(coalesce(payload,'{}'::jsonb)-'conversation_commit'
        -'decision_attempt_started_at'-'decision_attempt_worker')
        || jsonb_build_object('burst_superseded_at',now()),updated_at=now()
     WHERE id=v_inbound.id;
    RETURN jsonb_build_object('state','burst_superseded','burst_superseded',true,
      'canonical_inbound_id',v_inbound.id,'newer_member_count',v_newer_count);
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

  v_active_branches := ARRAY(
    SELECT DISTINCT branch.value
      FROM jsonb_array_elements_text(
        coalesce(p_turn->'active_branch_node_ids','[]'::jsonb)
      ) AS branch(value)
     WHERE nullif(branch.value, '') IS NOT NULL
  );
  IF cardinality(v_active_branches) = 0 AND nullif(p_turn->>'active_branch_node_id','') IS NOT NULL THEN
    v_active_branches := ARRAY[p_turn->>'active_branch_node_id'];
  END IF;

  UPDATE public.conversation_ledger_branches
     SET state='dropped', completed_at=now()
   WHERE ledger_id=(v_graph->>'ledger_id')::uuid
     AND state='active'
     AND NOT (branch_anchor_node_id = ANY(v_active_branches));

  FOREACH v_branch IN ARRAY v_active_branches LOOP
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

  SELECT array_agg(value::uuid) INTO v_member_ids
    FROM jsonb_array_elements_text(coalesce(v_inbound.payload->'burst_member_ids','[]'::jsonb));
  IF v_member_ids IS NOT NULL THEN
    UPDATE public.lead_buffer SET status='ignored',locked_at=NULL,locked_by=NULL,
      payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
        'coalesced',true,'coalesced_into',v_inbound.id,'coalesced_at',now()),updated_at=now()
     WHERE id=ANY(v_member_ids) AND id<>v_inbound.id AND direction='inbound'
       AND status IN ('buffered','retry');
  END IF;
  RETURN jsonb_build_object('state','completed','graph_turn',v_graph,
    'outbound_buffer_id',v_outbound_id,
    'outbound_status',CASE
      WHEN v_outbound_id IS NULL THEN NULL
      WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN 'sent'
      ELSE 'pending_send' END);
END;
$$;

REVOKE ALL ON FUNCTION public.commit_graph_turn_and_outbox_v3(jsonb,jsonb,jsonb,jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v3(jsonb,jsonb,jsonb,jsonb)
  TO service_role;
