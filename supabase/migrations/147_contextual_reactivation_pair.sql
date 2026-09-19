-- Relational contextual reactivation queue.
-- Queue identity is queryable columns on lead_buffer; business identity,
-- revision and line semantics are not stored in payload JSONB.

ALTER TABLE public.lead_buffer
  ADD COLUMN IF NOT EXISTS queue_group_id uuid,
  ADD COLUMN IF NOT EXISTS queue_parent_buffer_id uuid REFERENCES public.lead_buffer(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS queue_line_kind text,
  ADD COLUMN IF NOT EXISTS queue_sequence smallint,
  ADD COLUMN IF NOT EXISTS queue_revision integer NOT NULL DEFAULT 1;

ALTER TABLE public.lead_buffer DROP CONSTRAINT IF EXISTS lead_buffer_queue_line_check;
ALTER TABLE public.lead_buffer ADD CONSTRAINT lead_buffer_queue_line_check CHECK (
  (queue_group_id IS NULL AND queue_parent_buffer_id IS NULL AND queue_line_kind IS NULL AND queue_sequence IS NULL)
  OR (queue_group_id IS NOT NULL AND queue_parent_buffer_id IS NOT NULL
      AND queue_line_kind IN ('apology','context') AND queue_sequence IN (1,2)
      AND queue_revision > 0)
);

ALTER TABLE public.lead_buffer DROP CONSTRAINT IF EXISTS lead_buffer_status_check;
ALTER TABLE public.lead_buffer ADD CONSTRAINT lead_buffer_status_check CHECK (status IN (
  'received','buffered','processing','awaiting_proof','preview_ready','pending_send',
  'sent','delivered','read','failed','retry','dead_letter','waiting_human','ignored','superseded'
));

CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_buffer_queue_line_identity
  ON public.lead_buffer(queue_group_id, queue_line_kind, queue_revision)
  WHERE queue_group_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lead_buffer_queue_group
  ON public.lead_buffer(queue_group_id, queue_revision, queue_sequence);

CREATE OR REPLACE FUNCTION public.enqueue_reactivation_pair_with_proof_v1(
  p_source_buffer_id uuid, p_apology_buffer jsonb, p_apology_message jsonb,
  p_context_buffer jsonb, p_context_message jsonb, p_publication_id uuid,
  p_evidence_node_ids jsonb, p_apology_proof_result jsonb, p_context_proof_result jsonb,
  p_apology_model_proposal jsonb DEFAULT '{}'::jsonb,
  p_context_model_proposal jsonb DEFAULT '{}'::jsonb,
  p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_source public.lead_buffer%ROWTYPE; v_lead public.leads%ROWTYPE;
  v_publication public.graph_publications%ROWTYPE; v_group uuid; v_revision integer;
  v_regenerate boolean; v_existing_count integer;
  v_apology jsonb; v_context jsonb; v_apology_id uuid; v_context_id uuid;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('reactivation:' || p_source_buffer_id::text));
  SELECT * INTO v_source FROM public.lead_buffer WHERE id=p_source_buffer_id FOR UPDATE;
  IF NOT FOUND OR v_source.direction <> 'outbound' OR v_source.status NOT IN ('sent','delivered','read') THEN
    RAISE EXCEPTION 'reactivation source was not delivered' USING ERRCODE='23514'; END IF;
  IF v_source.message_origin='proactive' THEN RAISE EXCEPTION 'reactivation cannot follow a proactive message' USING ERRCODE='23514'; END IF;
  SELECT * INTO v_lead FROM public.leads WHERE id=v_source.lead_ref FOR UPDATE;
  IF NOT FOUND OR v_lead.persona_id IS DISTINCT FROM v_source.persona_id THEN RAISE EXCEPTION 'reactivation lead is invalid' USING ERRCODE='23514'; END IF;
  IF coalesce(v_lead.handoff_level,'none') <> 'none' THEN RAISE EXCEPTION 'reactivation is blocked by human handoff' USING ERRCODE='23514'; END IF;
  IF EXISTS (SELECT 1 FROM public.lead_buffer i WHERE i.direction='inbound' AND i.lead_ref=v_source.lead_ref
      AND i.channel_binding_id IS NOT DISTINCT FROM v_source.channel_binding_id AND i.created_at>v_source.created_at)
    THEN RAISE EXCEPTION 'reactivation is obsolete after a newer inbound' USING ERRCODE='23514'; END IF;
  IF EXISTS (SELECT 1 FROM public.contact_consents c WHERE c.lead_id=v_source.lead_ref AND c.persona_id=v_source.persona_id
      AND c.channel='whatsapp' AND c.status IN ('refused','revoked') AND (c.valid_until IS NULL OR c.valid_until>now()))
    THEN RAISE EXCEPTION 'reactivation is blocked by opt-out' USING ERRCODE='23514'; END IF;
  IF EXISTS (SELECT 1 FROM public.campaign_recipients r WHERE r.lead_id=v_source.lead_ref AND r.persona_id=v_source.persona_id AND r.contact_status='provider_blocked')
    THEN RAISE EXCEPTION 'reactivation is blocked by provider status' USING ERRCODE='23514'; END IF;
  IF v_source.campaign_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.campaigns c WHERE c.id=v_source.campaign_id AND c.status='cancelled')
    THEN RAISE EXCEPTION 'reactivation is blocked by cancelled campaign' USING ERRCODE='23514'; END IF;

  BEGIN v_group := (p_apology_buffer->>'queue_group_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'invalid reactivation queue group' USING ERRCODE='23514'; END;
  v_revision := coalesce((p_apology_buffer->>'queue_revision')::integer,0);
  IF v_group IS NULL OR v_revision < 1
     OR (p_context_buffer->>'queue_group_id')::uuid IS DISTINCT FROM v_group
     OR coalesce((p_context_buffer->>'queue_revision')::integer,0) <> v_revision
     OR p_apology_buffer->>'queue_line_kind' <> 'apology' OR p_context_buffer->>'queue_line_kind' <> 'context'
     OR coalesce((p_apology_buffer->>'queue_sequence')::integer,0) <> 1
     OR coalesce((p_context_buffer->>'queue_sequence')::integer,0) <> 2
    THEN RAISE EXCEPTION 'invalid reactivation pair envelope' USING ERRCODE='23514'; END IF;
  v_regenerate := coalesce((p_apology_buffer->>'queue_regenerate')::boolean, false);
  SELECT count(*) INTO v_existing_count
    FROM public.lead_buffer
   WHERE queue_group_id=v_group AND queue_revision=v_revision;
  IF NOT v_regenerate AND v_existing_count > 0 THEN
    IF v_existing_count <> 2 THEN
      RAISE EXCEPTION 'reactivation pair is incomplete' USING ERRCODE='23514';
    END IF;
    RETURN jsonb_build_object(
      'reactivation_group_id',v_group,'preview_revision',v_revision,'deduplicated',true,
      'lines',coalesce((SELECT jsonb_agg(jsonb_build_object(
        'buffer_id',id,'line_kind',queue_line_kind,'sequence_index',queue_sequence,'status',status
      ) ORDER BY queue_sequence) FROM public.lead_buffer
       WHERE queue_group_id=v_group AND queue_revision=v_revision),'[]'::jsonb)
    );
  END IF;
  IF v_regenerate THEN
    SELECT coalesce(max(queue_revision),0)+1 INTO v_revision
      FROM public.lead_buffer WHERE queue_group_id=v_group;
  END IF;
  SELECT * INTO v_publication FROM public.graph_publications WHERE id=p_publication_id AND persona_id=v_source.persona_id AND status='active';
  IF NOT FOUND THEN RAISE EXCEPTION 'reactivation publication is no longer active' USING ERRCODE='23514'; END IF;

  UPDATE public.lead_buffer SET status='superseded', updated_at=now()
   WHERE queue_group_id=v_group AND queue_revision<v_revision
     AND status IN ('preview_ready','buffered','pending_send','awaiting_proof','retry','processing');
  v_apology := public.enqueue_proactive_with_proof_v1(p_apology_buffer,p_apology_message,p_publication_id,p_evidence_node_ids,p_apology_proof_result,p_apology_model_proposal);
  v_apology_id := (v_apology->>'buffer_id')::uuid;
  UPDATE public.lead_buffer SET queue_group_id=v_group, queue_parent_buffer_id=p_source_buffer_id, queue_line_kind='apology', queue_sequence=1, queue_revision=v_revision, status='preview_ready', locked_at=NULL, locked_by=NULL, updated_at=now() WHERE id=v_apology_id;
  v_context := public.enqueue_proactive_with_proof_v1(p_context_buffer,p_context_message,p_publication_id,p_evidence_node_ids,p_context_proof_result,p_context_model_proposal);
  v_context_id := (v_context->>'buffer_id')::uuid;
  UPDATE public.lead_buffer SET queue_group_id=v_group, queue_parent_buffer_id=p_source_buffer_id, queue_line_kind='context', queue_sequence=2, queue_revision=v_revision, status='preview_ready', locked_at=NULL, locked_by=NULL, updated_at=now() WHERE id=v_context_id;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.reactivation_pair','lead_buffer',v_apology_id::text,v_source.persona_id,
      jsonb_build_object('source_buffer_id',p_source_buffer_id,'context_buffer_id',v_context_id,'queue_group_id',v_group,'queue_revision',v_revision,'publication_id',p_publication_id,'actor_user_id',p_actor_user_id),'info','messaging.queue');
  RETURN jsonb_build_object('reactivation_group_id',v_group,'preview_revision',v_revision,'deduplicated',false,'lines',jsonb_build_array(
    jsonb_build_object('buffer_id',v_apology_id,'line_kind','apology','sequence_index',1,'status','preview_ready'),
    jsonb_build_object('buffer_id',v_context_id,'line_kind','context','sequence_index',2,'status','preview_ready')));
