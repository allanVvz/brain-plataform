-- Actionable message queue: previews and safe recovery stay in lead_buffer.
-- No conversation history or new table is introduced.

ALTER TABLE public.lead_buffer DROP CONSTRAINT IF EXISTS lead_buffer_status_check;
ALTER TABLE public.lead_buffer ADD CONSTRAINT lead_buffer_status_check CHECK (status IN (
  'received','buffered','processing','awaiting_proof','preview_ready','pending_send',
  'sent','delivered','read','failed','retry','dead_letter','waiting_human','ignored'
));

CREATE INDEX IF NOT EXISTS idx_lead_buffer_actionable_projection
  ON public.lead_buffer (persona_id, lead_ref, channel_binding_id, direction, created_at);

-- A preview is inert until the operator changes it to pending_send.  At that
-- transition it follows the exact same published schedule as a proof release.
CREATE OR REPLACE FUNCTION public.apply_published_outbound_schedule_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE v_available_at timestamptz; v_checksum text;
BEGIN
  IF NEW.direction <> 'outbound'
     OR OLD.status NOT IN ('awaiting_proof','preview_ready')
     OR NEW.status <> 'pending_send' THEN
    RETURN NEW;
  END IF;
  v_checksum := nullif(NEW.payload->'published_business_hours'->>'graph_checksum','');
  BEGIN
    v_available_at := (NEW.payload->>'available_at')::timestamptz;
  EXCEPTION WHEN OTHERS THEN
    v_available_at := NULL;
  END;
  IF v_checksum IS NULL OR v_available_at IS NULL THEN
    RAISE EXCEPTION 'published outbound schedule is incomplete' USING ERRCODE='22023';
  END IF;
  NEW.available_at := v_available_at;
  NEW.status := CASE WHEN v_available_at > now() THEN 'buffered' ELSE 'pending_send' END;
  RETURN NEW;
END;
$$;

