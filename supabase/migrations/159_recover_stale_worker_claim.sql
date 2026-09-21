-- A dispatcher-level claim (lead_buffer.status='processing' set directly by
-- the worker's own claim query, migration 111) is a different lock than the
-- payload.conversation_commit sub-status migration 158 already recovers.
-- When the worker process crashes mid-decision it never reaches the code
-- that would mark the row waiting_human/dead_letter, and the worker's own
-- reclaim query (migration 111) deliberately refuses to retry a row whose
-- payload still has decision_attempt_started_at/provider_attempt_started_at
-- set -- correct protection against re-running an in-flight decision, but it
-- leaves a genuinely crashed row stuck forever with no recovery path at all,
-- because claim_queue_operator_preview_v1 only accepted
-- status IN ('waiting_human','dead_letter'). This migration extends it to
-- also accept a stale 'processing' claim, under the same safety invariants
-- already used for the payload.conversation_commit case: old lock, no proof,
-- no outbound, no newer inbound, not paused.

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
     OR v_row.status NOT IN ('waiting_human','dead_letter','processing') THEN
    RAISE EXCEPTION 'inbound is not available for operator replay' USING ERRCODE='23514';
  END IF;
  IF coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
    RAISE EXCEPTION 'inbound is paused in the operational queue' USING ERRCODE='23514';
  END IF;
  IF nullif(btrim(coalesce(v_row.payload->>'text','')),'') IS NULL THEN
    RAISE EXCEPTION 'original inbound text is unavailable' USING ERRCODE='23514';
  END IF;

  IF v_row.status='processing' THEN
    IF v_row.locked_at IS NULL OR v_row.locked_at > now() - interval '5 minutes' THEN
      RAISE EXCEPTION 'inbound worker claim is still processing' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.conversation_turn_proofs p WHERE p.canonical_inbound_id=v_row.id::text)
       OR EXISTS (SELECT 1 FROM public.lead_buffer o WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
         AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
         AND o.correlation_id=('ai:'||coalesce(v_row.correlation_id,''))) THEN
      RAISE EXCEPTION 'inbound already has a decision or outbound' USING ERRCODE='23514';
    END IF;
    -- Clear every marker that would make the dispatcher's own reclaim query
    -- (or claim_conversation_commit) believe a decision is still in flight,
    -- so a subsequent normal attempt -- from this claim or a future one --
    -- does not immediately re-trip the same guard.
    UPDATE public.lead_buffer SET
      payload=(coalesce(payload,'{}'::jsonb)
        -'conversation_commit'-'decision_attempt_started_at'-'decision_attempt_worker'
        -'provider_attempt_started_at'-'provider_attempt_worker')||jsonb_build_object(
        'last_conversation_failure',jsonb_build_object('reason','stale_worker_claim_released','retryable',true)
      ), updated_at=now()
     WHERE id=v_row.id;
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.stale_worker_claim_released','lead_buffer',v_row.id::text,v_row.persona_id,
      jsonb_build_object('actor_user_id',p_actor_user_id,'locked_at',v_row.locked_at,'locked_by',v_row.locked_by,'threshold_seconds',300),
      'warn','messaging.queue');
  ELSE
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

-- The listing only offered "Gerar prévia" for queue_state='blocked' (an
-- inbound already sitting in waiting_human/dead_letter). A row stuck in a
-- stale worker claim projects as 'pending_response' -- "aguardando resposta
-- da IA" -- which is honest right up until the lock goes stale; past that it
-- actively misleads an operator into thinking the AI is still working. Both
-- the capability and the label are corrected together.
CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL,p_origin text DEFAULT NULL,p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0,p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
WITH base AS (
  SELECT public.list_actionable_message_queue_v156(p_persona_ids,p_origin,p_status,p_offset,p_limit) AS data
), elements AS (
  SELECT item, ordinal
  FROM base CROSS JOIN LATERAL jsonb_array_elements(coalesce(data->'items','[]'::jsonb)) WITH ORDINALITY AS e(item,ordinal)
), decorated AS (
  SELECT ordinal, CASE
    WHEN item->>'queue_state'='blocked'
      AND item->>'id'=item->'outbound_messages'->0->>'buffer_id'
      AND item->'outbound_messages'->0->>'text' IS NULL
      AND item->'outbound_messages'->0->>'proof_id' IS NULL
    THEN jsonb_set(item,'{outbound_messages,0}',
      (item->'outbound_messages'->0)||jsonb_build_object(
        'can_generate_preview',true,'generate_preview_reason',NULL),true)
    WHEN item->>'queue_state'='pending_response'
      AND item->>'id'=item->'outbound_messages'->0->>'buffer_id'
      AND stale.id IS NOT NULL
    THEN jsonb_set(item,'{outbound_messages,0}',
      (item->'outbound_messages'->0)||jsonb_build_object(
        'can_generate_preview',true,'generate_preview_reason',NULL,'status','blocked'),true)
      ||jsonb_build_object('status','blocked','queue_state','blocked')
    ELSE item END AS item
  FROM elements
  LEFT JOIN LATERAL (
    SELECT lb.id FROM public.lead_buffer lb
     WHERE lb.id=nullif(elements.item->>'id','')::uuid
       AND lb.status='processing' AND lb.locked_at < now() - interval '5 minutes'
  ) stale ON true
), aggregated AS (
  SELECT coalesce(jsonb_agg(item ORDER BY ordinal),'[]'::jsonb) AS items FROM decorated
)
SELECT jsonb_set(base.data,'{items}',aggregated.items,true)
FROM base CROSS JOIN aggregated;
$$;

REVOKE ALL ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst,'reload schema';
