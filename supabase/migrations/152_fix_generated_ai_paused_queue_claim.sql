-- leads.ai_paused is generated from handoff_level since migration 103. The
-- queue preview claim still wrote the generated column directly, which made
-- reprocessing fail with SQLSTATE 428C9. Clear the source column instead.
CREATE OR REPLACE FUNCTION public.claim_queue_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.lead_buffer%ROWTYPE;
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

REVOKE ALL ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
