-- One semantic decision may deliver an ordered media batch. The batch is
-- committed atomically with the graph proof; only its first item is released.

CREATE OR REPLACE FUNCTION public.commit_graph_turn_and_outbox_v5(
  p_turn jsonb,p_outbound_buffer jsonb DEFAULT NULL,
  p_outbound_message jsonb DEFAULT NULL,p_result jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_result jsonb;
  v_buffers jsonb:=p_outbound_buffer;
  v_messages jsonb:=p_outbound_message;
  v_count integer;
  v_index integer;
  v_buffer jsonb;
  v_message jsonb;
  v_envelope jsonb;
  v_ids jsonb:='[]'::jsonb;
  v_validation boolean:=false;
  v_batch_id text;
BEGIN
  IF p_outbound_buffer IS NULL OR jsonb_typeof(p_outbound_buffer)<>'array' THEN
    RETURN public.commit_graph_turn_and_outbox_v4(
      p_turn,p_outbound_buffer,p_outbound_message,p_result
    );
  END IF;
  IF jsonb_typeof(p_outbound_message)<>'array' THEN
    RAISE EXCEPTION 'media batch messages must be an array' USING ERRCODE='23514';
  END IF;
  v_count:=jsonb_array_length(v_buffers);
  IF v_count<1 OR v_count>20 OR jsonb_array_length(v_messages)<>v_count THEN
    RAISE EXCEPTION 'media batch size is invalid' USING ERRCODE='23514';
  END IF;
  v_batch_id:=(v_buffers->0)->'payload'->'media_batch'->>'batch_id';
  FOR v_index IN 0..v_count-1 LOOP
    v_buffer:=v_buffers->v_index;
    v_message:=v_messages->v_index;
    IF v_buffer->>'status'<>'awaiting_proof'
       OR nullif(v_buffer->'payload'->'media'->>'path','') IS NULL
       OR nullif(v_buffer->'payload'->'media_batch'->>'batch_id','') IS NULL
       OR v_buffer->'payload'->'media_batch'->>'batch_id'<>v_batch_id
       OR (v_buffer->'payload'->'media_batch'->>'index')::integer<>v_index+1
       OR (v_buffer->'payload'->'media_batch'->>'total')::integer<>v_count THEN
      RAISE EXCEPTION 'media batch envelope is invalid' USING ERRCODE='23514';
    END IF;
  END LOOP;

  v_result:=public.commit_graph_turn_and_outbox_v4(
    p_turn,v_buffers->0,v_messages->0,
    coalesce(p_result,'{}'::jsonb)||jsonb_build_object('media_batch_size',v_count)
  );
  IF v_result->>'state'='burst_superseded' THEN RETURN v_result; END IF;
  IF nullif(v_result->>'outbound_buffer_id','') IS NULL THEN
    RAISE EXCEPTION 'v5 first batch item was not committed' USING ERRCODE='23514';
  END IF;
  v_ids:=jsonb_build_array(v_result->'outbound_buffer_id');
  v_validation:=coalesce(((v_buffers->0)->'payload'->>'validation')::boolean,false);
  FOR v_index IN 1..v_count-1 LOOP
    v_buffer:=v_buffers->v_index;
    v_message:=v_messages->v_index;
    v_envelope:=public.enqueue_whatsapp_envelope(v_buffer,v_message);
    IF coalesce((v_envelope->>'deduplicated')::boolean,false) THEN
      RAISE EXCEPTION 'v5 atomic commit refuses preexisting batch item'
        USING ERRCODE='23514';
    END IF;
    v_ids:=v_ids||jsonb_build_array(v_envelope->'buffer_id');
    IF v_validation THEN
      UPDATE public.lead_buffer SET status='sent',updated_at=now()
       WHERE id=(v_envelope->>'buffer_id')::uuid;
      UPDATE public.messages SET status='sent'
       WHERE channel_binding_id=(p_turn->>'binding_id')::uuid
         AND correlation_id=v_message->>'correlation_id';
    END IF;
  END LOOP;
  v_result:=v_result||jsonb_build_object(
    'media_batch_size',v_count,'media_batch_buffer_ids',v_ids
  );
  UPDATE public.lead_buffer SET
    payload=jsonb_set(
      payload,'{conversation_commit,result}',v_result,true
    ),updated_at=now()
   WHERE id=(p_turn->>'canonical_inbound_id')::uuid;
  RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.release_next_graph_media_batch_item(
  p_completed_buffer_id uuid
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_current public.lead_buffer%ROWTYPE;
  v_next_id uuid;
  v_batch_id text;
  v_index integer;
BEGIN
  SELECT * INTO v_current FROM public.lead_buffer
   WHERE id=p_completed_buffer_id FOR UPDATE;
  IF NOT FOUND OR v_current.status<>'sent' THEN RETURN NULL; END IF;
  v_batch_id:=nullif(v_current.payload->'media_batch'->>'batch_id','');
  v_index:=nullif(v_current.payload->'media_batch'->>'index','')::integer;
  IF v_batch_id IS NULL OR v_index IS NULL THEN RETURN NULL; END IF;
  SELECT id INTO v_next_id FROM public.lead_buffer
   WHERE direction='outbound' AND status='awaiting_proof'
     AND persona_id=v_current.persona_id
     AND lead_ref=v_current.lead_ref
     AND channel_binding_id=v_current.channel_binding_id
     AND payload->'media_batch'->>'batch_id'=v_batch_id
     AND payload->'media_batch'->>'total'=v_current.payload->'media_batch'->>'total'
     AND (payload->'media_batch'->>'index')::integer=v_index+1
   FOR UPDATE;
  IF v_next_id IS NOT NULL THEN
    UPDATE public.lead_buffer SET status='pending_send',available_at=now(),updated_at=now()
     WHERE id=v_next_id;
  END IF;
  RETURN v_next_id;
END;
$$;

REVOKE ALL ON FUNCTION public.commit_graph_turn_and_outbox_v5(jsonb,jsonb,jsonb,jsonb)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.release_next_graph_media_batch_item(uuid)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.commit_graph_turn_and_outbox_v5(jsonb,jsonb,jsonb,jsonb)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.release_next_graph_media_batch_item(uuid)
  TO service_role;
