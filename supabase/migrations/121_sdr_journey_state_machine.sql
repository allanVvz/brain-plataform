-- Structural SDR state machine. Reuses conversation_journeys,
-- sales_conversions and metadata; no new table is introduced.
-- Production application remains a separately authorized operation.

CREATE OR REPLACE FUNCTION public.graph_turn_context_batch_v3(
  p_persona_id uuid,p_lead_ref bigint,p_message_limit integer DEFAULT 8
)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp
AS $$
  WITH journey AS (
    SELECT * FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current
     LIMIT 1
  ), publication AS (
    SELECT * FROM public.graph_publications
     WHERE persona_id=p_persona_id AND status='active' LIMIT 1
  ), ledger AS (
    SELECT l.* FROM public.conversation_ledgers l JOIN journey j ON j.id=l.journey_id
     WHERE l.persona_id=p_persona_id AND l.lead_ref=p_lead_ref LIMIT 1
  ), facts AS (
    SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.field_key,f.revision),'[]'::jsonb) value
      FROM public.conversation_facts f JOIN ledger l ON l.id=f.ledger_id WHERE f.is_current
  ), branches AS (
    SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.added_at),'[]'::jsonb) value
      FROM public.conversation_ledger_branches b JOIN ledger l ON l.id=b.ledger_id
     WHERE b.state='active'
  ), messages AS (
    SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.created_at,m.id),'[]'::jsonb) value FROM (
      SELECT id,lead_id,role,content,direction,external_message_id,created_at
        FROM public.messages WHERE lead_id=p_lead_ref
       ORDER BY created_at DESC,id DESC LIMIT greatest(1,least(coalesce(p_message_limit,8),20))
    ) m
  ) SELECT jsonb_build_object(
    'journey',(SELECT to_jsonb(journey) FROM journey),
    'publication',(SELECT to_jsonb(publication) FROM publication),
    'ledger',(SELECT to_jsonb(ledger) FROM ledger),
    'facts',(SELECT value FROM facts),'branches',(SELECT value FROM branches),
    'messages',(SELECT value FROM messages));
$$;

CREATE OR REPLACE FUNCTION public.maybe_open_next_conversation_journey_v1(
  p_journey_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_origin public.conversation_journeys%ROWTYPE;
BEGIN
  SELECT * INTO v_origin FROM public.conversation_journeys WHERE id=p_journey_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'journey not found' USING ERRCODE='P0002'; END IF;
  -- Qualification, sale and booking are outcomes of the current request.
  -- A following journey is born only from a later inbound after this request
  -- was explicitly closed by delivery, completion or cancellation.
  RETURN jsonb_build_object(
    'new_journey_created',false,'origin_journey',to_jsonb(v_origin),
    'reason','current_request_remains_open'
  );
END $$;

CREATE OR REPLACE FUNCTION public.assign_conversation_ledger_journey_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE v_journey public.conversation_journeys%ROWTYPE; v_reason text;
BEGIN
  IF NEW.journey_id IS NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.persona_id::text||':'||NEW.lead_ref::text,0));
    SELECT * INTO v_journey FROM public.conversation_journeys
     WHERE persona_id=NEW.persona_id AND lead_ref=NEW.lead_ref AND is_current FOR UPDATE;
    IF NOT FOUND THEN
      v_reason:=CASE WHEN EXISTS (
        SELECT 1 FROM public.conversation_journeys
         WHERE persona_id=NEW.persona_id AND lead_ref=NEW.lead_ref
      ) THEN 'new_demand_after_closed_request' ELSE 'initial' END;
      INSERT INTO public.conversation_journeys(
        persona_id,lead_ref,sequence,previous_journey_id,publication_id,
        graph_checksum,opening_reason
      ) SELECT NEW.persona_id,NEW.lead_ref,coalesce(max(sequence),0)+1,
               (array_agg(id ORDER BY sequence DESC))[1],NEW.publication_id,
               NEW.graph_checksum,v_reason
          FROM public.conversation_journeys
         WHERE persona_id=NEW.persona_id AND lead_ref=NEW.lead_ref
      RETURNING * INTO v_journey;
    END IF;
    NEW.journey_id:=v_journey.id;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.project_conversation_journey_from_proof_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_confirmed boolean:=coalesce((NEW.proof_result->>'explicit_confirmation')::boolean,false);
  v_incomplete boolean:=coalesce((NEW.proof_result->>'qualification_incomplete')::boolean,false);
  v_human boolean:=lower(coalesce(NEW.final_decision->>'route',''))='human';
  v_missing jsonb:=coalesce(NEW.proof_result->'missing_fields','[]'::jsonb);
  v_reason text:=nullif(NEW.final_decision->>'handoff_reason','');
  v_confirmation_state text:=coalesce(NEW.proof_result->>'confirmation_state','');
