-- Preserve every inbound as evidence and coalesce only after the final proof.
-- Burst metadata lives in lead_buffer.payload; no new table/column is needed.

CREATE OR REPLACE FUNCTION public.claim_whatsapp_buffer(
  p_worker text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 60
)
RETURNS SETOF public.lead_buffer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('claim_whatsapp_buffer:v3'));
  PERFORM public.quarantine_expired_whatsapp_attempts(p_lease_seconds);

  RETURN QUERY
  WITH eligible AS (
    SELECT b.id, b.batch_key, b.available_at, b.created_at, b.direction
      FROM public.lead_buffer b
     WHERE (((b.status IN ('buffered','retry','pending_send') AND b.available_at <= now())
          OR (b.status = 'processing' AND b.locked_at < now() - make_interval(secs => greatest(p_lease_seconds,1))
              AND NOT (coalesce(b.payload,'{}'::jsonb) ? 'decision_attempt_started_at'
                       OR coalesce(b.payload,'{}'::jsonb) ? 'provider_attempt_started_at')))
       AND b.status <> 'awaiting_proof'
       AND (b.direction <> 'inbound' OR b.created_at <= now() - interval '4 seconds')
       AND (b.direction <> 'outbound'
         OR coalesce(b.payload->>'sender_type','') <> 'agent'
         OR EXISTS (SELECT 1 FROM public.conversation_turn_proofs proof
                     WHERE proof.outbound_id=b.id::text
                       AND coalesce((proof.proof_result->>'valid')::boolean,false)))
       AND NOT EXISTS (
         SELECT 1 FROM public.lead_buffer newer
          WHERE newer.direction='inbound' AND newer.status IN ('buffered','retry')
            AND coalesce(newer.batch_key,newer.id::text)=coalesce(b.batch_key,b.id::text)
            AND (newer.created_at,newer.id)>(b.created_at,b.id)
            AND newer.created_at>now()-interval '4 seconds'
       )
       AND NOT EXISTS (
         SELECT 1 FROM public.lead_buffer active
          WHERE active.batch_key=b.batch_key AND active.status='processing' AND active.id<>b.id
       ))
  ), candidates AS (
    SELECT e.id FROM eligible e
     WHERE (e.direction='inbound' AND NOT EXISTS (
       SELECT 1 FROM eligible later
        WHERE later.direction='inbound'
          AND coalesce(later.batch_key,later.id::text)=coalesce(e.batch_key,e.id::text)
          AND (later.created_at,later.id)>(e.created_at,e.id)
     )) OR (e.direction<>'inbound' AND NOT EXISTS (
       SELECT 1 FROM eligible prior
        WHERE coalesce(prior.batch_key,prior.id::text)=coalesce(e.batch_key,e.id::text)
          AND (prior.available_at,prior.created_at,prior.id)<(e.available_at,e.created_at,e.id)
     ))
     ORDER BY e.available_at,e.created_at,e.id
     LIMIT greatest(p_limit,1)
  ), burst AS (
    SELECT c.id AS canonical_id,
      jsonb_agg(jsonb_build_object(
        'buffer_id',m.id,'text',m.payload->>'text','created_at',m.created_at
      ) ORDER BY m.created_at,m.id) AS evidence_messages,
      array_agg(m.id ORDER BY m.created_at,m.id) AS member_ids,
      string_agg(coalesce(m.payload->>'text',''),E'\n' ORDER BY m.created_at,m.id) AS aggregate_text,
      max(m.created_at) AS version_at
    FROM candidates c
    JOIN public.lead_buffer anchor ON anchor.id=c.id
    JOIN public.lead_buffer m
      ON m.direction='inbound' AND m.status IN ('buffered','retry')
     AND coalesce(m.batch_key,m.id::text)=coalesce(anchor.batch_key,anchor.id::text)
     AND m.created_at<=now()-interval '4 seconds'
    WHERE anchor.direction='inbound'
    GROUP BY c.id
  )
  UPDATE public.lead_buffer b SET
    status='processing',locked_at=now(),locked_by=p_worker,
    attempt_count=b.attempt_count+1,updated_at=now(),
    payload=CASE WHEN burst.canonical_id IS NULL THEN b.payload ELSE
      jsonb_set(jsonb_set(jsonb_set(jsonb_set(
        coalesce(b.payload,'{}'::jsonb),'{text}',to_jsonb(burst.aggregate_text),true),
        '{evidence_messages}',burst.evidence_messages,true),
        '{burst_member_ids}',to_jsonb(burst.member_ids),true),
        '{burst_version}',to_jsonb(burst.version_at),true)
      END
  FROM candidates c
  LEFT JOIN burst ON burst.canonical_id=c.id
  WHERE b.id=c.id
  RETURNING b.*;