END; $$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH scoped AS (
    SELECT b.*, l.nome AS lead_name, p.name AS persona_name, p.slug AS persona_slug,
      parent.created_at AS parent_created_at, previous_message.content AS previous_message,
      latest_inbound.content AS latest_inbound_context, proof.id AS proof_id, proof.publication_id
    FROM public.lead_buffer b
    LEFT JOIN public.leads l ON l.id=b.lead_ref LEFT JOIN public.personas p ON p.id=b.persona_id
    LEFT JOIN public.lead_buffer parent ON parent.id=b.queue_parent_buffer_id
    LEFT JOIN LATERAL (SELECT m.content FROM public.messages m WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref) AND m.direction='outbound' AND m.created_at<=coalesce(parent.created_at,b.created_at) ORDER BY m.created_at DESC LIMIT 1) previous_message ON true
    LEFT JOIN LATERAL (SELECT m.content FROM public.messages m WHERE m.lead_id=coalesce(parent.lead_ref,b.lead_ref) AND m.direction='inbound' AND m.created_at<=coalesce(parent.created_at,b.created_at) ORDER BY m.created_at DESC LIMIT 1) latest_inbound ON true
    LEFT JOIN public.conversation_turn_proofs proof ON proof.canonical_inbound_id='proactive:' || b.id::text
    WHERE (p_persona_ids IS NULL OR b.persona_id=ANY(p_persona_ids))
      AND coalesce(b.correlation_id,'') NOT LIKE 'validator:%' AND coalesce(b.correlation_id,'') NOT LIKE 'inbound:wa-validator:%'
  ), projected AS (
    SELECT s.*, CASE
      WHEN coalesce((s.payload->>'queue_pause')::boolean,false) THEN 'paused'
      WHEN s.status='superseded' THEN NULL
      WHEN s.direction='outbound' AND s.status='preview_ready' THEN 'preview_ready'
      WHEN s.direction='outbound' AND s.status IN ('buffered','pending_send','awaiting_proof','retry','failed','processing') THEN 'pending'
      WHEN s.direction='outbound' AND s.status IN ('sent','delivered','read') AND coalesce(s.message_origin,'conversation') <> 'proactive'
        AND NOT EXISTS (SELECT 1 FROM public.lead_buffer newer WHERE newer.direction='inbound' AND newer.lead_ref=s.lead_ref AND newer.channel_binding_id IS NOT DISTINCT FROM s.channel_binding_id AND newer.created_at>s.created_at) THEN 'awaiting_customer'
      WHEN s.direction='inbound' AND s.status='waiting_human' AND EXISTS (SELECT 1 FROM public.system_events e WHERE e.entity_type='lead_buffer' AND e.entity_id=s.id::text AND e.event_type IN ('conversation.technical_failure','conversation.technical_handoff')) THEN 'technical_failure'
      ELSE NULL END AS queue_state
    FROM scoped s
  ), filtered AS (SELECT * FROM projected WHERE queue_state IS NOT NULL AND (p_origin IS NULL OR p_origin='' OR coalesce(message_origin,'conversation')=p_origin) AND (p_status IS NULL OR p_status='' OR queue_state=p_status)), page AS (SELECT * FROM filtered ORDER BY coalesce(available_at,created_at),created_at,id OFFSET greatest(p_offset,0) LIMIT greatest(least(p_limit,100),1))
  SELECT jsonb_build_object('items',coalesce((SELECT jsonb_agg(jsonb_build_object(
    'id',id,'preview',left(coalesce(payload->>'text',payload->>'caption','[sem texto]'),240),'preview_text',left(coalesce(payload->>'text',payload->>'caption',''),2000),
    'lead_ref',lead_ref,'lead',CASE WHEN lead_ref IS NULL THEN NULL ELSE jsonb_build_object('nome',lead_name) END,'persona_id',persona_id,'persona',jsonb_build_object('name',persona_name,'slug',persona_slug),
    'origin',coalesce(message_origin,'conversation'),'status',queue_state,'queue_state',queue_state,'available_at',available_at,'created_at',created_at,'last_error',last_error,
    'reactivation_group_id',queue_group_id,'queue_parent_buffer_id',queue_parent_buffer_id,'sequence_index',queue_sequence,'line_kind',queue_line_kind,'preview_revision',queue_revision,
    'previous_message',previous_message,'latest_inbound_context',latest_inbound_context,'proof_id',proof_id,'publication_id',publication_id,
    'actions',CASE
      WHEN queue_state='technical_failure' THEN jsonb_build_array('reprocess')
      WHEN queue_state='preview_ready' AND queue_group_id IS NOT NULL THEN jsonb_build_array('send_preview','regenerate_preview','handoff','pause')
      WHEN queue_state='preview_ready' THEN jsonb_build_array('send_preview','pause')
      WHEN queue_state='pending' THEN jsonb_build_array('pause')
      WHEN queue_state='paused' THEN jsonb_build_array('resume')
      WHEN queue_state='awaiting_customer' AND coalesce(message_origin,'conversation') <> 'proactive' THEN jsonb_build_array('reactivate')
      ELSE '[]'::jsonb END
  )) FROM page),'[]'::jsonb),'next_offset',CASE WHEN (SELECT count(*) FROM filtered)>greatest(p_offset,0)+greatest(least(p_limit,100),1) THEN greatest(p_offset,0)+greatest(least(p_limit,100),1) ELSE NULL END);