BEGIN
  IF NEW.journey_id IS NULL THEN RETURN NEW; END IF;
  IF v_incomplete AND v_human THEN
    UPDATE public.conversation_journeys SET
      state='handed_off',handed_off_at=coalesce(handed_off_at,NEW.created_at),
      metadata=metadata||jsonb_build_object(
        'handoff_reason',coalesce(v_reason,'qualification_incomplete'),
        'unconfirmed_fields',v_missing,'last_proof_id',NEW.id
      ),updated_at=now() WHERE id=NEW.journey_id;
    RETURN NEW;
  END IF;
  IF v_confirmation_state IN ('collecting','correction_requested') THEN
    UPDATE public.conversation_journeys SET
      state='collecting',metadata=metadata||jsonb_build_object(
        'confirmation_state',v_confirmation_state,'last_proof_id',NEW.id
      ),updated_at=now() WHERE id=NEW.journey_id;
    RETURN NEW;
  END IF;
  IF jsonb_typeof(v_missing) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_missing)<>0 THEN RETURN NEW; END IF;
  UPDATE public.conversation_journeys SET
    state=CASE WHEN v_confirmed AND v_human THEN 'handed_off'
               WHEN v_confirmed THEN 'qualified_confirmed'
               ELSE 'awaiting_confirmation' END,
    qualification_completed_at=coalesce(qualification_completed_at,NEW.created_at),
    qualification_confirmed_at=CASE WHEN v_confirmed THEN coalesce(qualification_confirmed_at,NEW.created_at) ELSE qualification_confirmed_at END,
    handed_off_at=CASE WHEN v_confirmed AND v_human THEN coalesce(handed_off_at,NEW.created_at) ELSE handed_off_at END,
    metadata=metadata||jsonb_build_object(
      'last_proof_id',NEW.id,
      'confirmation_state',CASE WHEN v_confirmed THEN 'confirmed' ELSE 'awaiting_confirmation' END
    )||CASE WHEN v_confirmed AND v_human THEN jsonb_build_object(
      'handoff_reason',coalesce(v_reason,'qualification_confirmed')
    ) ELSE '{}'::jsonb END,
    updated_at=now()
   WHERE id=NEW.journey_id;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.record_conversation_journey_event_v1(
  p_persona_id uuid,p_lead_ref bigint,p_event_type text,p_idempotency_key text,
  p_source text,p_occurred_at timestamptz,p_external_ref text DEFAULT NULL,
  p_amount_minor bigint DEFAULT NULL,p_currency text DEFAULT NULL,
  p_items jsonb DEFAULT '[]'::jsonb,p_metadata jsonb DEFAULT '{}'::jsonb,
  p_responsible_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_journey public.conversation_journeys%ROWTYPE;
  v_conversion public.sales_conversions%ROWTYPE;
  v_existing boolean:=false; v_first boolean:=false; v_conversion_type text;
BEGIN
  IF p_event_type NOT IN ('sale_recorded','appointment_booked','delivered','service_completed','cancelled') THEN
    RAISE EXCEPTION 'invalid journey event';
  END IF;
  IF btrim(coalesce(p_idempotency_key,''))='' OR btrim(coalesce(p_source,''))='' THEN
    RAISE EXCEPTION 'event identity is required';
  END IF;
  IF p_amount_minor IS NOT NULL AND p_currency IS NULL THEN
    RAISE EXCEPTION 'currency is required with amount';
  END IF;
  IF p_event_type IN ('sale_recorded','appointment_booked') THEN
    v_conversion_type:=CASE
      WHEN p_event_type='sale_recorded' THEN 'purchase'
      ELSE 'appointment_booked'
    END;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));

  IF p_event_type IN ('sale_recorded','appointment_booked') THEN
    SELECT * INTO v_conversion FROM public.sales_conversions
     WHERE persona_id=p_persona_id AND source=p_source
       AND idempotency_key=p_idempotency_key FOR UPDATE;
    IF FOUND THEN
      IF v_conversion.lead_ref<>p_lead_ref
         OR v_conversion.conversion_type<>v_conversion_type THEN
        RAISE EXCEPTION 'idempotency key belongs to a different journey event';
      END IF;
      RETURN jsonb_build_object(
        'event_type',p_event_type,'conversion',to_jsonb(v_conversion),
        'deduplicated',true,'lead_first_conversion',
        coalesce((v_conversion.metadata->>'lead_first_conversion')::boolean,false),
        'new_journey_created',false
      );
    END IF;
  ELSE
    SELECT * INTO v_journey FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref
       AND EXISTS (
         SELECT 1 FROM jsonb_array_elements(coalesce(metadata->'event_idempotency','[]'::jsonb)) e
          WHERE e->>'source'=p_source AND e->>'key'=p_idempotency_key
       ) ORDER BY sequence DESC LIMIT 1;
    IF FOUND THEN
      RETURN jsonb_build_object('event_type',p_event_type,'journey',to_jsonb(v_journey),
        'deduplicated',true,'new_journey_created',false);
    END IF;
  END IF;

  SELECT * INTO v_journey FROM public.conversation_journeys
   WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'current journey not found' USING ERRCODE='P0002'; END IF;

  IF p_event_type IN ('sale_recorded','appointment_booked') THEN
    v_first:=NOT EXISTS (
      SELECT 1 FROM public.sales_conversions
       WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND completed_at IS NOT NULL
    );
    INSERT INTO public.sales_conversions(
      persona_id,lead_ref,journey_id,conversion_type,status,amount_minor,currency,
      items,source,idempotency_key,external_ref,metadata,occurred_at,completed_at,
      responsible_user_id,transition_history,idempotency_history
    ) VALUES (
      p_persona_id,p_lead_ref,v_journey.id,v_conversion_type,'completed',
      p_amount_minor,upper(p_currency),coalesce(p_items,'[]'::jsonb),p_source,
      p_idempotency_key,p_external_ref,coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
        'lead_first_conversion',v_first,'recurrence',NOT v_first
      ),p_occurred_at,p_occurred_at,p_responsible_user_id,
      jsonb_build_array(jsonb_build_object('status','completed','at',now())),
      jsonb_build_array(jsonb_build_object('source',p_source,'key',p_idempotency_key,'at',now()))
    ) RETURNING * INTO v_conversion;
    UPDATE public.conversation_journeys SET
      converted_at=coalesce(converted_at,p_occurred_at),updated_at=now()
     WHERE id=v_journey.id;
    RETURN jsonb_build_object(
      'event_type',p_event_type,'conversion',to_jsonb(v_conversion),
      'journey',to_jsonb(v_journey),'deduplicated',false,
      'lead_first_conversion',v_first,'new_journey_created',false
    );
  END IF;

  UPDATE public.conversation_journeys SET
    is_current=false,state='closed',closed_at=coalesce(closed_at,p_occurred_at),
    metadata=metadata||coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
      'closing_event',p_event_type,
      'event_idempotency',coalesce(metadata->'event_idempotency','[]'::jsonb)
        ||jsonb_build_array(jsonb_build_object(
          'source',p_source,'key',p_idempotency_key,'type',p_event_type,'at',p_occurred_at
        ))
    ),updated_at=now()
   WHERE id=v_journey.id RETURNING * INTO v_journey;
  RETURN jsonb_build_object(
    'event_type',p_event_type,'journey',to_jsonb(v_journey),
    'deduplicated',false,'new_journey_created',false
  );