END;
$$;

-- Replace the final atomic boundary so a message arriving while context/model
-- work is running reopens the burst before any fact, proof or outbox is written.
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
  v_graph jsonb; v_envelope jsonb; v_outbound_id uuid; v_final_result jsonb;
  v_branch text; v_inbound public.lead_buffer%ROWTYPE; v_burst_version timestamptz;
  v_newer_count integer; v_member_ids uuid[];
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
    IF p_outbound_message IS NULL OR p_outbound_buffer->>'status'<>'awaiting_proof' THEN
      RAISE EXCEPTION 'v3 outbound must be created awaiting_proof' USING ERRCODE='23514';
    END IF;
    IF NOT coalesce((p_turn->'proof_result'->>'valid')::boolean,false) THEN
      RAISE EXCEPTION 'v3 outbound requires a valid proof result' USING ERRCODE='23514';
    END IF;
    v_envelope:=public.enqueue_whatsapp_envelope(p_outbound_buffer,p_outbound_message);
    IF coalesce((v_envelope->>'deduplicated')::boolean,false) THEN
      RAISE EXCEPTION 'v3 atomic commit refuses a preexisting outbound envelope' USING ERRCODE='23514';
    END IF;
    v_outbound_id:=(v_envelope->>'buffer_id')::uuid;
  END IF;

  v_graph:=public.commit_graph_turn_v3(
    p_turn->>'canonical_inbound_id',(p_turn->>'persona_id')::uuid,(p_turn->>'lead_ref')::bigint,
    (p_turn->>'publication_id')::uuid,p_turn->>'graph_checksum',nullif(p_turn->>'active_branch_node_id',''),
    ARRAY(SELECT jsonb_array_elements_text(coalesce(p_turn->'asked_question_node_ids','[]'::jsonb))),
    coalesce((p_turn->>'expected_revision')::bigint,0),coalesce(p_turn->'facts','[]'::jsonb),
    coalesce(p_turn->'retrieval_trace','{}'::jsonb),coalesce(p_turn->'model_proposal','{}'::jsonb),
    coalesce(p_turn->'proof_result','{}'::jsonb),coalesce(p_turn->'repair_result','{}'::jsonb),
    coalesce(p_turn->'final_decision','{}'::jsonb),v_outbound_id::text);

  FOR v_branch IN SELECT jsonb_array_elements_text(coalesce(p_turn->'active_branch_node_ids','[]'::jsonb)) LOOP
    INSERT INTO public.conversation_ledger_branches(ledger_id,branch_anchor_node_id,state)
    VALUES ((v_graph->>'ledger_id')::uuid,v_branch,'active')
    ON CONFLICT (ledger_id,branch_anchor_node_id) DO UPDATE SET state='active',completed_at=NULL;
  END LOOP;
  v_final_result:=coalesce(p_result,'{}'::jsonb)||jsonb_build_object('graph_turn',v_graph,'outbound_buffer_id',v_outbound_id);
  IF v_outbound_id IS NOT NULL AND coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN
    UPDATE public.lead_buffer SET status='sent',updated_at=now() WHERE id=v_outbound_id;
    UPDATE public.messages SET status='sent' WHERE channel_binding_id=(p_turn->>'binding_id')::uuid
      AND correlation_id=p_outbound_message->>'correlation_id';
    PERFORM public.complete_conversation_commit(v_inbound.id,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_final_result);
  ELSIF v_outbound_id IS NOT NULL THEN
    PERFORM public.finalize_proven_conversation_turn(v_inbound.id,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_outbound_id,v_final_result);
  ELSE
    PERFORM public.complete_conversation_commit(v_inbound.id,(p_turn->>'binding_id')::uuid,
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
  RETURN jsonb_build_object('state','completed','graph_turn',v_graph,'outbound_buffer_id',v_outbound_id,
    'outbound_status',CASE WHEN v_outbound_id IS NULL THEN NULL
      WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN 'sent'
      ELSE 'pending_send' END);
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_whatsapp_buffer(text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v3(jsonb,jsonb,jsonb,jsonb) TO service_role;
