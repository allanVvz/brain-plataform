-- Project the operational queue as customer demands, not transcript rows.
-- No data is removed and no new table is introduced.  Validator traffic
-- remains persisted for /logs but is excluded here by canonical transport and
-- lead metadata before ranking or pagination.

CREATE INDEX IF NOT EXISTS idx_messages_queue_context
  ON public.messages (lead_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_turn_proofs_outbound
  ON public.conversation_turn_proofs (outbound_id);

-- Regenerate one line of a contextual reactivation.  The immutable proof of
-- the previous line is retained for audit; only that line's mutable queue
-- revision is superseded.  The sibling line is never recreated or resent.
CREATE OR REPLACE FUNCTION public.enqueue_reactivation_line_revision_v1(
  p_previous_buffer_id uuid, p_buffer jsonb, p_message jsonb,
  p_publication_id uuid, p_evidence_node_ids jsonb, p_proof_result jsonb,
  p_model_proposal jsonb DEFAULT '{}'::jsonb, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_previous public.lead_buffer%ROWTYPE;
  v_latest public.lead_buffer%ROWTYPE;
  v_source public.lead_buffer%ROWTYPE;
  v_publication public.graph_publications%ROWTYPE;
  v_envelope jsonb;
  v_new_id uuid;
  v_revision integer;
BEGIN
  SELECT * INTO v_previous FROM public.lead_buffer
   WHERE id=p_previous_buffer_id FOR UPDATE;
  IF NOT FOUND OR v_previous.direction<>'outbound'
     OR v_previous.queue_group_id IS NULL OR v_previous.queue_sequence NOT IN (1,2) THEN
    RAISE EXCEPTION 'queue message is not a reactivation line' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('reactivation:'||v_previous.queue_group_id::text));
  SELECT * INTO v_latest FROM public.lead_buffer
   WHERE queue_group_id=v_previous.queue_group_id
     AND queue_sequence=v_previous.queue_sequence
   ORDER BY queue_revision DESC,created_at DESC,id DESC LIMIT 1 FOR UPDATE;
  IF v_latest.id IS DISTINCT FROM v_previous.id THEN
    RAISE EXCEPTION 'queue message revision is no longer current' USING ERRCODE='40001';
  END IF;
  IF v_previous.status IN ('sent','delivered','read') THEN
    RAISE EXCEPTION 'a confirmed message cannot be regenerated' USING ERRCODE='23514';
  END IF;
  SELECT * INTO v_source FROM public.lead_buffer
   WHERE id=v_previous.queue_parent_buffer_id FOR UPDATE;
  IF NOT FOUND OR v_source.direction<>'outbound'
     OR v_source.status NOT IN ('sent','delivered','read') THEN
    RAISE EXCEPTION 'reactivation source is no longer confirmed' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.lead_buffer incoming
     WHERE incoming.direction='inbound' AND incoming.lead_ref=v_previous.lead_ref
       AND incoming.channel_binding_id IS NOT DISTINCT FROM v_previous.channel_binding_id
       AND incoming.created_at>v_source.created_at
  ) THEN
    RAISE EXCEPTION 'reactivation is obsolete after a newer inbound' USING ERRCODE='23514';
  END IF;
  SELECT * INTO v_publication FROM public.graph_publications
   WHERE id=p_publication_id AND persona_id=v_previous.persona_id AND status='active';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reactivation publication is no longer active' USING ERRCODE='23514';
  END IF;
  v_revision:=coalesce(v_previous.queue_revision,0)+1;
  IF (p_buffer->>'queue_group_id')::uuid IS DISTINCT FROM v_previous.queue_group_id
     OR coalesce((p_buffer->>'queue_sequence')::integer,0)<>v_previous.queue_sequence
     OR coalesce((p_buffer->>'queue_revision')::integer,0)<>v_revision
     OR p_buffer->>'queue_line_kind' IS DISTINCT FROM v_previous.queue_line_kind THEN
    RAISE EXCEPTION 'invalid queue line revision envelope' USING ERRCODE='23514';
  END IF;
  v_envelope:=public.enqueue_proactive_with_proof_v1(
    p_buffer,p_message,p_publication_id,p_evidence_node_ids,p_proof_result,p_model_proposal
  );
  v_new_id:=(v_envelope->>'buffer_id')::uuid;
  UPDATE public.lead_buffer SET
    queue_group_id=v_previous.queue_group_id,
    queue_parent_buffer_id=v_previous.queue_parent_buffer_id,
    queue_line_kind=v_previous.queue_line_kind,
    queue_sequence=v_previous.queue_sequence,
    queue_revision=v_revision,status='preview_ready',locked_at=NULL,locked_by=NULL,
    updated_at=now()
   WHERE id=v_new_id;
  UPDATE public.lead_buffer SET status='superseded',updated_at=now()
   WHERE id=v_previous.id AND status NOT IN ('sent','delivered','read');
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.line_retried','lead_buffer',v_new_id::text,v_previous.persona_id,
    jsonb_build_object('previous_buffer_id',v_previous.id,'queue_group_id',v_previous.queue_group_id,
      'sequence',v_previous.queue_sequence,'queue_revision',v_revision,
      'proof_id',v_envelope->'proof'->>'proof_id','actor_user_id',p_actor_user_id),
    'info','messaging.queue');
  RETURN v_envelope||jsonb_build_object('status','preview_ready','deduplicated',false,
    'previous_buffer_id',v_previous.id,'reactivation_group_id',v_previous.queue_group_id,
    'preview_revision',v_revision,'lines',jsonb_build_array(jsonb_build_object(
      'buffer_id',v_new_id,'line_kind',v_previous.queue_line_kind,
      'sequence_index',v_previous.queue_sequence,'status','preview_ready')));