END $$;

CREATE OR REPLACE FUNCTION public.repair_conversation_ledger_branch_v1(
  p_ledger_id uuid,p_expected_revision bigint,p_apply boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_ledger public.conversation_ledgers%ROWTYPE; v_service boolean;
BEGIN
  SELECT * INTO v_ledger FROM public.conversation_ledgers WHERE id=p_ledger_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger not found' USING ERRCODE='P0002'; END IF;
  IF v_ledger.revision<>p_expected_revision THEN RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001'; END IF;
  SELECT EXISTS (
    SELECT 1 FROM public.conversation_facts f
      JOIN public.graph_publications p ON p.id=v_ledger.publication_id
     WHERE f.ledger_id=v_ledger.id AND f.is_current AND f.field_key='servico'
       AND f.status='known' AND f.owner_node_id=v_ledger.active_branch_node_id
       AND lower(coalesce(f.value_json#>>'{}','')) IN (
         lower(v_ledger.active_branch_node_id),
         lower(coalesce(p.document_json->'node_by_id'->v_ledger.active_branch_node_id->>'slug','')),
         lower(coalesce(p.document_json->'node_by_id'->v_ledger.active_branch_node_id->>'title',''))
       )
  ) INTO v_service;
  IF v_ledger.active_branch_node_id IS NULL OR v_service THEN
    RETURN jsonb_build_object('changed',false,'apply',p_apply,'ledger_id',v_ledger.id,
      'revision',v_ledger.revision,'reason','consistent');
  END IF;
  IF NOT p_apply THEN
    RETURN jsonb_build_object('changed',false,'apply',false,'ledger_id',v_ledger.id,
      'revision',v_ledger.revision,'reason','active_branch_without_referential_service',
      'proposed_action','clear_active_branch_only');
  END IF;
  UPDATE public.conversation_ledgers SET active_branch_node_id=NULL,revision=revision+1,
    updated_at=now() WHERE id=v_ledger.id AND revision=p_expected_revision;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001'; END IF;
  UPDATE public.conversation_ledger_branches SET state='dropped',completed_at=now()
   WHERE ledger_id=v_ledger.id AND state='active';
  RETURN jsonb_build_object('changed',true,'apply',true,'ledger_id',v_ledger.id,
    'previous_revision',p_expected_revision,'revision',p_expected_revision+1,
    'reason','active_branch_without_referential_service');
END $$;

REVOKE ALL ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.assign_conversation_ledger_journey_v1() FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.project_conversation_journey_from_proof_v1() FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.record_conversation_journey_event_v1(uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.repair_conversation_ledger_branch_v1(uuid,bigint,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_conversation_journey_event_v1(uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.repair_conversation_ledger_branch_v1(uuid,bigint,boolean) TO service_role;
