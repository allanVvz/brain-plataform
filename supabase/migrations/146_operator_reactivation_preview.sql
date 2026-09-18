-- An operator reactivation is a new, proof-gated proactive message.  It is
-- never a retry of the previously delivered outbound and stays inert until
-- the operator explicitly sends its preview.
CREATE OR REPLACE FUNCTION public.enqueue_reactivation_preview_with_proof_v1(
  p_source_buffer_id uuid,
  p_buffer jsonb,
  p_message jsonb,
  p_publication_id uuid,
  p_evidence_node_ids jsonb,
  p_proof_result jsonb,
  p_model_proposal jsonb DEFAULT '{}'::jsonb,
  p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_source public.lead_buffer%ROWTYPE;
  v_lead public.leads%ROWTYPE;
  v_existing public.lead_buffer%ROWTYPE;
  v_envelope jsonb;
  v_publication public.graph_publications%ROWTYPE;
BEGIN
  SELECT * INTO v_source FROM public.lead_buffer WHERE id=p_source_buffer_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reactivation source was not found' USING ERRCODE='23514';
  END IF;
  IF v_source.direction <> 'outbound' OR v_source.status NOT IN ('sent','delivered','read') THEN
    RAISE EXCEPTION 'reactivation source was not delivered' USING ERRCODE='23514';
  END IF;
  IF v_source.message_origin='proactive' THEN
    RAISE EXCEPTION 'reactivation cannot follow a proactive message' USING ERRCODE='23514';
  END IF;

  SELECT * INTO v_lead FROM public.leads WHERE id=v_source.lead_ref FOR UPDATE;
  IF NOT FOUND OR v_lead.persona_id IS DISTINCT FROM v_source.persona_id THEN
    RAISE EXCEPTION 'reactivation lead is invalid' USING ERRCODE='23514';
  END IF;
  IF coalesce(v_lead.handoff_level,'none') <> 'none' THEN
    RAISE EXCEPTION 'reactivation is blocked by human handoff' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.lead_buffer incoming
     WHERE incoming.direction='inbound'
       AND incoming.lead_ref=v_source.lead_ref
       AND incoming.channel_binding_id IS NOT DISTINCT FROM v_source.channel_binding_id
       AND incoming.created_at>v_source.created_at
  ) THEN
    RAISE EXCEPTION 'reactivation is obsolete after a newer inbound' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.contact_consents consent
     WHERE consent.lead_id=v_source.lead_ref
       AND consent.persona_id=v_source.persona_id
       AND consent.channel='whatsapp'
       AND consent.status IN ('refused','revoked')
       AND (consent.valid_until IS NULL OR consent.valid_until>now())
  ) THEN
    RAISE EXCEPTION 'reactivation is blocked by opt-out' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.campaign_recipients recipient
     WHERE recipient.lead_id=v_source.lead_ref
       AND recipient.persona_id=v_source.persona_id
       AND recipient.contact_status='provider_blocked'
  ) THEN
    RAISE EXCEPTION 'reactivation is blocked by provider status' USING ERRCODE='23514';
  END IF;
  IF v_source.campaign_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM public.campaigns campaign
     WHERE campaign.id=v_source.campaign_id AND campaign.status='cancelled'
  ) THEN
    RAISE EXCEPTION 'reactivation is blocked by cancelled campaign' USING ERRCODE='23514';
  END IF;

  SELECT * INTO v_existing FROM public.lead_buffer
   WHERE direction='outbound' AND message_origin='proactive'
     AND payload->>'reactivation_source_buffer_id'=p_source_buffer_id::text
   ORDER BY created_at DESC LIMIT 1;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'buffer_id',v_existing.id,'status',v_existing.status,
      'deduplicated',true,'source_buffer_id',p_source_buffer_id
    );
  END IF;

  IF coalesce(p_buffer->>'message_origin','') <> 'proactive'
     OR coalesce(p_buffer->>'status','') <> 'awaiting_proof'
     OR coalesce(p_buffer->>'lead_ref','') <> v_source.lead_ref::text
     OR coalesce(p_buffer->>'persona_id','') <> v_source.persona_id::text THEN
    RAISE EXCEPTION 'invalid proactive reactivation envelope' USING ERRCODE='23514';
  END IF;
  SELECT * INTO v_publication FROM public.graph_publications
   WHERE id=p_publication_id AND persona_id=v_source.persona_id AND status='active';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reactivation publication is no longer active' USING ERRCODE='23514';
  END IF;

  v_envelope := public.enqueue_proactive_with_proof_v1(
    p_buffer,p_message,p_publication_id,p_evidence_node_ids,p_proof_result,p_model_proposal
  );
  UPDATE public.lead_buffer
     SET status='preview_ready', locked_at=NULL, locked_by=NULL,
         payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
           'reactivation_source_buffer_id',p_source_buffer_id::text,
           'reactivation_kind','operator_requested'
         ),
         updated_at=now()
   WHERE id=(v_envelope->>'buffer_id')::uuid;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.reactivation_preview','lead_buffer',v_envelope->>'buffer_id',v_source.persona_id,
    jsonb_build_object('source_buffer_id',p_source_buffer_id,'actor_user_id',p_actor_user_id,
      'publication_id',p_publication_id,'evidence_node_ids',p_evidence_node_ids),
    'info','messaging.queue');
  RETURN v_envelope || jsonb_build_object(
    'status','preview_ready','deduplicated',false,'source_buffer_id',p_source_buffer_id
  );
