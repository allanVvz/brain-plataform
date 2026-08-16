-- Cancelar estorna a compra, nao a conversao.
--
-- Ate aqui `cancelled` fechava a jornada e nada mais: a linha em
-- sales_conversions continuava `status='completed'` com `completed_at`
-- preenchido e `metadata.sold` seguia true. A tela mostrava "cancelado" pelo
-- desempate do terminal, mas a receita continuava contada no banco. Tela e
-- ledger discordavam.
--
-- Agora o cancelamento:
--
-- 1. transiciona para 'cancelled' toda conversao ainda completed da jornada
--    corrente, com carimbo e historico -- o mesmo contrato de
--    transition_sales_conversion_status_v1, aplicado em lote;
-- 2. remove `sold` e `last_conversion` da jornada, para o controle de venda
--    voltar a ficar desligado;
-- 3. **preserva `converted_at`**. Depois do primeiro agendamento ou compra o
--    lead esta convertido, e cancelar o pedido nao desfaz isso. Conversao e
--    fato do lead; venda e fato do pedido.

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
  v_reversed int:=0;
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
      -- Uma venda cancelada e depois relancada com a mesma chave nao pode
      -- ressuscitar em silencio: a chave ja foi gasta.
      IF v_conversion.status='cancelled' THEN
        RAISE EXCEPTION 'idempotency key belongs to a cancelled conversion';
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
       WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref
         AND completed_at IS NOT NULL AND status<>'cancelled'
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

  IF p_event_type='cancelled' THEN
    WITH estornadas AS (
      UPDATE public.sales_conversions SET
        status='cancelled',
        cancelled_at=coalesce(cancelled_at,p_occurred_at),
        transition_history=transition_history||jsonb_build_array(jsonb_build_object(
          'from',status,'to','cancelled','at',now(),'reason','journey_cancelled'
        )),
        metadata=metadata||jsonb_build_object('cancelled_by_journey_event',true),
        updated_at=now()
       WHERE journey_id=v_journey.id AND status='completed'
      RETURNING 1
    ) SELECT count(*) INTO v_reversed FROM estornadas;
  END IF;

  UPDATE public.conversation_journeys SET
    is_current=false,state='closed',closed_at=coalesce(closed_at,p_occurred_at),
    -- `converted_at` fica: depois do primeiro agendamento ou compra o lead
    -- esta convertido, e cancelar o pedido nao desfaz isso.
    metadata=CASE WHEN p_event_type='cancelled'
      THEN (metadata-'sold'-'last_conversion') ELSE metadata END
      ||coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
      'closing_event',p_event_type,
      'reversed_conversions',v_reversed,
      'event_idempotency',coalesce(metadata->'event_idempotency','[]'::jsonb)
        ||jsonb_build_array(jsonb_build_object(
          'source',p_source,'key',p_idempotency_key,'type',p_event_type,'at',p_occurred_at
        ))
    ),updated_at=now()
   WHERE id=v_journey.id RETURNING * INTO v_journey;
  RETURN jsonb_build_object(
    'event_type',p_event_type,'journey',to_jsonb(v_journey),
    'deduplicated',false,'reversed_conversions',v_reversed,
    'new_journey_created',false
  );
END $$;

REVOKE ALL ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_conversation_journey_event_v1(
  uuid,bigint,text,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid
) TO service_role;
