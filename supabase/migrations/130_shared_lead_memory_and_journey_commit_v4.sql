-- Shared lead memory and semantic journey opening.  This migration is
-- additive and projects only existing storage; it creates no table.
-- Production application requires its own explicit authorization.

CREATE OR REPLACE FUNCTION public.graph_turn_context_batch_v4(
  p_persona_id uuid,p_lead_ref bigint,p_message_limit integer DEFAULT 8
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH base AS (
    SELECT public.graph_turn_context_batch_v3(
      p_persona_id,p_lead_ref,greatest(1,least(coalesce(p_message_limit,8),20))
    ) AS value
  ), memory_facts AS (
    SELECT coalesce(jsonb_agg(
      to_jsonb(f)||jsonb_build_object('journey_id',l.journey_id)
      ORDER BY f.created_at,f.revision
    ),'[]'::jsonb) value
      FROM public.conversation_facts f
      JOIN public.conversation_ledgers l ON l.id=f.ledger_id
     WHERE l.persona_id=p_persona_id AND l.lead_ref=p_lead_ref
  ), journeys AS (
    SELECT coalesce(jsonb_agg(to_jsonb(j) ORDER BY j.sequence),'[]'::jsonb) value
      FROM public.conversation_journeys j
     WHERE j.persona_id=p_persona_id AND j.lead_ref=p_lead_ref
  ), outcomes AS (
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.occurred_at),'[]'::jsonb) value
      FROM public.sales_conversions s
     WHERE s.persona_id=p_persona_id AND s.lead_ref=p_lead_ref
  ), activity AS (
    SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.created_at),'[]'::jsonb) value
      FROM (
        SELECT p.canonical_inbound_id,p.created_at,p.final_decision,p.proof_result,p.journey_id
          FROM public.conversation_turn_proofs p
          LEFT JOIN public.conversation_ledgers l ON l.id=p.ledger_id
         WHERE (l.persona_id=p_persona_id AND l.lead_ref=p_lead_ref)
            OR p.canonical_inbound_id IN (
              SELECT id::text FROM public.lead_buffer
               WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref
            )
         ORDER BY p.created_at DESC LIMIT 100
      ) p
  )
  SELECT (SELECT value FROM base)
    ||jsonb_build_object(
      'memory_facts',(SELECT value FROM memory_facts),
      'journeys',(SELECT value FROM journeys),
      'journey_outcomes',(SELECT value FROM outcomes),
      'agent_activity',(SELECT value FROM activity),
      'contract_version','graph_turn_context_batch_v4'
    );
$$;