END; $$;

-- Ordinary conversation previews also support an isolated revision.  A retry
-- gets a new immutable proof identity while retaining the original canonical
-- inbound as audit context; it never reclaims or replays that inbound.
CREATE OR REPLACE FUNCTION public.enqueue_queue_message_revision_v1(
  p_previous_buffer_id uuid, p_canonical_inbound_id uuid,
  p_buffer jsonb, p_message jsonb, p_publication_id uuid,
  p_evidence_node_ids jsonb, p_proof_result jsonb,
  p_model_proposal jsonb DEFAULT '{}'::jsonb, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_previous public.lead_buffer%ROWTYPE;
  v_inbound public.lead_buffer%ROWTYPE;
  v_latest_id uuid;
  v_publication public.graph_publications%ROWTYPE;
  v_envelope jsonb;
  v_new_id uuid;
  v_proof_id uuid;
  v_revision integer;
  v_identity text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('queue-retry:'||p_canonical_inbound_id::text));
  SELECT * INTO v_previous FROM public.lead_buffer WHERE id=p_previous_buffer_id FOR UPDATE;
  SELECT * INTO v_inbound FROM public.lead_buffer WHERE id=p_canonical_inbound_id FOR UPDATE;
  IF NOT FOUND OR v_inbound.direction<>'inbound' THEN
    RAISE EXCEPTION 'canonical inbound was not found' USING ERRCODE='23514'; END IF;
  IF v_previous.id IS NULL OR v_previous.direction<>'outbound'
     OR v_previous.status IN ('sent','delivered','read','pending_send','processing','buffered')
     OR v_previous.lead_ref IS DISTINCT FROM v_inbound.lead_ref
     OR v_previous.persona_id IS DISTINCT FROM v_inbound.persona_id
     OR v_previous.channel_binding_id IS DISTINCT FROM v_inbound.channel_binding_id THEN
    RAISE EXCEPTION 'queue preview is not individually retryable' USING ERRCODE='23514';
  END IF;
  SELECT candidate.id INTO v_latest_id
    FROM public.lead_buffer candidate
    LEFT JOIN public.conversation_turn_proofs candidate_proof ON candidate_proof.outbound_id=candidate.id::text
   WHERE candidate.direction='outbound'
     AND candidate.lead_ref=v_previous.lead_ref
     AND candidate.channel_binding_id IS NOT DISTINCT FROM v_previous.channel_binding_id
     AND candidate.status<>'superseded'
     AND (candidate.id=v_previous.id
       OR candidate.payload->>'queue_canonical_inbound_id'=p_canonical_inbound_id::text
       OR candidate_proof.canonical_inbound_id=p_canonical_inbound_id::text
       OR candidate_proof.final_decision->>'queue_canonical_inbound_id'=p_canonical_inbound_id::text)
   ORDER BY coalesce(candidate.queue_revision,1) DESC,candidate.created_at DESC,candidate.id DESC LIMIT 1;
  IF v_latest_id IS DISTINCT FROM v_previous.id THEN
    RAISE EXCEPTION 'queue preview revision is no longer current' USING ERRCODE='40001'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.conversation_turn_proofs prior
    WHERE prior.outbound_id=v_previous.id::text AND (
      prior.canonical_inbound_id=p_canonical_inbound_id::text
      OR prior.final_decision->>'queue_canonical_inbound_id'=p_canonical_inbound_id::text)) THEN
    RAISE EXCEPTION 'previous queue preview proof is missing' USING ERRCODE='23514'; END IF;
  IF EXISTS (SELECT 1 FROM public.lead_buffer newer WHERE newer.direction='inbound'
    AND newer.lead_ref=v_inbound.lead_ref
    AND newer.channel_binding_id IS NOT DISTINCT FROM v_inbound.channel_binding_id
    AND newer.created_at>v_inbound.created_at) THEN
    RAISE EXCEPTION 'queue preview is obsolete after a newer inbound' USING ERRCODE='23514'; END IF;
  SELECT * INTO v_publication FROM public.graph_publications
   WHERE id=p_publication_id AND persona_id=v_inbound.persona_id AND status='active';
  IF NOT FOUND THEN RAISE EXCEPTION 'queue preview publication is not active' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(p_evidence_node_ids)<>'array' OR jsonb_array_length(p_evidence_node_ids)=0
     OR NOT coalesce((p_proof_result->>'delivery_authorized')::boolean,(p_proof_result->>'valid')::boolean,false) THEN
    RAISE EXCEPTION 'queue preview retry requires a valid proof' USING ERRCODE='23514'; END IF;
  v_revision:=coalesce((p_buffer->>'queue_revision')::integer,0);
  IF v_revision<>coalesce(v_previous.queue_revision,1)+1
     OR coalesce(p_buffer->>'status','')<>'awaiting_proof'
     OR coalesce(p_buffer->>'message_origin','')<>'conversation'
     OR coalesce(p_buffer->>'lead_ref','')<>v_inbound.lead_ref::text
     OR coalesce(p_buffer->>'persona_id','')<>v_inbound.persona_id::text THEN
    RAISE EXCEPTION 'invalid queue preview revision envelope' USING ERRCODE='23514'; END IF;
  v_envelope:=public.enqueue_whatsapp_envelope(p_buffer,p_message);
  v_new_id:=(v_envelope->>'buffer_id')::uuid;
  v_identity:='queue-retry:'||p_canonical_inbound_id::text||':r'||v_revision::text;
  INSERT INTO public.conversation_turn_proofs(
    canonical_inbound_id,publication_id,retrieval_trace,model_proposal,
    proof_result,final_decision,outbound_id
  ) VALUES (
    v_identity,p_publication_id,
    jsonb_build_object('evidence_node_ids',p_evidence_node_ids,'queue_origin','operator_retry','queue_canonical_inbound_id',p_canonical_inbound_id),
    coalesce(p_model_proposal,'{}'::jsonb),coalesce(p_proof_result,'{}'::jsonb),
    jsonb_build_object('kind','queue_message_retry','queue_canonical_inbound_id',p_canonical_inbound_id,'buffer_id',v_new_id),v_new_id::text
  ) RETURNING id INTO v_proof_id;
  UPDATE public.lead_buffer SET status='preview_ready',locked_at=NULL,locked_by=NULL,
    queue_revision=v_revision,
    payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object(
      'queue_canonical_inbound_id',p_canonical_inbound_id::text,
      'queue_retry_revision',v_revision),
    updated_at=now() WHERE id=v_new_id;
  UPDATE public.lead_buffer SET status='superseded',updated_at=now()
   WHERE id=v_previous.id AND status NOT IN ('sent','delivered','read');
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.message_retried','lead_buffer',v_new_id::text,v_inbound.persona_id,
    jsonb_build_object('previous_buffer_id',v_previous.id,'canonical_inbound_id',p_canonical_inbound_id,
      'queue_revision',v_revision,'proof_id',v_proof_id,'actor_user_id',p_actor_user_id),'info','messaging.queue');
  RETURN v_envelope||jsonb_build_object('status','preview_ready','proof_id',v_proof_id,
    'preview_revision',v_revision,'previous_buffer_id',v_previous.id,'deduplicated',false);
