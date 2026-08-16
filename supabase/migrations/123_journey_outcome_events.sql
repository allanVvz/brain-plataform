-- Desfecho comercial da jornada.
--
-- Duas correcoes estruturais, sem tabela nova:
--
-- 1. O evento 'converted' passa a existir. O estado 'converted' ja estava no
--    CHECK de conversation_journeys desde a 118, mas nenhuma funcao o escrevia:
--    era estado morto. Agora o humano registra a conversao explicitamente e a
--    venda tambem avanca a jornada para 'converted'.
--
-- 2. A projecao a partir do proof nunca regride um desfecho comercial. A 122 ja
--    protegia 'converted'/'closed' no ramo de suporte pos-handoff; os demais
--    ramos ainda podiam jogar uma jornada convertida de volta para 'collecting'
--    ou 'handed_off' no proximo inbound. Desfecho registrado por humano e fato,
--    nao inferencia do SDR: o proof continua atualizando metadata, nunca o
--    estado.

CREATE OR REPLACE FUNCTION public.project_conversation_journey_from_proof_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_confirmed boolean:=coalesce((NEW.proof_result->>'explicit_confirmation')::boolean,false);
  v_incomplete boolean:=coalesce((NEW.proof_result->>'qualification_incomplete')::boolean,false);
  v_human boolean:=lower(coalesce(NEW.final_decision->>'route',''))='human';
  v_missing jsonb:=coalesce(NEW.proof_result->'missing_fields','[]'::jsonb);
  v_reason text:=nullif(NEW.final_decision->>'handoff_reason','');
  v_confirmation_state text:=coalesce(NEW.proof_result->>'confirmation_state','');
  v_settled boolean;
BEGIN
  IF NEW.journey_id IS NULL THEN RETURN NEW; END IF;

  -- Desfecho comercial ja registrado: metadata continua evoluindo, estado nao.
  SELECT state IN ('converted','closed') INTO v_settled
    FROM public.conversation_journeys WHERE id=NEW.journey_id;
  IF v_settled IS NULL THEN RETURN NEW; END IF;

  IF v_incomplete AND v_human THEN
    UPDATE public.conversation_journeys SET
      state=CASE WHEN v_settled THEN state ELSE 'handed_off' END,
      handed_off_at=coalesce(handed_off_at,NEW.created_at),
      metadata=metadata||jsonb_build_object(
        'handoff_reason',coalesce(v_reason,'qualification_incomplete'),
        'unconfirmed_fields',v_missing,'last_proof_id',NEW.id
      ),updated_at=now() WHERE id=NEW.journey_id;
    RETURN NEW;
  END IF;
  IF v_confirmation_state IN ('collecting','correction_requested') THEN
    UPDATE public.conversation_journeys SET
      state=CASE WHEN v_settled THEN state ELSE 'collecting' END,
      metadata=metadata||jsonb_build_object(
        'confirmation_state',v_confirmation_state,'last_proof_id',NEW.id
      ),updated_at=now() WHERE id=NEW.journey_id;
    RETURN NEW;
  END IF;
  IF v_confirmation_state='post_qualification_support' THEN
    UPDATE public.conversation_journeys SET
      state=CASE WHEN v_settled THEN state ELSE 'handed_off' END,
      handed_off_at=coalesce(handed_off_at,NEW.created_at),
      metadata=metadata||jsonb_build_object(
        'confirmation_state','post_qualification_support','last_proof_id',NEW.id
      ),updated_at=now() WHERE id=NEW.journey_id;
    RETURN NEW;
  END IF;
  IF jsonb_typeof(v_missing) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_missing)<>0 THEN RETURN NEW; END IF;
  UPDATE public.conversation_journeys SET
    state=CASE WHEN v_settled THEN state
               WHEN v_confirmed AND v_human THEN 'handed_off'
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
  v_first boolean:=false; v_conversion_type text;
  v_sale boolean:=p_event_type IN ('sale_recorded','appointment_booked');
  v_closing boolean:=p_event_type IN ('delivered','service_completed','cancelled');
