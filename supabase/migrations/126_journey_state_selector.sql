-- Seletor de estado do pedido: o closer humano no comando.
--
-- `record_conversation_journey_event_v1` e append-only e idempotente -- certo
-- para integracao e para o agente, errado para um humano corrigindo o
-- registro. Um closer precisa poder voltar atras: marcou entregue sem querer,
-- desfaz; cancelou o pedido errado, reabre.
--
-- Esta funcao e a outra metade do contrato. Ela recebe o estado ALVO e calcula
-- o delta a partir do estado atual, inclusive os caminhos de volta que nao
-- existiam:
--
--   vendido    -> convertido  estorna a conversao e tira o marcador `sold`
--   convertido -> qualificado limpa `converted_at` DESTA jornada
--   fechado    -> aberto      reabre (`is_current`), se ninguem passou na frente
--
-- Guarda estrutural: reabrir so vale enquanto nenhuma jornada mais nova
-- existir. `idx_conversation_journeys_one_current` (migration 118) garante uma
-- corrente por lead, e reabrir por cima corromperia o indice -- entao a funcao
-- levanta erro nomeado em vez de deixar o banco recusar com violacao de indice.
--
-- Piso permanente: depois do primeiro agendamento ou compra a lead esta
-- convertida e nao volta a "qualificado". O carimbo mora em
-- `leads.metadata.first_converted_at` e ninguem o apaga -- nem o cancelamento,
-- nem este seletor.

CREATE OR REPLACE FUNCTION public.set_conversation_journey_state_v1(
  p_persona_id uuid, p_lead_ref bigint, p_target text, p_source text,
  p_occurred_at timestamptz, p_offering text DEFAULT 'sales',
  p_responsible_user_id uuid DEFAULT NULL, p_metadata jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_journey public.conversation_journeys%ROWTYPE;
  v_conversion public.sales_conversions%ROWTYPE;
  v_from text; v_newer bigint; v_first_converted text;
  v_reversed int:=0; v_conversion_type text; v_closing text;
  v_open boolean; v_key text; v_seq int;
BEGIN
  IF p_target NOT IN ('qualificado','convertido','vendido','entregue','cancelado') THEN
    RAISE EXCEPTION 'invalid journey state target';
  END IF;
  IF btrim(coalesce(p_source,''))='' THEN
    RAISE EXCEPTION 'event identity is required';
  END IF;
  v_open := p_target IN ('qualificado','convertido','vendido');
  v_conversion_type := CASE WHEN p_offering='appointment' THEN 'appointment_booked' ELSE 'purchase' END;
  v_closing := CASE WHEN p_offering='appointment' THEN 'service_completed' ELSE 'delivered' END;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));

  SELECT * INTO v_journey FROM public.conversation_journeys
   WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref
   ORDER BY sequence DESC LIMIT 1 FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no journey for this lead' USING ERRCODE='P0002';
  END IF;

  -- Estado atual na mesma linguagem do seletor (espelha journey_outcome.derive).
  v_from := CASE
    WHEN v_journey.state='closed'
      THEN CASE WHEN v_journey.metadata->>'closing_event'='cancelled'
                THEN 'cancelado' ELSE 'entregue' END
    WHEN v_journey.state='converted'
      THEN CASE WHEN coalesce((v_journey.metadata->>'sold')::boolean,false)
                THEN 'vendido' ELSE 'convertido' END
    WHEN v_journey.state IN ('qualified_confirmed','handed_off') THEN 'qualificado'
    ELSE 'coletando'
  END;

  IF v_from = p_target THEN
    RETURN jsonb_build_object(
      'target',p_target,'from',v_from,'changed',false,
      'journey',to_jsonb(v_journey),'reversed_conversions',0
    );
  END IF;

  -- Piso: a lead nao regride abaixo de convertida depois da primeira venda.
  SELECT metadata->>'first_converted_at' INTO v_first_converted
    FROM public.leads WHERE id=p_lead_ref;
  IF p_target='qualificado' AND v_first_converted IS NOT NULL THEN
    RAISE EXCEPTION 'lead already converted: qualificado is no longer available';
  END IF;

  -- Reabrir so vale se ninguem abriu o pedido seguinte.
  IF v_open AND NOT v_journey.is_current THEN
    SELECT max(sequence) INTO v_newer FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND sequence>v_journey.sequence;
    IF v_newer IS NOT NULL THEN
      RAISE EXCEPTION 'a newer order already exists for this lead';
    END IF;
  END IF;

  -- Sair de vendido (para tras ou para cancelado) estorna a conversao.
  IF v_from='vendido' AND p_target IN ('qualificado','convertido')
     OR p_target='cancelado' THEN
    WITH estornadas AS (
      UPDATE public.sales_conversions SET
        status='cancelled', cancelled_at=coalesce(cancelled_at,p_occurred_at),
        transition_history=transition_history||jsonb_build_array(jsonb_build_object(
          'from',status,'to','cancelled','at',now(),'reason','journey_state_selector'
        )),
        metadata=metadata||jsonb_build_object('cancelled_by_state_selector',true),
        updated_at=now()
       WHERE journey_id=v_journey.id AND status='completed'
      RETURNING 1
    ) SELECT count(*) INTO v_reversed FROM estornadas;
  END IF;

  -- Entrar em vendido garante uma conversao ativa. Chave deterministica por
  -- tentativa: uma venda estornada queimou a chave anterior, entao a proxima
  -- precisa de uma nova em vez de colidir no UNIQUE(persona,source,key).
  IF p_target='vendido' THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.sales_conversions
       WHERE journey_id=v_journey.id AND status='completed'
    ) THEN
      SELECT count(*)+1 INTO v_seq FROM public.sales_conversions WHERE journey_id=v_journey.id;
      v_key := 'selector:'||v_journey.id::text||':'||v_seq::text;
      INSERT INTO public.sales_conversions(
        persona_id,lead_ref,journey_id,conversion_type,status,source,idempotency_key,
        metadata,occurred_at,completed_at,responsible_user_id,
        transition_history,idempotency_history
      ) VALUES (
        p_persona_id,p_lead_ref,v_journey.id,v_conversion_type,'completed',p_source,v_key,
        coalesce(p_metadata,'{}'::jsonb)||jsonb_build_object(
          'lead_first_conversion',v_first_converted IS NULL,
          'recurrence',v_first_converted IS NOT NULL,
          'recorded_by','state_selector'
        ),
        p_occurred_at,p_occurred_at,p_responsible_user_id,
        jsonb_build_array(jsonb_build_object('status','completed','at',now())),
        jsonb_build_array(jsonb_build_object('source',p_source,'key',v_key,'at',now()))
      ) RETURNING * INTO v_conversion;
    END IF;
    -- Carimbo permanente da lead, escrito uma unica vez.
    UPDATE public.leads SET
      metadata=coalesce(metadata,'{}'::jsonb)
        ||jsonb_build_object('first_converted_at',
             coalesce(metadata->>'first_converted_at', to_char(p_occurred_at,'YYYY-MM-DD"T"HH24:MI:SSOF')))
     WHERE id=p_lead_ref;
  END IF;

  UPDATE public.conversation_journeys SET
    state=CASE p_target
      WHEN 'qualificado' THEN 'handed_off'
      WHEN 'convertido' THEN 'converted'
      WHEN 'vendido' THEN 'converted'
      ELSE 'closed' END,
    is_current=v_open,
    converted_at=CASE
      WHEN p_target='qualificado' THEN NULL
      WHEN p_target IN ('convertido','vendido') THEN coalesce(converted_at,p_occurred_at)
      ELSE converted_at END,
    closed_at=CASE WHEN v_open THEN NULL ELSE coalesce(closed_at,p_occurred_at) END,
    handed_off_at=CASE WHEN p_target='qualificado' THEN coalesce(handed_off_at,p_occurred_at)
                       ELSE handed_off_at END,
    metadata=(
      CASE WHEN v_open THEN metadata-'closing_event' ELSE metadata END
      - CASE WHEN p_target IN ('qualificado','convertido','cancelado') THEN 'sold' ELSE '' END
    )
      ||coalesce(p_metadata,'{}'::jsonb)
      ||CASE WHEN p_target='vendido' THEN jsonb_build_object('sold',true) ELSE '{}'::jsonb END
      ||CASE WHEN v_open THEN '{}'::jsonb
             ELSE jsonb_build_object('closing_event',
                    CASE WHEN p_target='cancelado' THEN 'cancelled' ELSE v_closing END) END
      ||jsonb_build_object(
          'state_selector_last',jsonb_build_object(
            'from',v_from,'to',p_target,'at',p_occurred_at,'source',p_source,
            'by',p_responsible_user_id
          ),
          'state_history',coalesce(metadata->'state_history','[]'::jsonb)
            ||jsonb_build_array(jsonb_build_object(
                'from',v_from,'to',p_target,'at',p_occurred_at,'source',p_source,
                'by',p_responsible_user_id
              ))
        ),
    updated_at=now()
   WHERE id=v_journey.id RETURNING * INTO v_journey;

  RETURN jsonb_build_object(
    'target',p_target,'from',v_from,'changed',true,
    'journey',to_jsonb(v_journey),
    'conversion',to_jsonb(v_conversion),
    'reversed_conversions',v_reversed,
    'journey_closed',NOT v_open
  );