END; $$;

-- Sending is a separate, atomic action.  It revalidates the current proof,
-- active publication, pause/handoff state, absence of a newer inbound and the
-- predecessor acknowledgement for sequence 2.  Repeated clicks cannot turn a
-- pending/sent row into another provider attempt.
CREATE OR REPLACE FUNCTION public.control_message_queue_v2(
  p_buffer_ids uuid[], p_action text, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE; v_results jsonb:='[]'::jsonb;
  v_result text; v_reason text; v_target timestamptz; v_previous text;
  v_hours jsonb; v_start time; v_end time; v_tz text;
BEGIN
  IF p_action NOT IN ('pause','resume','send_preview') THEN
    RAISE EXCEPTION 'unsupported queue action' USING ERRCODE='22023'; END IF;
  IF coalesce(array_length(p_buffer_ids,1),0)=0 THEN
    RAISE EXCEPTION 'buffer ids are required' USING ERRCODE='22023'; END IF;
  FOR v_row IN SELECT * FROM public.lead_buffer WHERE id=ANY(p_buffer_ids)
    ORDER BY coalesce(queue_sequence,1),created_at,id FOR UPDATE LOOP
    v_result:=NULL; v_reason:=NULL; v_target:=NULL; v_previous:=v_row.status;
    IF p_action='pause' THEN
      IF v_row.status IN ('sent','delivered','read','dead_letter','ignored','superseded') THEN
        v_result:='bloqueado'; v_reason:='estado_terminal';
      ELSIF v_row.status='preview_ready' THEN
        UPDATE public.lead_buffer SET payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_pause',true),updated_at=now() WHERE id=v_row.id;
        v_result:='pausado';
      ELSE
        v_target:=now()+interval '10 years';
        UPDATE public.lead_buffer SET status='buffered',available_at=v_target,payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_pause',true),updated_at=now() WHERE id=v_row.id;
        v_result:='pausado';
      END IF;
    ELSIF p_action='resume' THEN
      IF NOT coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
        v_result:='superado'; v_reason:='item_nao_esta_pausado_pela_fila';
      ELSIF v_row.status IN ('sent','delivered','read','dead_letter','ignored','superseded') THEN
        v_result:='bloqueado'; v_reason:='estado_terminal';
      ELSIF v_row.status='preview_ready' THEN
        UPDATE public.lead_buffer SET payload=coalesce(payload,'{}'::jsonb)-'queue_pause',updated_at=now() WHERE id=v_row.id;
        v_result:='retomado';
      ELSE
        v_hours:=v_row.payload->'published_business_hours';
        BEGIN
          v_start:=(v_hours->>'start')::time; v_end:=(v_hours->>'end')::time; v_tz:=nullif(v_hours->>'timezone','');
          IF v_start>=v_end OR v_tz IS NULL THEN RAISE EXCEPTION 'invalid policy'; END IF;
          v_target:=public.next_business_hours_slot(now(),0,1,v_start,v_end,v_tz);
        EXCEPTION WHEN OTHERS THEN v_target:=NULL; v_reason:='politica_publicada_indisponivel'; END;
        IF v_target IS NULL THEN v_result:='bloqueado';
        ELSE
          UPDATE public.lead_buffer SET status='buffered',available_at=v_target,payload=coalesce(payload,'{}'::jsonb)-'queue_pause',updated_at=now() WHERE id=v_row.id;
          v_result:='agendado';
        END IF;
      END IF;
    ELSE
      IF v_row.direction<>'outbound' OR v_row.status<>'preview_ready' THEN
        v_result:='bloqueado'; v_reason:='preview_nao_encontrado_ou_ja_enviado';
      ELSIF coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
        v_result:='bloqueado'; v_reason:='preview_pausado';
      ELSIF EXISTS (SELECT 1 FROM public.leads l WHERE l.id=v_row.lead_ref AND (coalesce(l.ai_paused,false) OR coalesce(l.handoff_level,'none')<>'none')) THEN
        v_result:='bloqueado'; v_reason:='lead_pausada_ou_em_handoff';
      ELSIF EXISTS (SELECT 1 FROM public.workflow_bindings w WHERE w.id=v_row.channel_binding_id AND (coalesce(w.metadata->>'safety_paused','false')='true' OR w.connection_status='safety_paused')) THEN
        v_result:='bloqueado'; v_reason:='binding_pausado';
      ELSIF EXISTS (SELECT 1 FROM public.lead_buffer i WHERE i.direction='inbound' AND i.lead_ref=v_row.lead_ref AND i.channel_binding_id IS NOT DISTINCT FROM v_row.channel_binding_id AND i.created_at>coalesce((SELECT created_at FROM public.lead_buffer WHERE id=v_row.queue_parent_buffer_id),v_row.created_at)) THEN
        v_result:='superado'; v_reason:='nova_mensagem_da_lead';
      ELSIF NOT EXISTS (SELECT 1 FROM public.conversation_turn_proofs p JOIN public.graph_publications gp ON gp.id=p.publication_id AND gp.status='active' AND gp.persona_id=v_row.persona_id WHERE p.outbound_id=v_row.id::text AND coalesce((p.proof_result->>'delivery_authorized')::boolean,(p.proof_result->>'valid')::boolean,false)) THEN
        v_result:='bloqueado'; v_reason:='proof_ou_publicacao_invalida';
      ELSIF v_row.queue_sequence=2 AND NOT EXISTS (
        SELECT 1 FROM (
          SELECT first_line.status FROM public.lead_buffer first_line
           WHERE first_line.queue_group_id=v_row.queue_group_id AND first_line.queue_sequence=1
           ORDER BY first_line.queue_revision DESC,first_line.created_at DESC,first_line.id DESC LIMIT 1
        ) latest_first WHERE latest_first.status IN ('sent','delivered','read')
      ) THEN
        v_result:='bloqueado'; v_reason:='mensagem_1_ainda_nao_confirmada';
      ELSE
        UPDATE public.lead_buffer SET status='pending_send',updated_at=now() WHERE id=v_row.id AND status='preview_ready';
        SELECT available_at INTO v_target FROM public.lead_buffer WHERE id=v_row.id;
        v_result:='agendado';
      END IF;
    END IF;
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.'||p_action,'lead_buffer',v_row.id::text,v_row.persona_id,jsonb_build_object('result',v_result,'reason',v_reason,'actor_user_id',p_actor_user_id,'previous_status',v_previous,'scheduled_for',v_target),'info','messaging.queue');
    v_results:=v_results||jsonb_build_array(jsonb_build_object('buffer_id',v_row.id,'result',v_result,'reason',v_reason,'previous_status',v_previous,'scheduled_for',v_target));
  END LOOP;
  RETURN jsonb_build_object('items',v_results);
END; $$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v156(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
WITH buffer_scope AS (
  SELECT b.*,l.nome AS lead_name,l.metadata AS lead_metadata,l.lead_id AS lead_identity,
    p.name AS persona_name,p.slug AS persona_slug,w.provider AS binding_provider,
    proof_by_outbound.canonical_inbound_id,
    coalesce(b.queue_group_id::text,b.payload->>'queue_canonical_inbound_id',
      proof_by_outbound.final_decision->>'queue_canonical_inbound_id',
      proof_by_outbound.canonical_inbound_id,b.id::text) AS demand_key,
    CASE
      WHEN coalesce((b.payload->>'queue_pause')::boolean,false) THEN 'paused'
      WHEN b.status='superseded' THEN NULL
      WHEN b.direction='outbound' AND b.status='preview_ready' THEN 'preview_ready'
      WHEN b.direction='outbound' AND b.status IN ('buffered','pending_send','awaiting_proof','retry','failed','processing') THEN 'pending'
      WHEN b.direction='outbound' AND b.status IN ('sent','delivered','read') AND b.queue_group_id IS NOT NULL THEN 'message_sent'
      WHEN b.direction='outbound' AND b.status IN ('sent','delivered','read') AND coalesce(b.message_origin,'conversation')<>'proactive'
        AND NOT EXISTS (SELECT 1 FROM public.lead_buffer newer WHERE newer.direction='inbound' AND newer.lead_ref=b.lead_ref AND newer.channel_binding_id IS NOT DISTINCT FROM b.channel_binding_id AND newer.created_at>b.created_at) THEN 'awaiting_customer'
      WHEN b.direction='inbound' AND b.status IN ('received','buffered','processing','retry') THEN 'pending_response'
      WHEN b.direction='inbound' AND b.status IN ('waiting_human','dead_letter')
        AND EXISTS (SELECT 1 FROM public.system_events e WHERE e.entity_type='lead_buffer' AND e.entity_id=b.id::text AND e.event_type IN ('conversation.technical_failure','conversation.technical_handoff'))
        AND NOT EXISTS (SELECT 1 FROM public.conversation_turn_proofs pr WHERE pr.canonical_inbound_id=b.id::text)
        THEN 'technical_failure'
      WHEN b.direction='inbound' AND b.status IN ('waiting_human','dead_letter') THEN 'blocked'
      ELSE NULL END AS item_state
  FROM public.lead_buffer b
  LEFT JOIN public.leads l ON l.id=b.lead_ref
  LEFT JOIN public.personas p ON p.id=b.persona_id
  LEFT JOIN public.workflow_bindings w ON w.id=b.channel_binding_id
  LEFT JOIN LATERAL (SELECT pr.canonical_inbound_id,pr.final_decision FROM public.conversation_turn_proofs pr WHERE pr.outbound_id=b.id::text ORDER BY pr.created_at DESC LIMIT 1) proof_by_outbound ON true
  WHERE (p_persona_ids IS NULL OR b.persona_id=ANY(p_persona_ids))
    AND coalesce(b.payload->>'provider','')<>'internal_validator'
    AND coalesce(b.payload->>'validation_transport','false')<>'true'
    AND coalesce(w.provider,'')<>'internal_validator'
    AND coalesce(l.metadata->'validation'->>'is_validation','false')<>'true'
    AND coalesce(l.metadata->>'validator_session_id','')=''
    AND coalesce(l.lead_id,'') !~ '^validator_'
), latest_sequence AS (
  SELECT scoped.*,row_number() OVER (PARTITION BY persona_id,lead_ref,demand_key,coalesce(queue_sequence,1) ORDER BY coalesce(queue_revision,1) DESC,created_at DESC,id DESC) AS sequence_rank
  FROM buffer_scope scoped WHERE status<>'superseded'
), current_buffers AS (
  SELECT * FROM latest_sequence WHERE sequence_rank=1
), actionable_keys AS (
  SELECT persona_id,lead_ref,demand_key FROM current_buffers
   GROUP BY persona_id,lead_ref,demand_key HAVING bool_or(item_state IS NOT NULL AND item_state<>'message_sent')
), demands AS (
  SELECT c.persona_id,c.lead_ref,c.demand_key,
    (array_agg(c.id ORDER BY c.created_at DESC,c.id DESC))[1] AS id,
    (array_agg(c.lead_name ORDER BY c.created_at DESC))[1] AS lead_name,
    (array_agg(c.persona_name ORDER BY c.created_at DESC))[1] AS persona_name,
    (array_agg(c.persona_slug ORDER BY c.created_at DESC))[1] AS persona_slug,
    (array_agg(coalesce(c.message_origin,'conversation') ORDER BY c.created_at DESC))[1] AS origin,
    min(c.created_at) AS created_at,min(coalesce(c.available_at,c.created_at)) AS available_at,
    CASE
      WHEN bool_or(c.item_state='technical_failure') THEN 'technical_failure'
      WHEN bool_or(c.item_state='blocked') THEN 'blocked'
      WHEN bool_or(c.item_state='preview_ready') THEN 'preview_ready'
      WHEN bool_or(c.item_state='pending') THEN 'pending'
      WHEN bool_or(c.item_state='paused') THEN 'paused'
      WHEN bool_or(c.item_state='pending_response') THEN 'pending_response'
      WHEN bool_or(c.item_state='awaiting_customer') THEN 'awaiting_customer'
      ELSE 'pending' END AS queue_state
  FROM current_buffers c JOIN actionable_keys k USING(persona_id,lead_ref,demand_key)
  GROUP BY c.persona_id,c.lead_ref,c.demand_key
), filtered AS (
  SELECT * FROM demands WHERE (p_origin IS NULL OR p_origin='' OR origin=p_origin)
    AND (p_status IS NULL OR p_status='' OR queue_state=p_status)
), ranked AS (
  SELECT filtered.*,row_number() OVER (PARTITION BY persona_id,lead_ref ORDER BY created_at DESC,id DESC) AS lead_demand_rank
  FROM filtered
), page AS (
  SELECT * FROM ranked WHERE lead_demand_rank<=3
  ORDER BY available_at,created_at,id OFFSET greatest(p_offset,0) LIMIT greatest(least(p_limit,100),1)
), hydrated AS (
  SELECT page.*,
    customer.content AS customer_message,customer.created_at AS customer_message_at,
    agent.content AS last_agent_message,agent.created_at AS last_agent_message_at,
    coalesce(history.messages,'[]'::jsonb) AS recent_context,
    coalesce(outbounds.messages,
      jsonb_build_array(jsonb_build_object('buffer_id',page.id,'sequence',1,'kind','response','text',NULL,'proof_id',NULL,'status',page.queue_state,
        'can_retry',page.queue_state='technical_failure','retry_reason',CASE WHEN page.queue_state='technical_failure' THEN NULL ELSE 'Demanda sem falha técnica recuperável' END,
        'can_send',false,'send_reason','Gere uma resposta válida antes de enviar'))
    ) AS outbound_messages
  FROM page
  LEFT JOIN LATERAL (
    SELECT m.content,m.created_at FROM public.messages m WHERE m.lead_id=page.lead_ref AND m.created_at<=page.created_at
      AND (m.direction='inbound' OR m.role IN ('user','customer')) ORDER BY m.created_at DESC,m.id DESC LIMIT 1
  ) customer ON true
  LEFT JOIN LATERAL (
    SELECT m.content,m.created_at FROM public.messages m WHERE m.lead_id=page.lead_ref AND m.created_at<=page.created_at
      AND (m.direction='outbound' OR m.role IN ('assistant','agent','ai'))
      AND coalesce(m.metadata->>'sender_type','agent') NOT IN ('human','operator','client','customer')
      ORDER BY m.created_at DESC,m.id DESC LIMIT 1
  ) agent ON true
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object('id',recent.id,'content',left(coalesce(recent.content,''),2000),'direction',recent.direction,'role',recent.role,'sender_type',coalesce(recent.metadata->>'sender_type',CASE WHEN recent.direction='outbound' THEN 'agent' ELSE 'client' END),'created_at',recent.created_at) ORDER BY recent.created_at DESC,recent.id DESC) AS messages
    FROM (SELECT m.id,m.content,m.direction,m.role,m.metadata,m.created_at FROM public.messages m WHERE m.lead_id=page.lead_ref AND m.created_at<=page.created_at AND (m.direction IN ('inbound','outbound') OR m.role IN ('user','customer','assistant','agent','ai','human')) ORDER BY m.created_at DESC,m.id DESC LIMIT 6) recent
  ) history ON true
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
      'buffer_id',b.id,'sequence',coalesce(b.queue_sequence,1),
      'kind',coalesce(b.queue_line_kind,'response'),'text',left(coalesce(b.payload->>'text',b.payload->>'caption',''),2000),
      'proof_id',pr.id,'status',b.status,
      'can_retry',((b.queue_group_id IS NOT NULL OR coalesce(b.message_origin,'conversation')='conversation') AND b.status NOT IN ('sent','delivered','read','pending_send','processing','buffered')),
      'retry_reason',CASE WHEN b.status IN ('sent','delivered','read') THEN 'Mensagem já confirmada' WHEN b.status IN ('pending_send','processing','buffered') THEN 'Envio em andamento' WHEN b.queue_group_id IS NULL AND coalesce(b.message_origin,'conversation')<>'conversation' THEN 'Retry individual não se aplica a esta mensagem' ELSE NULL END,
      'can_send',(b.status='preview_ready' AND NOT coalesce((b.payload->>'queue_pause')::boolean,false) AND pr.id IS NOT NULL AND gp.status='active' AND (coalesce(b.queue_sequence,1)=1 OR EXISTS (SELECT 1 FROM current_buffers predecessor WHERE predecessor.persona_id=page.persona_id AND predecessor.lead_ref=page.lead_ref AND predecessor.demand_key=page.demand_key AND predecessor.queue_sequence=1 AND predecessor.status IN ('sent','delivered','read')))),
      'send_reason',CASE WHEN b.status<>'preview_ready' THEN CASE WHEN b.status IN ('sent','delivered','read') THEN 'Mensagem já confirmada' ELSE 'Mensagem não está pronta para envio' END WHEN coalesce((b.payload->>'queue_pause')::boolean,false) THEN 'Mensagem pausada' WHEN pr.id IS NULL OR gp.status IS DISTINCT FROM 'active' THEN 'Proof ou publicação inválida' WHEN b.queue_sequence=2 AND NOT EXISTS (SELECT 1 FROM current_buffers predecessor WHERE predecessor.persona_id=page.persona_id AND predecessor.lead_ref=page.lead_ref AND predecessor.demand_key=page.demand_key AND predecessor.queue_sequence=1 AND predecessor.status IN ('sent','delivered','read')) THEN 'A mensagem 1 ainda não foi confirmada' ELSE NULL END
    ) ORDER BY coalesce(b.queue_sequence,1)) AS messages
    FROM current_buffers b
    LEFT JOIN LATERAL (
      SELECT proof.* FROM public.conversation_turn_proofs proof
       WHERE proof.outbound_id=b.id::text
       ORDER BY proof.created_at DESC LIMIT 1
    ) pr ON true
    LEFT JOIN public.graph_publications gp ON gp.id=pr.publication_id
    WHERE b.persona_id=page.persona_id AND b.lead_ref=page.lead_ref AND b.demand_key=page.demand_key AND b.direction='outbound'
  ) outbounds ON true
)
SELECT jsonb_build_object(
  'items',coalesce((SELECT jsonb_agg(jsonb_build_object(
    'id',id,'demand_id',demand_key,'lead_ref',lead_ref,'lead',jsonb_build_object('nome',lead_name),
    'persona_id',persona_id,'persona',jsonb_build_object('name',persona_name,'slug',persona_slug),
    'origin',origin,'status',queue_state,'queue_state',queue_state,'available_at',available_at,'created_at',created_at,
    'customer_message',customer_message,'customer_message_at',customer_message_at,
    'latest_message',customer_message,'latest_inbound_context',customer_message,
    'last_agent_message',last_agent_message,'last_agent_message_at',last_agent_message_at,
    'recent_context',recent_context,'outbound_messages',outbound_messages,
    'preview_text',outbound_messages->0->>'text','proof_id',outbound_messages->0->>'proof_id',
    'actions',CASE WHEN queue_state='technical_failure' THEN jsonb_build_array('reprocess') WHEN queue_state='preview_ready' THEN jsonb_build_array('send_preview','regenerate_preview') WHEN queue_state='pending' THEN jsonb_build_array('pause') WHEN queue_state='paused' THEN jsonb_build_array('resume') WHEN queue_state='awaiting_customer' THEN jsonb_build_array('reactivate') ELSE '[]'::jsonb END
  ) ORDER BY available_at,created_at,id) FROM hydrated),'[]'::jsonb),
  'next_offset',CASE WHEN (SELECT count(*) FROM ranked WHERE lead_demand_rank<=3)>greatest(p_offset,0)+greatest(least(p_limit,100),1) THEN greatest(p_offset,0)+greatest(least(p_limit,100),1) ELSE NULL END
);
$$;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL,p_origin text DEFAULT NULL,p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0,p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT public.list_actionable_message_queue_v156(p_persona_ids,p_origin,p_status,p_offset,p_limit);
$$;

REVOKE ALL ON FUNCTION public.enqueue_reactivation_line_revision_v1(uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_reactivation_line_revision_v1(uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) TO brain_transport;
REVOKE ALL ON FUNCTION public.enqueue_queue_message_revision_v1(uuid,uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_queue_message_revision_v1(uuid,uuid,jsonb,jsonb,uuid,jsonb,jsonb,jsonb,uuid) TO brain_transport;
REVOKE ALL ON FUNCTION public.control_message_queue_v2(uuid[],text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.control_message_queue_v2(uuid[],text,uuid) TO service_role,brain_control_plane;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v156(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v156(uuid[],text,text,integer,integer) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst,'reload schema';