$$;

CREATE OR REPLACE FUNCTION public.handoff_reactivation_lines_v1(p_buffer_ids uuid[], p_actor_user_id uuid DEFAULT NULL, p_reason text DEFAULT 'handoff_operacional_fila_reativacao') RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.lead_buffer%ROWTYPE; v_lead_ref bigint; v_group uuid; v_count integer:=0; v_selected_count integer:=0;
BEGIN
  IF coalesce(array_length(p_buffer_ids,1),0)=0 THEN RAISE EXCEPTION 'reactivation lines are required' USING ERRCODE='22023'; END IF;
  SELECT lead_ref,queue_group_id INTO v_lead_ref,v_group FROM public.lead_buffer WHERE id=ANY(p_buffer_ids) AND queue_group_id IS NOT NULL ORDER BY created_at LIMIT 1 FOR UPDATE;
  IF v_lead_ref IS NULL OR v_group IS NULL THEN RAISE EXCEPTION 'reactivation line was not found' USING ERRCODE='P0002'; END IF;
  SELECT count(*) INTO v_selected_count FROM public.lead_buffer
   WHERE id=ANY(p_buffer_ids) AND queue_group_id=v_group AND lead_ref=v_lead_ref;
  IF v_selected_count <> array_length(p_buffer_ids,1) THEN
    RAISE EXCEPTION 'reactivation lines must belong to one pair' USING ERRCODE='22023';
  END IF;
  SELECT * INTO v_row FROM public.lead_buffer WHERE queue_group_id=v_group FOR UPDATE LIMIT 1;
  UPDATE public.leads SET handoff_level='full', updated_at=now() WHERE id=v_lead_ref;
  UPDATE public.lead_buffer SET status='waiting_human', locked_at=NULL, locked_by=NULL, updated_at=now() WHERE queue_group_id=v_group AND status IN ('preview_ready','buffered','pending_send','awaiting_proof','retry','processing');
  GET DIAGNOSTICS v_count = ROW_COUNT;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source) VALUES ('messaging.queue.handoff','lead_buffer',v_row.id::text,v_row.persona_id,jsonb_build_object('reason',p_reason,'actor_user_id',p_actor_user_id,'queue_group_id',v_group),'info','messaging.queue');
  RETURN jsonb_build_object('items',jsonb_build_array(jsonb_build_object('result','handoff','count',v_count,'reason',p_reason)));
END; $$;

REVOKE ALL ON FUNCTION public.enqueue_reactivation_pair_with_proof_v1(uuid,jsonb,jsonb,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_reactivation_pair_with_proof_v1(uuid,jsonb,jsonb,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,uuid) TO brain_transport;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO brain_control_plane;
REVOKE ALL ON FUNCTION public.handoff_reactivation_lines_v1(uuid[],uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.handoff_reactivation_lines_v1(uuid[],uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.handoff_reactivation_lines_v1(uuid[],uuid,text) TO brain_control_plane;
NOTIFY pgrst, 'reload schema';