END; $$;

-- Awaiting-customer entries are intentionally not a transcript.  The one
-- available action makes a distinct proactive preview; the original outbound
-- remains an immutable delivery record.
CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL,
  p_origin text DEFAULT NULL,
  p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0,
  p_limit integer DEFAULT 50
) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH persona_scope AS (
    SELECT b.*, l.nome AS lead_name, p.name AS persona_name, p.slug AS persona_slug
      FROM public.lead_buffer b
      LEFT JOIN public.leads l ON l.id=b.lead_ref
      LEFT JOIN public.personas p ON p.id=b.persona_id
     WHERE p_persona_ids IS NULL OR b.persona_id=ANY(p_persona_ids)
  ), projected AS (
    SELECT s.*,
      CASE
        WHEN coalesce((s.payload->>'queue_pause')::boolean,false) THEN 'paused'
        WHEN s.direction='outbound' AND s.status='preview_ready' THEN 'preview_ready'
        WHEN s.direction='outbound' AND s.status IN ('buffered','pending_send','awaiting_proof','retry','failed','processing') THEN 'pending'
        WHEN s.direction='outbound' AND s.status IN ('sent','delivered','read')
          AND NOT EXISTS (
            SELECT 1 FROM public.lead_buffer newer
             WHERE newer.direction='inbound'
               AND newer.lead_ref=s.lead_ref
               AND newer.channel_binding_id IS NOT DISTINCT FROM s.channel_binding_id
               AND newer.created_at>s.created_at
          ) THEN 'awaiting_customer'
        WHEN s.direction='inbound' AND s.status='waiting_human'
          AND EXISTS (
            SELECT 1 FROM public.system_events event
             WHERE event.entity_type='lead_buffer' AND event.entity_id=s.id::text
               AND event.event_type IN ('conversation.technical_failure','conversation.technical_handoff')
          ) THEN 'technical_failure'
        ELSE NULL
      END AS queue_state
    FROM persona_scope s
  ), filtered AS (
    SELECT * FROM projected
     WHERE queue_state IS NOT NULL
       AND (p_origin IS NULL OR p_origin='' OR coalesce(message_origin,'conversation')=p_origin)
       AND (p_status IS NULL OR p_status='' OR queue_state=p_status)
  ), page AS (
    SELECT * FROM filtered
     ORDER BY coalesce(available_at,created_at), created_at, id
     OFFSET greatest(p_offset,0) LIMIT greatest(least(p_limit,100),1)
  )
  SELECT jsonb_build_object(
    'items', coalesce((
      SELECT jsonb_agg(jsonb_build_object(
        'id', id,
        'preview', left(coalesce(payload->>'text',payload->>'caption','[sem texto]'),240),
        'lead_ref', lead_ref,
        'lead', CASE WHEN lead_ref IS NULL THEN NULL ELSE jsonb_build_object('nome',lead_name) END,
        'persona_id', persona_id,
        'persona', jsonb_build_object('name',persona_name,'slug',persona_slug),
        'origin', coalesce(message_origin,'conversation'),
        'status', queue_state,
        'queue_state', queue_state,
        'available_at', available_at,
        'created_at', created_at,
        'last_error', last_error,
        'actions', CASE queue_state
          WHEN 'technical_failure' THEN jsonb_build_array('reprocess')
          WHEN 'preview_ready' THEN jsonb_build_array('send_preview','pause')
          WHEN 'pending' THEN jsonb_build_array('pause')
          WHEN 'paused' THEN jsonb_build_array('resume')
          WHEN 'awaiting_customer' THEN CASE
            WHEN coalesce(message_origin,'conversation') <> 'proactive' THEN jsonb_build_array('reactivate')
            ELSE '[]'::jsonb
          END
          ELSE '[]'::jsonb
        END
      )) FROM page
    ),'[]'::jsonb),
    'next_offset', CASE WHEN (SELECT count(*) FROM filtered)>greatest(p_offset,0)+greatest(least(p_limit,100),1)
      THEN greatest(p_offset,0)+greatest(least(p_limit,100),1) ELSE NULL END
  );
$$;

REVOKE ALL ON FUNCTION public.enqueue_reactivation_preview_with_proof_v1(uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_reactivation_preview_with_proof_v1(uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) TO brain_transport;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