CREATE OR REPLACE FUNCTION public.commit_graph_turn_and_outbox_v4(
  p_turn jsonb,p_outbound_buffer jsonb DEFAULT NULL,
  p_outbound_message jsonb DEFAULT NULL,p_result jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_action text:=coalesce(nullif(p_turn->>'journey_action',''),'continue');
  v_current public.conversation_journeys%ROWTYPE;
  v_inbound public.lead_buffer%ROWTYPE;
  v_envelope jsonb;
  v_outbound_id uuid;
  v_result jsonb;
  v_proof_id uuid;
  v_burst_version timestamptz;
  v_newer_count integer;
  v_member_ids uuid[];
BEGIN
  IF v_action NOT IN ('continue','open','none') THEN
    RAISE EXCEPTION 'invalid journey action' USING ERRCODE='23514';
  END IF;
  IF nullif(p_turn->>'canonical_inbound_id','') IS NULL
     OR nullif(p_turn->>'binding_id','') IS NULL
     OR nullif(p_turn->>'correlation_id','') IS NULL THEN
    RAISE EXCEPTION 'turn identity is incomplete' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(
    (p_turn->>'persona_id')||':'||(p_turn->>'lead_ref'),0
  ));
  SELECT * INTO v_current FROM public.conversation_journeys
   WHERE persona_id=(p_turn->>'persona_id')::uuid
     AND lead_ref=(p_turn->>'lead_ref')::bigint AND is_current FOR UPDATE;

  IF v_action='open' THEN
    IF FOUND AND v_current.state IN ('collecting','awaiting_confirmation') THEN
      RAISE EXCEPTION 'cannot open a second active journey' USING ERRCODE='23514';
    END IF;
    IF FOUND THEN
      UPDATE public.conversation_journeys SET
        is_current=false,state='closed',closed_at=coalesce(closed_at,now()),
        metadata=metadata||jsonb_build_object(
          'closed_by','semantic_new_demand_v4','previous_terminal_state',v_current.state
        ),updated_at=now()
       WHERE id=v_current.id;
    END IF;
    PERFORM public.ensure_current_conversation_journey_v1(
      (p_turn->>'persona_id')::uuid,(p_turn->>'lead_ref')::bigint,
      (p_turn->>'publication_id')::uuid,p_turn->>'graph_checksum','semantic_new_demand'
    );
    RETURN public.commit_graph_turn_and_outbox_v3(
      p_turn,p_outbound_buffer,p_outbound_message,p_result
    );
  ELSIF v_action='continue' THEN
    IF NOT FOUND THEN
      PERFORM public.ensure_current_conversation_journey_v1(
        (p_turn->>'persona_id')::uuid,(p_turn->>'lead_ref')::bigint,
        (p_turn->>'publication_id')::uuid,p_turn->>'graph_checksum','initial_demand'
      );
    END IF;
    RETURN public.commit_graph_turn_and_outbox_v3(
      p_turn,p_outbound_buffer,p_outbound_message,p_result
    );
  END IF;

  -- journey_action=none persists proof/outbound exactly once without creating
  -- or mutating a journey, ledger, fact or branch.
  SELECT * INTO v_inbound FROM public.lead_buffer
   WHERE id=(p_turn->>'canonical_inbound_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'canonical inbound not found' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(coalesce(v_inbound.batch_key,v_inbound.id::text)));
  v_burst_version:=nullif(v_inbound.payload->>'burst_version','')::timestamptz;
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
        ||jsonb_build_object('burst_superseded_at',now()),updated_at=now()
     WHERE id=v_inbound.id;
    RETURN jsonb_build_object(
      'state','burst_superseded','burst_superseded',true,
      'canonical_inbound_id',v_inbound.id,'newer_member_count',v_newer_count
    );
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.conversation_turn_proofs
     WHERE canonical_inbound_id=p_turn->>'canonical_inbound_id'
  ) THEN
    RAISE EXCEPTION 'conversation turn proof already exists' USING ERRCODE='23505';
  END IF;
  IF p_outbound_buffer IS NOT NULL THEN
    IF p_outbound_message IS NULL OR p_outbound_buffer->>'status'<>'awaiting_proof'
       OR NOT coalesce((p_turn->'proof_result'->>'valid')::boolean,false) THEN
      RAISE EXCEPTION 'v4 outbound requires a valid proof' USING ERRCODE='23514';
    END IF;
    v_envelope:=public.enqueue_whatsapp_envelope(p_outbound_buffer,p_outbound_message);
    IF coalesce((v_envelope->>'deduplicated')::boolean,false) THEN
      RAISE EXCEPTION 'v4 atomic commit refuses preexisting outbound' USING ERRCODE='23514';
    END IF;
    v_outbound_id:=(v_envelope->>'buffer_id')::uuid;
  END IF;
  INSERT INTO public.conversation_turn_proofs(
    canonical_inbound_id,ledger_id,journey_id,publication_id,retrieval_trace,
    model_proposal,proof_result,repair_result,final_decision,outbound_id
  ) VALUES (
    p_turn->>'canonical_inbound_id',NULL,NULL,(p_turn->>'publication_id')::uuid,
    coalesce(p_turn->'retrieval_trace','{}'::jsonb),
    coalesce(p_turn->'model_proposal','{}'::jsonb),
    coalesce(p_turn->'proof_result','{}'::jsonb),
    coalesce(p_turn->'repair_result','{}'::jsonb),
    coalesce(p_turn->'final_decision','{}'::jsonb),v_outbound_id::text
  ) RETURNING id INTO v_proof_id;
  v_result:=coalesce(p_result,'{}'::jsonb)||jsonb_build_object(
    'proof_id',v_proof_id,'journey_action','none','outbound_buffer_id',v_outbound_id
  );
  IF v_outbound_id IS NOT NULL
     AND coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN
    UPDATE public.lead_buffer SET status='sent',updated_at=now() WHERE id=v_outbound_id;
    UPDATE public.messages SET status='sent'
     WHERE channel_binding_id=(p_turn->>'binding_id')::uuid
       AND correlation_id=p_outbound_message->>'correlation_id';
    PERFORM public.complete_conversation_commit(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_result
    );
  ELSIF v_outbound_id IS NOT NULL THEN
    PERFORM public.finalize_proven_conversation_turn(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_outbound_id,v_result
    );
  ELSE
    PERFORM public.complete_conversation_commit(
      (p_turn->>'canonical_inbound_id')::uuid,(p_turn->>'binding_id')::uuid,
      (p_turn->>'lead_ref')::bigint,p_turn->>'correlation_id',v_result
    );
  END IF;
  SELECT array_agg(value::uuid) INTO v_member_ids
    FROM jsonb_array_elements_text(coalesce(v_inbound.payload->'burst_member_ids','[]'::jsonb));
  IF v_member_ids IS NOT NULL THEN
    UPDATE public.lead_buffer SET status='ignored',locked_at=NULL,locked_by=NULL,
      payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
        'coalesced',true,'coalesced_into',v_inbound.id,'coalesced_at',now()
      ),updated_at=now()
     WHERE id=ANY(v_member_ids) AND id<>v_inbound.id AND direction='inbound'
       AND status IN ('buffered','retry');
  END IF;
  RETURN jsonb_build_object(
    'state','completed','journey_action','none','proof_id',v_proof_id,
    'outbound_buffer_id',v_outbound_id,
    'outbound_status',CASE WHEN v_outbound_id IS NULL THEN NULL
      WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false)
        THEN 'sent' ELSE 'pending_send' END
  );
END;
$$;

REVOKE ALL ON FUNCTION public.graph_turn_context_batch_v4(uuid,bigint,integer)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.commit_graph_turn_and_outbox_v4(jsonb,jsonb,jsonb,jsonb)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.graph_turn_context_batch_v4(uuid,bigint,integer)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v4(jsonb,jsonb,jsonb,jsonb)
  TO service_role;
