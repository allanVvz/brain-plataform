-- Persist operator-generated technical previews as inert preview_ready rows.
-- This migration changes functions/projection only: no tables, data cleanup or
-- provider delivery is performed here.

CREATE OR REPLACE FUNCTION public.finalize_proven_conversation_turn(
  p_inbound_buffer_id uuid, p_binding_id uuid, p_lead_ref bigint,
  p_correlation_id text, p_outbound_id uuid, p_result jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_inbound public.lead_buffer%ROWTYPE;
  v_outbound public.lead_buffer%ROWTYPE;
  v_proof_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_binding_id::text || ':' || p_lead_ref::text));
  SELECT * INTO v_inbound FROM public.lead_buffer WHERE id = p_inbound_buffer_id FOR UPDATE;
  SELECT * INTO v_outbound FROM public.lead_buffer WHERE id = p_outbound_id FOR UPDATE;
  IF v_inbound.id IS NULL OR v_inbound.direction <> 'inbound'
     OR v_inbound.channel_binding_id <> p_binding_id OR v_inbound.lead_ref <> p_lead_ref THEN
    RAISE EXCEPTION 'canonical inbound identity mismatch' USING ERRCODE = '23514';
  END IF;
  IF v_outbound.id IS NULL OR v_outbound.direction <> 'outbound'
     OR v_outbound.channel_binding_id <> p_binding_id OR v_outbound.lead_ref <> p_lead_ref THEN
    RAISE EXCEPTION 'outbound identity mismatch' USING ERRCODE = '23514';
  END IF;
  SELECT count(*) INTO v_proof_count FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id = p_inbound_buffer_id::text
     AND outbound_id = p_outbound_id::text
     AND coalesce((proof_result->>'valid')::boolean, false);
  IF v_proof_count <> 1 THEN
    RAISE EXCEPTION 'outbound requires exactly one valid turn proof, found %', v_proof_count
      USING ERRCODE = '23514';
  END IF;

  -- preview_ready is already proof-authorized but must remain inert. Only a
  -- normal awaiting_proof turn is released to pending_send here.
  IF v_outbound.status = 'awaiting_proof' THEN
    UPDATE public.lead_buffer SET status = 'pending_send', available_at = now(),
      locked_at = NULL, locked_by = NULL, updated_at = now()
     WHERE id = p_outbound_id;
  ELSIF v_outbound.status NOT IN ('preview_ready','pending_send','processing','sent','delivered','read') THEN
    RAISE EXCEPTION 'outbound cannot be released from status %', v_outbound.status
      USING ERRCODE = '23514';
  END IF;

  UPDATE public.lead_buffer SET
    payload = jsonb_set(
      coalesce(payload, '{}'::jsonb) - 'queue_preview_claim',
      '{conversation_commit}',
      jsonb_build_object('status','completed','binding_id',p_binding_id,
        'lead_ref',p_lead_ref,'correlation_id',p_correlation_id,
        'completed_at',now(),'result',coalesce(p_result,'{}'::jsonb)), true
    ),
    status = 'sent', locked_at = NULL, locked_by = NULL, updated_at = now()
   WHERE id = p_inbound_buffer_id;
  RETURN jsonb_build_object('ok', true, 'state', 'completed',
    'inbound_id', p_inbound_buffer_id, 'outbound_id', p_outbound_id,
    'outbound_status', CASE WHEN v_outbound.status = 'awaiting_proof'
      THEN 'pending_send' ELSE v_outbound.status END);
END;
$$;

-- Keep the enhanced context projection as the source used by both current and
-- compatibility callers, while ordering regenerated previews by the original
-- inbound's immutable queue position.
CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT public.list_actionable_message_queue_v149(
    p_persona_ids, p_origin, p_status, p_offset, p_limit
  );
$$;

-- Replace only the paging order of the v149 projection. The full projection
-- remains here so the database does not depend on changing an old migration.
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
      WHERE b.queue_sequence=2 AND first_line.queue_group_id=b.queue_group_id
        AND first_line.queue_revision=b.queue_revision AND first_line.queue_sequence=1
        AND first_line.status <> 'superseded'
      ORDER BY first_line.created_at DESC LIMIT 1
    ) first_preview ON true
    LEFT JOIN public.conversation_turn_proofs proof
      ON proof.canonical_inbound_id='proactive:' || b.id::text
    WHERE (p_persona_ids IS NULL OR b.persona_id=ANY(p_persona_ids))
      AND coalesce(b.correlation_id,'') NOT LIKE 'validator:%'
      AND coalesce(b.correlation_id,'') NOT LIKE 'inbound:wa-validator:%'
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
      WHEN s.direction='inbound' AND s.status='waiting_human'
        AND EXISTS (
          SELECT 1 FROM public.system_events e
          WHERE e.entity_type='lead_buffer' AND e.entity_id=s.id::text
            AND e.event_type IN ('conversation.technical_failure','conversation.technical_handoff')
        ) THEN 'technical_failure'
      ELSE NULL
    END AS queue_state
    FROM scoped s
  ), filtered AS (
    SELECT * FROM projected
    WHERE queue_state IS NOT NULL
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
      'preview_text',CASE WHEN queue_state='awaiting_customer' THEN NULL ELSE left(coalesce(payload->>'text',payload->>'caption',''),2000) END,
      'lead_ref',lead_ref,'lead',CASE WHEN lead_ref IS NULL THEN NULL ELSE jsonb_build_object('nome',lead_name) END,
      'persona_id',persona_id,'persona',jsonb_build_object('name',persona_name,'slug',persona_slug),
      'origin',coalesce(message_origin,'conversation'),'status',queue_state,'queue_state',queue_state,
      'available_at',available_at,'created_at',created_at,'last_error',last_error,
      'reactivation_group_id',queue_group_id,'queue_parent_buffer_id',queue_parent_buffer_id,
      'sequence_index',queue_sequence,'line_kind',queue_line_kind,'preview_revision',queue_revision,
      'latest_message',latest_message,'last_agent_message',last_agent_message,
      'latest_inbound_context',latest_inbound_context,'recent_context',coalesce(recent_context,'[]'::jsonb),
      'first_preview_text',first_preview_text,
      'previous_message',coalesce(CASE WHEN queue_sequence=2 THEN first_preview_text ELSE NULL END,last_agent_message,latest_message,latest_inbound_context),
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

REVOKE ALL ON FUNCTION public.finalize_proven_conversation_turn(uuid,uuid,bigint,text,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_proven_conversation_turn(uuid,uuid,bigint,text,uuid,jsonb) TO service_role,brain_runtime;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v149(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v149(uuid[],text,text,integer,integer) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
