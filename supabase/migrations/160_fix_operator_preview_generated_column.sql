-- leads.ai_paused is GENERATED ALWAYS AS (handoff_level = 'full') since
-- migration 103. Migration 152 already fixed claim_queue_preview_v1 for
-- exactly this reason ("Clear the source column instead"), but migration 157
-- introduced the operator-replay pair writing the generated column again:
--
--   UPDATE public.leads SET ai_paused=false, handoff_level='none', ...
--
-- Postgres rejects that with 428C9 ("column can only be updated to DEFAULT"),
-- so claim_queue_operator_preview_v1 has raised on its second-to-last
-- statement since the day it shipped -- the whole transaction rolls back, and
-- "Gerar prévia" has never once succeeded in production. Migrations 158 and
-- 159 then built stale-commit and stale-worker-claim recovery on top of a
-- function that could never reach its own end. Verified 2026-09-21 by calling
-- the function inside a rolled-back transaction against a real stuck inbound.
--
-- The release path has the same defect, so a failed preview could not restore
-- the lead's prior pause state either.
--
-- Writing handoff_level alone is sufficient and correct: ai_paused derives
-- from it. This migration changes no other behaviour of either function.

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
    PERFORM public.release_conversation_commit_for_retry_v1(v_row.id::text,'stale_worker_claim_released');
    UPDATE public.lead_buffer SET
      payload=coalesce(payload,'{}'::jsonb)-'provider_attempt_started_at'-'provider_attempt_worker',
      updated_at=now()
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
      PERFORM public.release_conversation_commit_for_retry_v1(v_row.id::text,'stale_operator_preview_commit');
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
  -- handoff_level only: ai_paused is generated from it (migration 152 pattern).
  UPDATE public.leads SET handoff_level='none',
    metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('pending_reconfirmation',true),updated_at=now()
   WHERE id=v_row.lead_ref;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.operator_preview_claimed','lead_buffer',v_row.id::text,v_row.persona_id,
    jsonb_build_object('actor_user_id',p_actor_user_id,'operator_override',true),'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,'persona_id',v_row.persona_id,
    'channel_binding_id',v_row.channel_binding_id,'correlation_id',v_row.correlation_id,'text',v_row.payload->>'text');
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
      -- Restoring handoff_level restores ai_paused with it; writing the
      -- generated column directly is what made this rollback path fail too.
      UPDATE public.leads SET
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

-- The ordinary technical-recovery claim never cleared an orphaned commit, so
-- every reprocess of an inbound whose decision died mid-flight reached the
-- runtime and came back as "conversation commit is already processing" (409),
-- forever. Release a stale one here too, under the same invariants the shared
-- primitive already enforces: it refuses outright when a proof exists.
CREATE OR REPLACE FUNCTION public.claim_queue_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
  v_claimed_at timestamptz;
BEGIN
  SELECT * INTO v_row FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'queue item not found' USING ERRCODE='23514'; END IF;
  IF v_row.direction <> 'inbound' OR v_row.status <> 'waiting_human' THEN
    RAISE EXCEPTION 'queue item is not a recoverable technical inbound' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM public.conversation_turn_proofs WHERE canonical_inbound_id=v_row.id::text)
     OR EXISTS (
       SELECT 1 FROM public.lead_buffer o
       WHERE o.direction='outbound' AND o.lead_ref=v_row.lead_ref
         AND o.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id
         AND o.correlation_id=('ai:' || coalesce(v_row.correlation_id,''))
     ) THEN
    RAISE EXCEPTION 'canonical inbound already has a decision or outbound' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.system_events e
    WHERE e.entity_type='lead_buffer' AND e.entity_id=v_row.id::text
      AND e.event_type IN ('conversation.technical_failure','conversation.technical_handoff')
  ) THEN
    RAISE EXCEPTION 'queue item is a human handoff, not a technical recovery' USING ERRCODE='23514';
  END IF;
  IF coalesce(v_row.payload->'conversation_commit'->>'status','')='completed' THEN
    RAISE EXCEPTION 'canonical inbound already has a conversation commit' USING ERRCODE='23514';
  END IF;
  IF coalesce(v_row.payload->'conversation_commit'->>'status','')='processing' THEN
    v_claimed_at := NULLIF(v_row.payload->'conversation_commit'->>'claimed_at','')::timestamptz;
    IF v_claimed_at IS NULL OR v_claimed_at > now() - interval '5 minutes' THEN
      RAISE EXCEPTION 'canonical inbound conversation commit is still processing' USING ERRCODE='23514';
    END IF;
    PERFORM public.release_conversation_commit_for_retry_v1(v_row.id::text,'stale_queue_preview_commit');
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.stale_commit_released','lead_buffer',v_row.id::text,v_row.persona_id,
      jsonb_build_object('actor_user_id',p_actor_user_id,'claimed_at',v_claimed_at,'threshold_seconds',300),
      'warn','messaging.queue');
  END IF;
  UPDATE public.lead_buffer
  SET status='processing', locked_at=now(), locked_by='operator-preview',
      payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_preview_claim',true),
      updated_at=now()
  WHERE id=v_row.id;
  UPDATE public.leads SET handoff_level='none', updated_at=now()
  WHERE id=v_row.lead_ref AND handoff_level='full';
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.preview_claimed','lead_buffer',v_row.id::text,v_row.persona_id,
    jsonb_build_object('actor_user_id',p_actor_user_id),'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,
    'persona_id',v_row.persona_id,'channel_binding_id',v_row.channel_binding_id,
    'correlation_id',v_row.correlation_id,'text',coalesce(v_row.payload->>'text',''));
END; $$;

REVOKE ALL ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_operator_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
REVOKE ALL ON FUNCTION public.release_queue_operator_preview_claim_v1(uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.release_queue_operator_preview_claim_v1(uuid,text,uuid) TO service_role,brain_control_plane;
REVOKE ALL ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
NOTIFY pgrst,'reload schema';
