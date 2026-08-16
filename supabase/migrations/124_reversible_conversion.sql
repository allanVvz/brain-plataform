-- Conversao reversivel.
--
-- Conversao e venda tinham o mesmo peso na UI: quatro botoes, todos terminais.
-- Mas so a venda envolve dinheiro. Enquanto nao ha conversao registrada em
-- sales_conversions, marcar um lead como convertido e uma leitura do operador,
-- e leitura se corrige. O evento `conversion_reverted` desfaz a conversao e
-- devolve a jornada ao estado anterior.
--
-- Regras:
--
-- 1. `converted` guarda `state_before_conversion` para que o retorno seja ao
--    estado real de onde saiu, e nao a um default adivinhado.
-- 2. Reverter e proibido quando a jornada tem venda (`metadata.sold`). Depois
--    do dinheiro, conversao e fato e nao escolha -- desfazer teria que passar
--    por estorno em sales_conversions, que e outro contrato.
-- 3. `conversion_reverted` nao anexa entrada em `event_idempotency`: ele
--    *remove* a entrada do `converted` que desfez. Sem isso o operador so
--    conseguiria converter uma vez por jornada, e o toggle nao poderia voltar.
--    A idempotencia vem do proprio estado: reverter uma jornada que nao esta
--    convertida e no-op.

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
  v_first boolean:=false; v_conversion_type text; v_previous text;
  v_sale boolean:=p_event_type IN ('sale_recorded','appointment_booked');
  v_closing boolean:=p_event_type IN ('delivered','service_completed','cancelled');
  v_revert boolean:=p_event_type='conversion_reverted';
BEGIN
  IF p_event_type NOT IN ('converted','conversion_reverted','sale_recorded',
                          'appointment_booked','delivered','service_completed',
                          'cancelled') THEN
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
  ELSIF NOT v_revert THEN
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

  IF v_revert THEN
    IF v_journey.state<>'converted' THEN
      RETURN jsonb_build_object('event_type',p_event_type,'journey',to_jsonb(v_journey),
        'deduplicated',true,'new_journey_created',false);
    END IF;
    IF coalesce((v_journey.metadata->>'sold')::boolean,false) THEN
      RAISE EXCEPTION 'conversion backed by a sale cannot be reverted';
    END IF;
    UPDATE public.conversation_journeys SET
      state=coalesce(nullif(metadata->>'state_before_conversion',''),'handed_off'),
      converted_at=NULL,
      metadata=(metadata-'state_before_conversion')
        ||coalesce(p_metadata,'{}'::jsonb)
        ||jsonb_build_object(
          'event_idempotency',coalesce((
            SELECT jsonb_agg(e) FROM jsonb_array_elements(
              coalesce(metadata->'event_idempotency','[]'::jsonb)) e
             WHERE e->>'type' IS DISTINCT FROM 'converted'
          ),'[]'::jsonb),
          'last_conversion_reverted_at',p_occurred_at
        ),
      updated_at=now()
     WHERE id=v_journey.id RETURNING * INTO v_journey;
    RETURN jsonb_build_object(
      'event_type',p_event_type,'journey',to_jsonb(v_journey),
      'deduplicated',false,'new_journey_created',false
    );
  END IF;

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
    -- 'converted': o cliente aceitou. A jornada continua corrente e aberta, e
    -- guarda de onde saiu para poder voltar.
    v_previous:=v_journey.state;
    UPDATE public.conversation_journeys SET
      state=CASE WHEN state='closed' THEN state ELSE 'converted' END,
      converted_at=coalesce(converted_at,p_occurred_at),
      metadata=metadata||coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
        'state_before_conversion',v_previous,
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

REVOKE ALL ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) TO service_role;
