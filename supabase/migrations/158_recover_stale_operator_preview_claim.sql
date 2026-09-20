-- Recover a timed-out conversation commit when an operator explicitly asks
-- for a preview. This is deliberately narrow: only an old processing claim
-- without a proof or outbound can be released, and the newest inbound rule
-- remains enforced below.

CREATE OR REPLACE FUNCTION public.claim_queue_operator_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
  v_lead public.leads%ROWTYPE;
  v_commit jsonb;
  v_claimed_at timestamptz;
BEGIN
  SELECT * INTO v_row FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND OR v_row.direction<>'inbound'
     OR v_row.status NOT IN ('waiting_human','dead_letter') THEN
    RAISE EXCEPTION 'inbound is not available for operator replay' USING ERRCODE='23514';
  END IF;
  IF coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
    RAISE EXCEPTION 'inbound is paused in the operational queue' USING ERRCODE='23514';
  END IF;
  IF nullif(btrim(coalesce(v_row.payload->>'text','')),'') IS NULL THEN
    RAISE EXCEPTION 'original inbound text is unavailable' USING ERRCODE='23514';
  END IF;

  v_commit := v_row.payload->'conversation_commit';
  IF coalesce(v_commit->>'status','')='completed' THEN
    RAISE EXCEPTION 'inbound already has a conversation commit' USING ERRCODE='23514';
  END IF;
  IF coalesce(v_commit->>'status','')='processing' THEN
    v_claimed_at := NULLIF(v_commit->>'claimed_at','')::timestamptz;
    IF v_claimed_at IS NULL OR v_claimed_at > now() - interval '5 minutes' THEN
      RAISE EXCEPTION 'inbound conversation commit is still processing' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.conversation_turn_proofs p WHERE p.canonical_inbound_id=v_row.id::text)
       OR EXISTS (SELECT 1 FROM public.lead_buffer o WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
         AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
         AND o.correlation_id=('ai:'||coalesce(v_row.correlation_id,''))) THEN
      RAISE EXCEPTION 'inbound already has a decision or outbound' USING ERRCODE='23514';
    END IF;
    UPDATE public.lead_buffer SET
      payload=(coalesce(payload,'{}'::jsonb)-'conversation_commit')||jsonb_build_object(
        'last_conversation_failure',jsonb_build_object('reason','stale_operator_preview_commit','retryable',true)
      ), updated_at=now()
     WHERE id=v_row.id;
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.stale_commit_released','lead_buffer',v_row.id::text,v_row.persona_id,
      jsonb_build_object('actor_user_id',p_actor_user_id,'claimed_at',v_claimed_at,'threshold_seconds',300),
      'warn','messaging.queue');
  END IF;

  PERFORM pg_advisory_xact_lock(hashtext('operator-preview:'||v_row.lead_ref::text||':'||coalesce(v_row.channel_binding_id::text,'')));
  SELECT * INTO v_lead FROM public.leads WHERE id=v_row.lead_ref FOR UPDATE;
  IF NOT FOUND OR v_lead.persona_id IS DISTINCT FROM v_row.persona_id THEN
    RAISE EXCEPTION 'inbound lead scope changed' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM public.conversation_turn_proofs p WHERE p.canonical_inbound_id=v_row.id::text)
     OR EXISTS (SELECT 1 FROM public.lead_buffer o WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
       AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
       AND o.correlation_id=('ai:'||coalesce(v_row.correlation_id,''))) THEN
    RAISE EXCEPTION 'inbound already has a decision or outbound' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM public.lead_buffer newer WHERE newer.direction='inbound' AND newer.lead_ref=v_row.lead_ref
       AND newer.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
       AND (newer.created_at,newer.id)>(v_row.created_at,v_row.id)) THEN
    RAISE EXCEPTION 'inbound is superseded by a newer customer message' USING ERRCODE='23514';
  END IF;
  UPDATE public.lead_buffer SET status='processing',locked_at=now(),locked_by='operator-preview',
    payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
      'queue_preview_claim',true,'queue_preview_claim_mode','operator_replay',
      'operator_preview_prior_ai_paused',coalesce(v_lead.ai_paused,false),
      'operator_preview_prior_handoff_level',coalesce(v_lead.handoff_level,'none'),
      'operator_preview_had_pending_reconfirmation',coalesce(v_lead.metadata,'{}'::jsonb)?'pending_reconfirmation',
      'operator_preview_prior_pending_reconfirmation',v_lead.metadata->'pending_reconfirmation'
    ),updated_at=now() WHERE id=v_row.id;
  UPDATE public.leads SET ai_paused=false,handoff_level='none',
    metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('pending_reconfirmation',true),updated_at=now()
   WHERE id=v_row.lead_ref;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.operator_preview_claimed','lead_buffer',v_row.id::text,v_row.persona_id,
    jsonb_build_object('actor_user_id',p_actor_user_id,'operator_override',true),'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,'persona_id',v_row.persona_id,
    'channel_binding_id',v_row.channel_binding_id,'correlation_id',v_row.correlation_id,'text',v_row.payload->>'text');
END; $$;

REVOKE ALL ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
