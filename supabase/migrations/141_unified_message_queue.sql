-- Unified message queue.  lead_buffer remains the only mutable queue; this
-- migration adds no message table and keeps the existing delivery history.
-- Apply only through the approved migration lifecycle.

ALTER TABLE public.lead_buffer DROP CONSTRAINT IF EXISTS lead_buffer_message_origin_check;
ALTER TABLE public.lead_buffer ADD CONSTRAINT lead_buffer_message_origin_check
  CHECK (message_origin IN ('conversation', 'campaign', 'manual', 'proactive', 'system'));
ALTER TABLE public.messages DROP CONSTRAINT IF EXISTS messages_message_origin_check;
ALTER TABLE public.messages ADD CONSTRAINT messages_message_origin_check
  CHECK (message_origin IN ('conversation', 'campaign', 'manual', 'proactive', 'system'));

CREATE INDEX IF NOT EXISTS idx_lead_buffer_queue_persona_created
  ON public.lead_buffer(persona_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_buffer_queue_lead_created
  ON public.lead_buffer(lead_ref, created_at DESC);

-- The action is deliberately per buffer identity.  It cannot replay an
-- accepted outbound or a completed canonical inbound turn.  Every requested
-- id yields an auditable result instead of failing the whole selected batch.
CREATE OR REPLACE FUNCTION public.control_message_queue_v1(
  p_buffer_ids uuid[], p_action text, p_reason text, p_idempotency_key text,
  p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE; v_results jsonb := '[]'::jsonb;
  v_result text; v_reason text; v_target timestamptz; v_previous_status text;
BEGIN
  IF p_action NOT IN ('pause','resume','reprocess') THEN
    RAISE EXCEPTION 'unsupported queue action' USING ERRCODE='22023';
  END IF;
  IF coalesce(array_length(p_buffer_ids,1),0)=0 OR nullif(btrim(p_reason),'') IS NULL
     OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
    RAISE EXCEPTION 'buffer ids, reason and idempotency key are required' USING ERRCODE='22023';
  END IF;
  FOR v_row IN SELECT * FROM public.lead_buffer WHERE id = ANY(p_buffer_ids) FOR UPDATE LOOP
    v_result := NULL; v_reason := NULL; v_target := NULL; v_previous_status := v_row.status;
    IF EXISTS (SELECT 1 FROM public.system_events e WHERE e.event_type='messaging.queue.'||p_action
      AND e.entity_id=v_row.id::text AND e.payload->>'idempotency_key'=p_idempotency_key) THEN
      v_result := 'superado'; v_reason := 'acao_idempotente_ja_registrada';
    ELSIF p_action='pause' THEN
      IF v_row.status IN ('sent','delivered','read','dead_letter','ignored') THEN
        v_result := 'bloqueado'; v_reason := 'entrega_ou_estado_terminal';
      ELSE
        v_target := now()+interval '10 years';
        UPDATE public.lead_buffer SET status='buffered', available_at=v_target,
          payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_pause',true,'queue_pause_reason',p_reason),
          updated_at=now() WHERE id=v_row.id;
        v_result := 'pausado';
      END IF;
    ELSIF p_action='resume' THEN
      IF NOT coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
        v_result := 'superado'; v_reason := 'item_nao_esta_pausado_pela_fila';
      ELSIF v_row.status IN ('sent','delivered','read','dead_letter','ignored') THEN
        v_result := 'bloqueado'; v_reason := 'entrega_ou_estado_terminal';
      ELSE
        v_target := public.next_business_hours_slot(now(),0,1,'08:00','20:00','America/Sao_Paulo');
        UPDATE public.lead_buffer SET status='buffered', available_at=v_target,
          payload=coalesce(payload,'{}'::jsonb)-'queue_pause'-'queue_pause_reason', updated_at=now() WHERE id=v_row.id;
        v_result := 'agendado';
      END IF;
    ELSE
      IF v_row.direction <> 'inbound' THEN
        v_result := 'bloqueado'; v_reason := 'somente_inbound_pode_ser_reprocessado';
      ELSIF v_row.status IN ('sent','delivered','read','dead_letter','ignored','processing','waiting_human') THEN
        v_result := 'bloqueado'; v_reason := 'estado_nao_elegivel';
      ELSIF coalesce(v_row.payload->'conversation_commit'->>'status','')='completed'
        OR EXISTS (SELECT 1 FROM public.conversation_turn_proofs p WHERE p.canonical_inbound_id=v_row.id::text) THEN
        v_result := 'superado'; v_reason := 'turno_canonico_ja_concluido';
      ELSE
        v_target := public.next_business_hours_slot(now(),0,1,'08:00','20:00','America/Sao_Paulo');
        UPDATE public.lead_buffer SET status='retry', available_at=v_target, locked_at=NULL, locked_by=NULL,
          last_error=NULL, payload=coalesce(payload,'{}'::jsonb)-'queue_pause'-'queue_pause_reason', updated_at=now()
          WHERE id=v_row.id;
        v_result := 'reprocessado';
      END IF;
    END IF;
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.'||p_action,'lead_buffer',v_row.id::text,v_row.persona_id,
      jsonb_build_object('result',v_result,'reason',v_reason,'operator_reason',p_reason,
        'idempotency_key',p_idempotency_key,'actor_user_id',p_actor_user_id,
        'previous_status',v_previous_status,'scheduled_for',v_target),'info','messaging.queue');
    v_results := v_results || jsonb_build_array(jsonb_build_object(
      'buffer_id',v_row.id,'result',v_result,'reason',v_reason,
      'previous_status',v_previous_status,'scheduled_for',v_target
    ));
  END LOOP;
  RETURN jsonb_build_object('items',v_results);
END; $$;

REVOKE ALL ON FUNCTION public.control_message_queue_v1(uuid[],text,text,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.control_message_queue_v1(uuid[],text,text,text,uuid) TO service_role,brain_control_plane;

-- Proactive notices are not retries of an inbound.  They use an independent
-- canonical identity in the existing proof ledger, tied to the precise
-- outbound buffer and graph publication.  No additional mutable queue or
-- proof table is introduced.
CREATE OR REPLACE FUNCTION public.commit_proactive_queue_proof_v1(
  p_buffer_id uuid,
  p_publication_id uuid,
  p_evidence_node_ids jsonb,
  p_proof_result jsonb DEFAULT '{}'::jsonb,
  p_model_proposal jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_canonical_id text := 'proactive:' || p_buffer_id::text;
  v_proof public.conversation_turn_proofs%ROWTYPE;
BEGIN
  SELECT * INTO v_buffer FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'queue buffer not found' USING ERRCODE='P0002'; END IF;
  IF v_buffer.direction <> 'outbound' OR v_buffer.message_origin <> 'proactive' THEN
    RAISE EXCEPTION 'proactive proof requires an outbound proactive buffer' USING ERRCODE='23514';
  END IF;
  IF v_buffer.status IN ('sent','delivered','read','dead_letter','ignored') THEN
    RAISE EXCEPTION 'cannot attach or replay proactive proof after terminal delivery state' USING ERRCODE='23514';
  END IF;
  IF jsonb_typeof(p_evidence_node_ids) <> 'array' OR jsonb_array_length(p_evidence_node_ids)=0 THEN
    RAISE EXCEPTION 'proactive proof requires published evidence nodes' USING ERRCODE='23514';
  END IF;
  IF NOT coalesce((p_proof_result->>'delivery_authorized')::boolean,
                  (p_proof_result->>'valid')::boolean,false) THEN
    RAISE EXCEPTION 'proactive delivery is not authorized by proof' USING ERRCODE='23514';
  END IF;
  SELECT * INTO v_proof FROM public.conversation_turn_proofs
   WHERE canonical_inbound_id=v_canonical_id FOR UPDATE;
  IF FOUND THEN
    IF v_proof.outbound_id <> p_buffer_id::text THEN
      RAISE EXCEPTION 'proactive proof identity conflict' USING ERRCODE='23505';
    END IF;
    RETURN jsonb_build_object('state','completed','deduplicated',true,'proof_id',v_proof.id,'outbound_buffer_id',p_buffer_id);
  END IF;
  INSERT INTO public.conversation_turn_proofs(
    canonical_inbound_id, publication_id, retrieval_trace, model_proposal,
    proof_result, final_decision, outbound_id
  ) VALUES (
    v_canonical_id, p_publication_id,
    jsonb_build_object('evidence_node_ids',p_evidence_node_ids,'queue_origin','proactive'),
    coalesce(p_model_proposal,'{}'::jsonb),
    coalesce(p_proof_result,'{}'::jsonb),
    jsonb_build_object('kind','proactive','buffer_id',p_buffer_id), p_buffer_id::text
  ) RETURNING * INTO v_proof;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.proactive_proof','lead_buffer',p_buffer_id::text,v_buffer.persona_id,
    jsonb_build_object('proof_id',v_proof.id,'publication_id',p_publication_id,
      'evidence_node_ids',p_evidence_node_ids),'info','messaging.queue');
  RETURN jsonb_build_object('state','completed','deduplicated',false,'proof_id',v_proof.id,'outbound_buffer_id',p_buffer_id);
END; $$;

REVOKE ALL ON FUNCTION public.commit_proactive_queue_proof_v1(uuid,uuid,jsonb,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.commit_proactive_queue_proof_v1(uuid,uuid,jsonb,jsonb,jsonb)
  TO service_role,brain_runtime;
NOTIFY pgrst, 'reload schema';
