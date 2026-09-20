-- Allow an explicitly authorized operator to resume one human-held inbound
-- from the queue and create a proof-gated preview. This never sends outbound.
-- The selected inbound must still be unanswered and the newest for its lead.

CREATE OR REPLACE FUNCTION public.claim_queue_operator_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
  v_lead public.leads%ROWTYPE;
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
  IF coalesce(v_row.payload->'conversation_commit'->>'status','') IN ('processing','completed') THEN
    RAISE EXCEPTION 'inbound already has a conversation commit' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('operator-preview:'||v_row.lead_ref::text||':'||coalesce(v_row.channel_binding_id::text,'')));
  SELECT * INTO v_lead FROM public.leads WHERE id=v_row.lead_ref FOR UPDATE;
  IF NOT FOUND OR v_lead.persona_id IS DISTINCT FROM v_row.persona_id THEN
    RAISE EXCEPTION 'inbound lead scope changed' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.conversation_turn_proofs p
     WHERE p.canonical_inbound_id=v_row.id::text
  ) OR EXISTS (
    SELECT 1 FROM public.lead_buffer o
     WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
       AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
       AND o.correlation_id=('ai:'||coalesce(v_row.correlation_id,''))
  ) THEN
    RAISE EXCEPTION 'inbound already has a decision or outbound' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.lead_buffer newer
     WHERE newer.direction='inbound' AND newer.lead_ref=v_row.lead_ref
       AND newer.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
       AND (newer.created_at,newer.id)>(v_row.created_at,v_row.id)
  ) THEN
    RAISE EXCEPTION 'inbound is superseded by a newer customer message' USING ERRCODE='23514';
  END IF;
  UPDATE public.lead_buffer SET
    status='processing',locked_at=now(),locked_by='operator-preview',
    payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
      'queue_preview_claim',true,
      'queue_preview_claim_mode','operator_replay',
      'operator_preview_prior_ai_paused',coalesce(v_lead.ai_paused,false),
      'operator_preview_prior_handoff_level',coalesce(v_lead.handoff_level,'none'),
      'operator_preview_had_pending_reconfirmation',coalesce(v_lead.metadata,'{}'::jsonb)?'pending_reconfirmation',
      'operator_preview_prior_pending_reconfirmation',v_lead.metadata->'pending_reconfirmation'
    ),updated_at=now()
   WHERE id=v_row.id;
  UPDATE public.leads SET
    ai_paused=false,handoff_level='none',
    metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('pending_reconfirmation',true),
    updated_at=now()
   WHERE id=v_row.lead_ref;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.operator_preview_claimed','lead_buffer',v_row.id::text,v_row.persona_id,
    jsonb_build_object('actor_user_id',p_actor_user_id,'prior_ai_paused',coalesce(v_lead.ai_paused,false),
      'prior_handoff_level',coalesce(v_lead.handoff_level,'none'),'operator_override',true),
    'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,
    'persona_id',v_row.persona_id,'channel_binding_id',v_row.channel_binding_id,
    'correlation_id',v_row.correlation_id,'text',v_row.payload->>'text');
END; $$;

CREATE OR REPLACE FUNCTION public.release_queue_operator_preview_claim_v1(
  p_buffer_id uuid,p_error text,p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.lead_buffer%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'queue item not found' USING ERRCODE='23514'; END IF;
  IF v_row.status='processing' AND coalesce(v_row.payload->>'queue_preview_claim_mode','')='operator_replay' THEN
    IF NOT EXISTS (SELECT 1 FROM public.conversation_turn_proofs p WHERE p.canonical_inbound_id=v_row.id::text)
       AND NOT EXISTS (SELECT 1 FROM public.lead_buffer o WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
         AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
         AND o.correlation_id=('ai:'||coalesce(v_row.correlation_id,''))) THEN
      UPDATE public.leads SET
        ai_paused=coalesce((v_row.payload->>'operator_preview_prior_ai_paused')::boolean,false),
        handoff_level=coalesce(v_row.payload->>'operator_preview_prior_handoff_level','none'),
        metadata=CASE WHEN coalesce((v_row.payload->>'operator_preview_had_pending_reconfirmation')::boolean,false)
          THEN jsonb_set(coalesce(metadata,'{}'::jsonb),'{pending_reconfirmation}',v_row.payload->'operator_preview_prior_pending_reconfirmation',true)
          ELSE coalesce(metadata,'{}'::jsonb)-'pending_reconfirmation' END,updated_at=now()
       WHERE id=v_row.lead_ref;
      UPDATE public.lead_buffer SET status='waiting_human',locked_at=NULL,locked_by=NULL,
        last_error=left(coalesce(p_error,'operator preview generation failed'),1000),
        payload=coalesce(payload,'{}'::jsonb)-'queue_preview_claim'-'queue_preview_claim_mode'
          -'operator_preview_prior_ai_paused'-'operator_preview_prior_handoff_level'
          -'operator_preview_had_pending_reconfirmation'-'operator_preview_prior_pending_reconfirmation',updated_at=now()
       WHERE id=v_row.id;
      INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
      VALUES ('messaging.queue.operator_preview_failed','lead_buffer',v_row.id::text,v_row.persona_id,
        jsonb_build_object('actor_user_id',p_actor_user_id,'reason',left(coalesce(p_error,''),300)),
        'warn','messaging.queue');
    END IF;
  END IF;
  RETURN jsonb_build_object('buffer_id',v_row.id,'status',
    (SELECT status FROM public.lead_buffer WHERE id=v_row.id));
END; $$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL,p_origin text DEFAULT NULL,p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0,p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
WITH base AS (
  SELECT public.list_actionable_message_queue_v156(p_persona_ids,p_origin,p_status,p_offset,p_limit) AS data
), decorated AS (
  SELECT coalesce(jsonb_agg(
    CASE WHEN item->>'queue_state'='blocked'
      AND item->>'id'=item->'outbound_messages'->0->>'buffer_id'
      AND item->'outbound_messages'->0->>'text' IS NULL
      AND item->'outbound_messages'->0->>'proof_id' IS NULL
    THEN jsonb_set(item,'{outbound_messages,0}',
      (item->'outbound_messages'->0)||jsonb_build_object(
        'can_generate_preview',true,'generate_preview_reason',NULL),true)
    ELSE item END ORDER BY ordinal
  ),'[]'::jsonb) AS items
  FROM base CROSS JOIN LATERAL jsonb_array_elements(coalesce(data->'items','[]'::jsonb))
    WITH ORDINALITY AS elements(item,ordinal)
)
SELECT jsonb_set(base.data,'{items}',decorated.items,true)
FROM base CROSS JOIN decorated;
$$;

REVOKE ALL ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.release_queue_operator_preview_claim_v1(uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
GRANT EXECUTE ON FUNCTION public.release_queue_operator_preview_claim_v1(uuid,text,uuid) TO service_role,brain_control_plane;
-- Keep the isolated-role grant explicit for the migration contract validator;
-- service_role remains listed above for the internal RPC gateway.
GRANT EXECUTE ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.release_queue_operator_preview_claim_v1(uuid,text,uuid) TO brain_control_plane;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst,'reload schema';