END $$;

REVOKE ALL ON FUNCTION public.set_conversation_journey_state_v1(
  uuid,bigint,text,text,timestamptz,text,uuid,jsonb
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.set_conversation_journey_state_v1(
  uuid,bigint,text,text,timestamptz,text,uuid,jsonb
) TO service_role;

-- O carimbo permanente tambem passa a ser escrito pela via de eventos, para
-- integracao e seletor concordarem sobre quando a lead converteu.
CREATE OR REPLACE FUNCTION public.stamp_lead_first_conversion_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  IF NEW.completed_at IS NOT NULL AND NEW.status='completed' THEN
    UPDATE public.leads SET
      metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object(
        'first_converted_at',
        coalesce(metadata->>'first_converted_at',
                 to_char(NEW.completed_at,'YYYY-MM-DD"T"HH24:MI:SSOF'))
      )
     WHERE id=NEW.lead_ref;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_stamp_lead_first_conversion_v1 ON public.sales_conversions;
CREATE TRIGGER trg_stamp_lead_first_conversion_v1
  AFTER INSERT ON public.sales_conversions
  FOR EACH ROW EXECUTE FUNCTION public.stamp_lead_first_conversion_v1();

REVOKE ALL ON FUNCTION public.stamp_lead_first_conversion_v1()
  FROM PUBLIC,anon,authenticated;

-- Backfill: leads que ja converteram antes desta migration recebem o carimbo.
UPDATE public.leads l SET
  metadata=coalesce(l.metadata,'{}'::jsonb)||jsonb_build_object(
    'first_converted_at', to_char(c.primeira,'YYYY-MM-DD"T"HH24:MI:SSOF')
  )
 FROM (
   SELECT lead_ref, min(completed_at) primeira
     FROM public.sales_conversions
    WHERE completed_at IS NOT NULL
    GROUP BY lead_ref
 ) c
 WHERE c.lead_ref=l.id AND l.metadata->>'first_converted_at' IS NULL;