-- Claims a technical failure for one operator-requested preview.  The claim
-- never accepts a provider delivery and it rejects any inbound that already
-- spent its canonical turn.
CREATE OR REPLACE FUNCTION public.claim_queue_preview_v1(
  p_buffer_id uuid, p_actor_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.lead_buffer%ROWTYPE;
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
  UPDATE public.leads SET ai_paused=false, updated_at=now()
   WHERE id=v_row.lead_ref AND ai_paused=true;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
  VALUES ('messaging.queue.preview_claimed','lead_buffer',v_row.id::text,v_row.persona_id,
    jsonb_build_object('actor_user_id',p_actor_user_id),'info','messaging.queue');
  RETURN jsonb_build_object('buffer_id',v_row.id,'lead_ref',v_row.lead_ref,
    'persona_id',v_row.persona_id,'channel_binding_id',v_row.channel_binding_id,
    'correlation_id',v_row.correlation_id,'text',coalesce(v_row.payload->>'text',''));
END; $$;

CREATE OR REPLACE FUNCTION public.release_queue_preview_claim_v1(
  p_buffer_id uuid, p_error text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.lead_buffer%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM public.lead_buffer WHERE id=p_buffer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'queue item not found' USING ERRCODE='23514'; END IF;
  IF v_row.status='processing' AND coalesce(v_row.payload->>'queue_preview_claim','')='true' THEN
    UPDATE public.lead_buffer SET status='waiting_human', locked_at=NULL, locked_by=NULL,
      last_error=left(coalesce(p_error,'preview generation failed'),1000),
      payload=coalesce(payload,'{}'::jsonb)-'queue_preview_claim', updated_at=now()
    WHERE id=v_row.id;
  END IF;
  RETURN jsonb_build_object('buffer_id',v_row.id,'status',v_row.status);
END; $$;

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
    RAISE EXCEPTION 'unsupported queue action' USING ERRCODE='22023';
  END IF;
  IF coalesce(array_length(p_buffer_ids,1),0)=0 THEN
    RAISE EXCEPTION 'buffer ids are required' USING ERRCODE='22023';
  END IF;
  FOR v_row IN SELECT * FROM public.lead_buffer WHERE id=ANY(p_buffer_ids) FOR UPDATE LOOP
    v_result:=NULL; v_reason:=NULL; v_target:=NULL; v_previous:=v_row.status;
    IF p_action='pause' THEN
      IF v_row.status IN ('sent','delivered','read','dead_letter','ignored') THEN
        v_result:='bloqueado'; v_reason:='entrega_ou_estado_terminal';
      ELSIF v_row.status='preview_ready' THEN
        UPDATE public.lead_buffer SET payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_pause',true), updated_at=now() WHERE id=v_row.id;
        v_result:='pausado';
      ELSE
        v_target:=now()+interval '10 years';
        UPDATE public.lead_buffer SET status='buffered', available_at=v_target,
          payload=coalesce(payload,'{}'::jsonb)||jsonb_build_object('queue_pause',true), updated_at=now() WHERE id=v_row.id;
        v_result:='pausado';
      END IF;
    ELSIF p_action='resume' THEN
      IF NOT coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
        v_result:='superado'; v_reason:='item_nao_esta_pausado_pela_fila';
      ELSIF v_row.status IN ('sent','delivered','read','dead_letter','ignored') THEN
        v_result:='bloqueado'; v_reason:='entrega_ou_estado_terminal';
      ELSIF v_row.status='preview_ready' THEN
        UPDATE public.lead_buffer SET payload=coalesce(payload,'{}'::jsonb)-'queue_pause', updated_at=now() WHERE id=v_row.id;
        v_result:='retomado';
      ELSE
        v_hours:=v_row.payload->'published_business_hours';
        BEGIN
          v_start:=(v_hours->>'start')::time;
          v_end:=(v_hours->>'end')::time;
          v_tz:=nullif(v_hours->>'timezone','');
          IF v_start>=v_end OR v_tz IS NULL THEN RAISE EXCEPTION 'invalid published delivery policy'; END IF;
          v_target:=public.next_business_hours_slot(now(),0,1,v_start,v_end,v_tz);
        EXCEPTION WHEN OTHERS THEN
          v_target:=NULL; v_reason:='politica_publicada_indisponivel';
        END;
        IF v_target IS NULL THEN
          v_result:='bloqueado';
        ELSE
          UPDATE public.lead_buffer SET status='buffered', available_at=v_target,
            payload=coalesce(payload,'{}'::jsonb)-'queue_pause', updated_at=now() WHERE id=v_row.id;
          v_result:='agendado';
        END IF;
      END IF;
    ELSE
      IF v_row.direction<>'outbound' OR v_row.status<>'preview_ready' THEN
        v_result:='bloqueado'; v_reason:='preview_nao_encontrado';
      ELSIF coalesce((v_row.payload->>'queue_pause')::boolean,false) THEN
        v_result:='bloqueado'; v_reason:='preview_pausado';
      ELSIF EXISTS (SELECT 1 FROM public.lead_buffer i WHERE i.direction='inbound'
          AND i.lead_ref=v_row.lead_ref AND i.created_at>v_row.created_at) THEN
        v_result:='superado'; v_reason:='nova_mensagem_da_lead';
      ELSE
        UPDATE public.lead_buffer SET status='pending_send', updated_at=now() WHERE id=v_row.id;
        SELECT available_at INTO v_target FROM public.lead_buffer WHERE id=v_row.id;
        v_result:='agendado';
      END IF;
    END IF;
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('messaging.queue.'||p_action,'lead_buffer',v_row.id::text,v_row.persona_id,
      jsonb_build_object('result',v_result,'reason',v_reason,'actor_user_id',p_actor_user_id,
        'previous_status',v_previous,'scheduled_for',v_target),'info','messaging.queue');
    v_results:=v_results||jsonb_build_array(jsonb_build_object('buffer_id',v_row.id,
      'result',v_result,'reason',v_reason,'previous_status',v_previous,'scheduled_for',v_target));
  END LOOP;
  RETURN jsonb_build_object('items',v_results);
END; $$;

-- The dashboard is an operational projection, not a paginated history scan.
-- Calculate it in Postgres so a large old transcript cannot hide a currently
-- actionable FIFO item after an arbitrary client-side fetch cap.
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
          ELSE '[]'::jsonb
        END
      )) FROM page
    ),'[]'::jsonb),
    'next_offset', CASE WHEN (SELECT count(*) FROM filtered)>greatest(p_offset,0)+greatest(least(p_limit,100),1)
      THEN greatest(p_offset,0)+greatest(least(p_limit,100),1) ELSE NULL END
  );
$$;

-- The existing atomic turn commit is deliberately proof-gated.  A generated
-- preview has that same validated proof, but it must remain inert until an
-- operator explicitly sends it.  Extend only the status guard; the envelope,
-- uniqueness and proof checks in the established commit function stay intact.
DO $$
DECLARE
  v_definition text;
  v_pattern text := E'p_outbound_buffer\\s*->>\\s*''status''\\s*<>\\s*''awaiting_proof''';
  v_new text := 'p_outbound_buffer->>''status'' NOT IN (''awaiting_proof'',''preview_ready'')';
BEGIN
  SELECT pg_get_functiondef(p.oid) INTO v_definition
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='public'
     AND p.proname='commit_graph_turn_and_outbox_v4';
  IF v_definition IS NULL OR v_definition !~ v_pattern THEN
    RAISE EXCEPTION 'commit_graph_turn_and_outbox_v4 proof guard was not found';
  END IF;
  EXECUTE regexp_replace(v_definition,v_pattern,v_new,'g');
END $$;

REVOKE ALL ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.release_queue_preview_claim_v1(uuid,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.control_message_queue_v2(uuid[],text,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_queue_preview_v1(uuid,uuid) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.release_queue_preview_claim_v1(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_queue_preview_claim_v1(uuid,text) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.control_message_queue_v2(uuid[],text,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.control_message_queue_v2(uuid[],text,uuid) TO brain_control_plane;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO brain_control_plane;

NOTIFY pgrst, 'reload schema';
