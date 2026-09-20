-- Reconcile the operator queue with the real production conversation state.
-- Validator traffic stays persisted for internal QA, but never belongs in the
-- real dispatch queue. Dead letters are visible with an explicit reason; only
-- an unproved technical turn without a matching outbound can be regenerated.

CREATE OR REPLACE FUNCTION public.claim_queue_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.lead_buffer%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'queue item not found' USING ERRCODE='23514'; END IF;
  IF v_row.direction <> 'inbound' OR v_row.status NOT IN ('waiting_human','dead_letter') THEN
    RAISE EXCEPTION 'queue item is not a recoverable technical inbound' USING ERRCODE='23514';
  END IF;
  IF coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
    RAISE EXCEPTION 'lead is paused in the operational queue' USING ERRCODE='23514';
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
    jsonb_build_object('actor_user_id',p_actor_user_id,'previous_status',v_row.status),'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,
    'persona_id',v_row.persona_id,'channel_binding_id',v_row.channel_binding_id,
    'correlation_id',v_row.correlation_id,'text',coalesce(v_row.payload->>'text',''));
END; $$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v149(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH scoped AS (
    SELECT b.*, l.nome AS lead_name, p.name AS persona_name, p.slug AS persona_slug,
      parent.created_at AS parent_created_at,
      latest_customer.content AS latest_message,
      last_agent.content AS last_agent_message,
      latest_inbound.content AS latest_inbound_context,
      recent_context.messages AS recent_context,
      first_preview.content AS first_preview_text, proof.id AS proof_id, proof.publication_id
    FROM public.lead_buffer b
    LEFT JOIN public.leads l ON l.id=b.lead_ref
    LEFT JOIN public.personas p ON p.id=b.persona_id
    LEFT JOIN public.lead_buffer parent ON parent.id=b.queue_parent_buffer_id
    LEFT JOIN LATERAL (
      SELECT m.content FROM public.messages m
       WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref)
         AND m.created_at <= coalesce(parent.created_at,b.created_at)
         AND (m.direction='inbound' OR m.role IN ('user','customer'))
       ORDER BY m.created_at DESC,m.id DESC LIMIT 1
    ) latest_customer ON true
    LEFT JOIN LATERAL (
      SELECT m.content FROM public.messages m
       WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref)
         AND m.created_at <= coalesce(parent.created_at,b.created_at)
         AND (m.direction='outbound' OR m.role IN ('assistant','agent','ai'))
         AND coalesce(m.metadata->>'sender_type','agent') NOT IN ('human','operator','client','customer')
         AND NOT (b.status='preview_ready' AND m.correlation_id IS NOT NULL AND m.correlation_id=b.correlation_id)
       ORDER BY m.created_at DESC,m.id DESC LIMIT 1
    ) last_agent ON true
    LEFT JOIN LATERAL (
      SELECT m.content FROM public.messages m
       WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref)
         AND m.created_at <= coalesce(parent.created_at,b.created_at)
         AND (m.direction='inbound' OR m.role IN ('user','customer'))
       ORDER BY m.created_at DESC,m.id DESC LIMIT 1
    ) latest_inbound ON true
    LEFT JOIN LATERAL (
      SELECT coalesce(jsonb_agg(jsonb_build_object(
        'id',recent.id,'content',left(coalesce(recent.content,''),2000),
        'direction',recent.direction,'role',recent.role,
        'sender_type',coalesce(recent.metadata->>'sender_type',case when recent.direction='outbound' then 'agent' else 'client' end),
        'created_at',recent.created_at
      ) ORDER BY recent.created_at DESC,recent.id DESC),'[]'::jsonb) AS messages
      FROM (
        SELECT m.id,m.content,m.direction,m.role,m.metadata,m.created_at
        FROM public.messages m
        WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref)
          AND m.created_at <= coalesce(parent.created_at,b.created_at)
          AND (m.direction IN ('inbound','outbound') OR m.role IN ('user','customer','assistant','agent','ai','human'))
          AND NOT (b.status='preview_ready' AND m.correlation_id IS NOT NULL AND m.correlation_id=b.correlation_id)
        ORDER BY m.created_at DESC,m.id DESC LIMIT 3
      ) recent
    ) recent_context ON true
    LEFT JOIN LATERAL (
      SELECT first_line.payload->>'text' AS content
      FROM public.lead_buffer first_line
      WHERE b.queue_sequence=2
        AND first_line.queue_group_id=b.queue_group_id
        AND first_line.queue_revision=b.queue_revision
        AND first_line.queue_sequence=1
        AND first_line.status <> 'superseded'
      ORDER BY first_line.created_at DESC LIMIT 1
    ) first_preview ON true
    LEFT JOIN public.conversation_turn_proofs proof
      ON proof.canonical_inbound_id='proactive:' || b.id::text
    WHERE (p_persona_ids IS NULL OR b.persona_id=ANY(p_persona_ids))
      AND coalesce(b.correlation_id,'') NOT ILIKE '%validator%'
      AND coalesce(b.external_message_id,'') NOT LIKE 'validator:%'
      AND coalesce(b.external_message_id,'') NOT LIKE 'ai_reply.validator:%'
      AND coalesce(b.payload->>'source','') <> 'wa_validator'
      AND coalesce(b.payload->>'sender','') <> 'wa-validator'
      AND coalesce(b.payload->>'validation_transport','') <> 'true'
      AND coalesce(b.payload->>'provider','') <> 'internal_validator'
  ), projected AS (
    SELECT s.*, CASE
      WHEN coalesce((s.payload->>'queue_pause')::boolean,false) THEN 'paused'
      WHEN s.status='superseded' THEN NULL
      WHEN s.direction='outbound' AND s.status='preview_ready' THEN 'preview_ready'
      WHEN s.direction='outbound' AND s.status IN ('buffered','pending_send','awaiting_proof','retry','failed','processing') THEN 'pending'
      WHEN s.direction='outbound' AND s.status IN ('sent','delivered','read')
        AND coalesce(s.message_origin,'conversation') <> 'proactive'
        AND NOT EXISTS (
          SELECT 1 FROM public.lead_buffer newer
          WHERE newer.direction='inbound' AND newer.lead_ref=s.lead_ref
            AND newer.channel_binding_id IS NOT DISTINCT FROM s.channel_binding_id
            AND newer.created_at>s.created_at
        ) THEN 'awaiting_customer'
      WHEN s.direction='inbound' AND s.status IN ('received','buffered','processing','retry') THEN 'pending_response'
      WHEN s.direction='inbound' AND s.status IN ('waiting_human','dead_letter')
        AND EXISTS (
          SELECT 1 FROM public.system_events e
          WHERE e.entity_type='lead_buffer' AND e.entity_id=s.id::text
            AND e.event_type IN ('conversation.technical_failure','conversation.technical_handoff')
        )
        AND NOT EXISTS (
          SELECT 1 FROM public.conversation_turn_proofs proof
          WHERE proof.canonical_inbound_id=s.id::text
        )
        AND NOT EXISTS (
          SELECT 1 FROM public.lead_buffer outbound
          WHERE outbound.direction='outbound'
            AND outbound.lead_ref=s.lead_ref
            AND outbound.channel_binding_id IS NOT DISTINCT FROM s.channel_binding_id
            AND outbound.correlation_id=('ai:' || coalesce(s.correlation_id,''))
        ) THEN 'technical_failure'
      WHEN s.direction='inbound' AND s.status IN ('waiting_human','dead_letter') THEN 'blocked'
      ELSE NULL
    END AS queue_state
    FROM scoped s
  ), ranked AS (
    SELECT projected.*,
      row_number() OVER (
        PARTITION BY persona_id, lead_ref
        ORDER BY created_at DESC, id DESC
      ) AS lead_rank
    FROM projected
    WHERE queue_state IS NOT NULL
  ), filtered AS (
    SELECT * FROM ranked
    WHERE lead_rank <= 2
      AND (p_origin IS NULL OR p_origin='' OR coalesce(message_origin,'conversation')=p_origin)
      AND (p_status IS NULL OR p_status='' OR queue_state=p_status)
  ), page AS (
    SELECT * FROM filtered
    ORDER BY CASE
      WHEN coalesce(payload->>'queue_position_epoch','') ~ '^[0-9]+(\.[0-9]+)?$'
        THEN (payload->>'queue_position_epoch')::double precision
      ELSE extract(epoch from coalesce(available_at,created_at))
    END, created_at, id
    OFFSET greatest(p_offset,0) LIMIT greatest(least(p_limit,100),1)
  )
  SELECT jsonb_build_object(
    'items',coalesce((SELECT jsonb_agg(jsonb_build_object(
      'id',id,'preview',left(coalesce(payload->>'text',payload->>'caption','[sem texto]'),240),
      'preview_text',CASE WHEN queue_state IN ('awaiting_customer','blocked','technical_failure') THEN NULL ELSE left(coalesce(payload->>'text',payload->>'caption',''),2000) END,
      'lead_ref',lead_ref,'lead',CASE WHEN lead_ref IS NULL THEN NULL ELSE jsonb_build_object('nome',lead_name) END,
      'persona_id',persona_id,'persona',jsonb_build_object('name',persona_name,'slug',persona_slug),
      'origin',coalesce(message_origin,'conversation'),'status',queue_state,'queue_state',queue_state,
      'available_at',available_at,'created_at',created_at,'last_error',last_error,
      'reactivation_group_id',queue_group_id,'queue_parent_buffer_id',queue_parent_buffer_id,
      'sequence_index',queue_sequence,'line_kind',queue_line_kind,'preview_revision',queue_revision,
      'latest_message',latest_message,'last_agent_message',last_agent_message,
      'latest_inbound_context',latest_inbound_context,'recent_context',coalesce(recent_context,'[]'::jsonb),
      'first_preview_text',first_preview_text,
      'previous_message',coalesce(CASE WHEN queue_sequence=2 THEN first_preview_text ELSE NULL END,last_agent_message),
      'proof_id',proof_id,'publication_id',publication_id,
      'actions',CASE
        WHEN queue_state='technical_failure' THEN jsonb_build_array('reprocess')
        WHEN queue_state='preview_ready' AND queue_group_id IS NOT NULL THEN jsonb_build_array('send_preview','regenerate_preview','handoff','pause')
        WHEN queue_state='preview_ready' THEN jsonb_build_array('send_preview','pause')
        WHEN queue_state='pending' THEN jsonb_build_array('pause')
        WHEN queue_state='paused' THEN jsonb_build_array('resume')
        WHEN queue_state='awaiting_customer' AND coalesce(message_origin,'conversation') <> 'proactive' THEN jsonb_build_array('reactivate')
        ELSE '[]'::jsonb END
    )) FROM page),'[]'::jsonb),
    'next_offset',CASE WHEN (SELECT count(*) FROM filtered)>greatest(p_offset,0)+greatest(least(p_limit,100),1)
      THEN greatest(p_offset,0)+greatest(least(p_limit,100),1) ELSE NULL END
  );
$$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT public.list_actionable_message_queue_v149(
    p_persona_ids, p_origin, p_status, p_offset, p_limit
  );
$$;

REVOKE ALL ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) TO service_role,brain_control_plane;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v149(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v149(uuid[],text,text,integer,integer) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