BEGIN
  IF p_event_type NOT IN ('converted','sale_recorded','appointment_booked',
                          'delivered','service_completed','cancelled') THEN
    RAISE EXCEPTION 'invalid journey event';
  END IF;
  IF btrim(coalesce(p_idempotency_key,''))='' OR btrim(coalesce(p_source,''))='' THEN
    RAISE EXCEPTION 'event identity is required';
  END IF;
  IF p_amount_minor IS NOT NULL AND p_currency IS NULL THEN
    RAISE EXCEPTION 'currency is required with amount';
  END IF;
  IF NOT v_sale AND (p_amount_minor IS NOT NULL
                     OR coalesce(jsonb_array_length(p_items),0)>0) THEN
    RAISE EXCEPTION 'commercial values are only accepted for conversion events';
  END IF;
  IF v_sale THEN
    v_conversion_type:=CASE
      WHEN p_event_type='sale_recorded' THEN 'purchase'
      ELSE 'appointment_booked'
    END;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));

  IF v_sale THEN
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
      IF coalesce((
        SELECT e->>'type' FROM jsonb_array_elements(
          coalesce(v_journey.metadata->'event_idempotency','[]'::jsonb)) e
         WHERE e->>'source'=p_source AND e->>'key'=p_idempotency_key LIMIT 1
      ),p_event_type)<>p_event_type THEN
        RAISE EXCEPTION 'idempotency key belongs to a different journey event';
      END IF;
      RETURN jsonb_build_object('event_type',p_event_type,'journey',to_jsonb(v_journey),
        'deduplicated',true,'new_journey_created',false);
    END IF;
  END IF;

  SELECT * INTO v_journey FROM public.conversation_journeys
   WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'current journey not found' USING ERRCODE='P0002'; END IF;

  IF v_sale THEN
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
    -- A venda tambem converte a jornada: o pedido segue aberto ate entrega,
    -- conclusao ou cancelamento. O marcador `sold` deixa o desfecho legivel a
    -- partir de conversation_journeys apenas, sem um segundo select em
    -- sales_conversions para cada lead da lista.
    UPDATE public.conversation_journeys SET
      state=CASE WHEN state='closed' THEN state ELSE 'converted' END,
      converted_at=coalesce(converted_at,p_occurred_at),
      metadata=metadata||jsonb_build_object(
        'sold',true,
        'last_conversion',jsonb_build_object(
          'type',v_conversion_type,'event',p_event_type,'at',p_occurred_at,
          'conversion_id',v_conversion.id
        )
      ),updated_at=now()
     WHERE id=v_journey.id RETURNING * INTO v_journey;
    RETURN jsonb_build_object(
      'event_type',p_event_type,'conversion',to_jsonb(v_conversion),
      'journey',to_jsonb(v_journey),'deduplicated',false,
      'lead_first_conversion',v_first,'new_journey_created',false
    );
  END IF;

  IF NOT v_closing THEN
    -- 'converted': o cliente aceitou. A jornada continua corrente e aberta.
    UPDATE public.conversation_journeys SET
      state=CASE WHEN state='closed' THEN state ELSE 'converted' END,
      converted_at=coalesce(converted_at,p_occurred_at),
      metadata=metadata||coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
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

REVOKE ALL ON FUNCTION public.project_conversation_journey_from_proof_v1()
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) TO service_role;

-- Depreciacao explicita. As duas funcoes viraram orfas com a 121 e continuam
-- definidas com GRANT para service_role. record_purchase_completed_v1 ainda
-- contem a abertura automatica de jornada que a 121 aboliu: chama-la direto
-- burla o contrato. O COMMENT deixa o aviso visivel em \df+ e no catalogo, sem
-- dropar funcao que possa ter chamador legado em producao.
COMMENT ON FUNCTION public.record_purchase_completed_v1(
  uuid,bigint,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) IS 'DEPRECATED desde a migration 121. Use record_conversation_journey_event_v1. '
   'Esta funcao ainda abre a jornada seguinte na venda, comportamento abolido. '
   'Ver docs/architecture/SDR_JOURNEY_STATE_MACHINE.md.';

COMMENT ON FUNCTION public.mark_conversation_journey_qualification_v1(
  uuid,bigint,boolean,boolean
) IS 'DEPRECATED desde a migration 121. A qualificacao e projetada pelo trigger '
   'project_conversation_journey_from_proof_v1. '
   'Ver docs/architecture/SDR_JOURNEY_STATE_MACHINE.md.';
