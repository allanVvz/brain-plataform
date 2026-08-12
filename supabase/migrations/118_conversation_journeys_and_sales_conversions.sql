-- Conversation lifecycle and commercial outcomes are deliberately separate.
-- Production application requires its own explicit authorization.

CREATE TABLE IF NOT EXISTS public.conversation_journeys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE RESTRICT,
  lead_ref bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  sequence bigint NOT NULL CHECK (sequence > 0),
  is_current boolean NOT NULL DEFAULT true,
  state text NOT NULL DEFAULT 'collecting' CHECK (state IN (
    'collecting','awaiting_confirmation','qualified_confirmed',
    'handed_off','converted','closed'
  )),
  previous_journey_id uuid REFERENCES public.conversation_journeys(id) ON DELETE SET NULL,
  publication_id uuid REFERENCES public.graph_publications(id) ON DELETE RESTRICT,
  graph_checksum text CHECK (graph_checksum IS NULL OR graph_checksum LIKE 'sha256:%'),
  started_at timestamptz NOT NULL DEFAULT now(),
  qualification_completed_at timestamptz,
  qualification_confirmed_at timestamptz,
  handed_off_at timestamptz,
  converted_at timestamptz,
  closed_at timestamptz,
  opening_reason text NOT NULL DEFAULT 'initial',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(persona_id, lead_ref, sequence)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_journeys_one_current
  ON public.conversation_journeys(persona_id,lead_ref) WHERE is_current;
CREATE INDEX IF NOT EXISTS idx_conversation_journeys_lead
  ON public.conversation_journeys(persona_id,lead_ref,sequence DESC);

-- Backfill exactly one journey for every legacy ledger without interpreting
-- old friendly copy as explicit confirmation or conversion.
INSERT INTO public.conversation_journeys(
  persona_id,lead_ref,sequence,is_current,state,publication_id,graph_checksum,
  started_at,opening_reason,metadata
)
SELECT l.persona_id,l.lead_ref,1,true,'collecting',l.publication_id,l.graph_checksum,
       l.created_at,'legacy_backfill',jsonb_build_object('backfilled',true)
  FROM public.conversation_ledgers l
ON CONFLICT (persona_id,lead_ref,sequence) DO NOTHING;

ALTER TABLE public.conversation_ledgers
  ADD COLUMN IF NOT EXISTS journey_id uuid REFERENCES public.conversation_journeys(id) ON DELETE CASCADE;
UPDATE public.conversation_ledgers l
   SET journey_id=j.id
  FROM public.conversation_journeys j
 WHERE l.journey_id IS NULL AND j.persona_id=l.persona_id
   AND j.lead_ref=l.lead_ref AND j.sequence=1;
ALTER TABLE public.conversation_ledgers ALTER COLUMN journey_id SET NOT NULL;
ALTER TABLE public.conversation_ledgers DROP CONSTRAINT IF EXISTS conversation_ledgers_persona_id_lead_ref_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_ledgers_journey
  ON public.conversation_ledgers(journey_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_ledgers_per_journey
  ON public.conversation_ledgers(persona_id,lead_ref,journey_id);

CREATE OR REPLACE FUNCTION public.assign_conversation_ledger_journey_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE v_journey public.conversation_journeys%ROWTYPE;
BEGIN
  IF NEW.journey_id IS NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.persona_id::text||':'||NEW.lead_ref::text,0));
    SELECT * INTO v_journey FROM public.conversation_journeys
     WHERE persona_id=NEW.persona_id AND lead_ref=NEW.lead_ref AND is_current FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO public.conversation_journeys(
        persona_id,lead_ref,sequence,publication_id,graph_checksum,opening_reason
      ) SELECT NEW.persona_id,NEW.lead_ref,coalesce(max(sequence),0)+1,
               NEW.publication_id,NEW.graph_checksum,'initial'
          FROM public.conversation_journeys
         WHERE persona_id=NEW.persona_id AND lead_ref=NEW.lead_ref
      RETURNING * INTO v_journey;
    END IF;
    NEW.journey_id:=v_journey.id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_assign_conversation_ledger_journey_v1 ON public.conversation_ledgers;
CREATE TRIGGER trg_assign_conversation_ledger_journey_v1
  BEFORE INSERT ON public.conversation_ledgers FOR EACH ROW
  EXECUTE FUNCTION public.assign_conversation_ledger_journey_v1();

ALTER TABLE public.conversation_turn_proofs
  ADD COLUMN IF NOT EXISTS journey_id uuid REFERENCES public.conversation_journeys(id) ON DELETE SET NULL;
UPDATE public.conversation_turn_proofs p SET journey_id=l.journey_id
  FROM public.conversation_ledgers l
 WHERE p.journey_id IS NULL AND p.ledger_id=l.id;
CREATE INDEX IF NOT EXISTS idx_conversation_turn_proofs_journey
  ON public.conversation_turn_proofs(journey_id,created_at DESC);

CREATE OR REPLACE FUNCTION public.assign_conversation_proof_journey_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
  IF NEW.journey_id IS NULL AND NEW.ledger_id IS NOT NULL THEN
    SELECT journey_id INTO NEW.journey_id FROM public.conversation_ledgers WHERE id=NEW.ledger_id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_assign_conversation_proof_journey_v1 ON public.conversation_turn_proofs;
CREATE TRIGGER trg_assign_conversation_proof_journey_v1
  BEFORE INSERT OR UPDATE OF ledger_id ON public.conversation_turn_proofs FOR EACH ROW
  EXECUTE FUNCTION public.assign_conversation_proof_journey_v1();

CREATE OR REPLACE FUNCTION public.project_conversation_journey_from_proof_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_confirmed boolean; v_handed_off boolean;
BEGIN
  IF NEW.journey_id IS NULL
     OR jsonb_typeof(NEW.proof_result->'missing_fields') IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.proof_result->'missing_fields')<>0 THEN
    RETURN NEW;
  END IF;
  v_confirmed:=coalesce((NEW.proof_result->>'explicit_confirmation')::boolean,false);
  v_handed_off:=v_confirmed AND coalesce(NEW.final_decision->>'route','')='human';
  UPDATE public.conversation_journeys SET
    state=CASE WHEN v_handed_off THEN 'handed_off'
               WHEN v_confirmed THEN 'qualified_confirmed'
               ELSE 'awaiting_confirmation' END,
    qualification_completed_at=coalesce(qualification_completed_at,NEW.created_at),
    qualification_confirmed_at=CASE WHEN v_confirmed THEN coalesce(qualification_confirmed_at,NEW.created_at) ELSE qualification_confirmed_at END,
    handed_off_at=CASE WHEN v_handed_off THEN coalesce(handed_off_at,NEW.created_at) ELSE handed_off_at END,
    updated_at=now()
   WHERE id=NEW.journey_id;
  IF v_confirmed THEN
    PERFORM public.maybe_open_next_conversation_journey_v1(NEW.journey_id);
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_project_conversation_journey_from_proof_v1 ON public.conversation_turn_proofs;
CREATE TRIGGER trg_project_conversation_journey_from_proof_v1
  AFTER INSERT ON public.conversation_turn_proofs FOR EACH ROW
  EXECUTE FUNCTION public.project_conversation_journey_from_proof_v1();

-- Preserve the complete, battle-tested v3 commit body from migration 112 and
-- narrow only its ledger lock to the current journey. Repeating that large
-- function here would make later safety fixes drift between two copies.
DO $$
DECLARE v_oid oid; v_definition text; v_scoped text;
BEGIN
  SELECT p.oid INTO v_oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='public' AND p.proname='commit_graph_turn_v3'
     AND pg_get_function_identity_arguments(p.oid) LIKE 'p_canonical_inbound_id text,%';
  IF v_oid IS NULL THEN RAISE EXCEPTION 'commit_graph_turn_v3 not found'; END IF;
  v_definition:=pg_get_functiondef(v_oid);
  v_scoped:=replace(v_definition,
    'WHERE persona_id = p_persona_id AND lead_ref = p_lead_ref FOR UPDATE;',
    'WHERE persona_id = p_persona_id AND lead_ref = p_lead_ref AND journey_id = (SELECT id FROM public.conversation_journeys WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current) FOR UPDATE;');
  IF v_scoped=v_definition THEN
    RAISE EXCEPTION 'commit_graph_turn_v3 ledger selector contract changed';
  END IF;
  EXECUTE v_scoped;
END $$;

CREATE TABLE IF NOT EXISTS public.sales_conversions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE RESTRICT,
  lead_ref bigint NOT NULL REFERENCES public.leads(id) ON DELETE RESTRICT,
  journey_id uuid NOT NULL REFERENCES public.conversation_journeys(id) ON DELETE RESTRICT,
  conversion_type text NOT NULL CHECK (conversion_type IN (
    'purchase','appointment_booked','contract_signed','other'
  )),
  status text NOT NULL DEFAULT 'completed' CHECK (status IN (
    'completed','cancelled','partially_refunded','refunded'
  )),
  amount_minor bigint CHECK (amount_minor IS NULL OR amount_minor >= 0),
  refunded_amount_minor bigint CHECK (
    refunded_amount_minor IS NULL OR refunded_amount_minor >= 0
  ),
  currency text CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
  items jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(items)='array'),
  source text NOT NULL CHECK (btrim(source)<>''),
  idempotency_key text NOT NULL CHECK (btrim(idempotency_key)<>''),
  external_ref text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata)='object'),
  transition_history jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(transition_history)='array'),
  idempotency_history jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(idempotency_history)='array'),
  occurred_at timestamptz NOT NULL,
  completed_at timestamptz,
  cancelled_at timestamptz,
  refunded_at timestamptz,
  responsible_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(persona_id,source,idempotency_key),
  CHECK (amount_minor IS NULL OR currency IS NOT NULL),
  CHECK (refunded_amount_minor IS NULL OR amount_minor IS NULL OR refunded_amount_minor<=amount_minor)
);
CREATE INDEX IF NOT EXISTS idx_sales_conversions_journey
  ON public.sales_conversions(journey_id,occurred_at DESC);

CREATE OR REPLACE FUNCTION public.ensure_current_conversation_journey_v1(
  p_persona_id uuid,p_lead_ref bigint,p_publication_id uuid,p_graph_checksum text,
  p_opening_reason text DEFAULT 'initial'
) RETURNS public.conversation_journeys
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_journey public.conversation_journeys%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));
  SELECT * INTO v_journey FROM public.conversation_journeys
   WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current FOR UPDATE;
  IF FOUND THEN RETURN v_journey; END IF;
  INSERT INTO public.conversation_journeys(
    persona_id,lead_ref,sequence,publication_id,graph_checksum,opening_reason
  ) SELECT p_persona_id,p_lead_ref,coalesce(max(sequence),0)+1,
           p_publication_id,p_graph_checksum,p_opening_reason
      FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref
  RETURNING * INTO v_journey;
  RETURN v_journey;
END $$;

CREATE OR REPLACE FUNCTION public.maybe_open_next_conversation_journey_v1(
  p_journey_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_origin public.conversation_journeys%ROWTYPE; v_next public.conversation_journeys%ROWTYPE;
BEGIN
  SELECT * INTO v_origin FROM public.conversation_journeys WHERE id=p_journey_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'journey not found' USING ERRCODE='P0002'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(v_origin.persona_id::text||':'||v_origin.lead_ref::text,0));
  IF v_origin.qualification_confirmed_at IS NULL OR NOT EXISTS (
    SELECT 1 FROM public.sales_conversions c WHERE c.journey_id=v_origin.id
      AND c.conversion_type='purchase' AND c.completed_at IS NOT NULL
  ) THEN
    RETURN jsonb_build_object('new_journey_created',false,'origin_journey',to_jsonb(v_origin));
  END IF;
  SELECT * INTO v_next FROM public.conversation_journeys
   WHERE previous_journey_id=v_origin.id ORDER BY sequence LIMIT 1;
  IF NOT FOUND THEN
    UPDATE public.conversation_journeys SET is_current=false,state='closed',closed_at=coalesce(closed_at,now()),updated_at=now()
     WHERE persona_id=v_origin.persona_id AND lead_ref=v_origin.lead_ref AND is_current;
    INSERT INTO public.conversation_journeys(
      persona_id,lead_ref,sequence,previous_journey_id,publication_id,graph_checksum,opening_reason
    ) VALUES (
      v_origin.persona_id,v_origin.lead_ref,v_origin.sequence+1,v_origin.id,
      v_origin.publication_id,v_origin.graph_checksum,'qualified_purchase_completed'
    ) RETURNING * INTO v_next;
    RETURN jsonb_build_object('new_journey_created',true,'origin_journey',to_jsonb(v_origin),'new_journey',to_jsonb(v_next));
  END IF;
  RETURN jsonb_build_object('new_journey_created',false,'origin_journey',to_jsonb(v_origin),'new_journey',to_jsonb(v_next));
END $$;

CREATE OR REPLACE FUNCTION public.record_purchase_completed_v1(
  p_persona_id uuid,p_lead_ref bigint,p_idempotency_key text,p_source text,
  p_occurred_at timestamptz,p_external_ref text DEFAULT NULL,p_amount_minor bigint DEFAULT NULL,
  p_currency text DEFAULT NULL,p_items jsonb DEFAULT '[]'::jsonb,p_metadata jsonb DEFAULT '{}'::jsonb,
  p_responsible_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_journey public.conversation_journeys%ROWTYPE; v_conversion public.sales_conversions%ROWTYPE;
        v_existing boolean:=false; v_open jsonb;
BEGIN
  IF p_amount_minor IS NOT NULL AND p_currency IS NULL THEN RAISE EXCEPTION 'currency is required with amount'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));
  SELECT * INTO v_conversion FROM public.sales_conversions
   WHERE persona_id=p_persona_id AND source=p_source AND idempotency_key=p_idempotency_key FOR UPDATE;
  IF FOUND THEN v_existing:=true; v_journey.id:=v_conversion.journey_id;
  ELSE
    SELECT * INTO v_journey FROM public.conversation_journeys
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'current journey not found' USING ERRCODE='P0002'; END IF;
    INSERT INTO public.sales_conversions(
      persona_id,lead_ref,journey_id,conversion_type,status,amount_minor,currency,items,
      source,idempotency_key,external_ref,metadata,occurred_at,completed_at,responsible_user_id,
      transition_history,idempotency_history
    ) VALUES (p_persona_id,p_lead_ref,v_journey.id,'purchase','completed',p_amount_minor,
      upper(p_currency),coalesce(p_items,'[]'),p_source,p_idempotency_key,p_external_ref,
      coalesce(p_metadata,'{}'),p_occurred_at,p_occurred_at,p_responsible_user_id,
      jsonb_build_array(jsonb_build_object('status','completed','at',now())),
      jsonb_build_array(jsonb_build_object('source',p_source,'key',p_idempotency_key,'at',now())))
    RETURNING * INTO v_conversion;
    UPDATE public.conversation_journeys SET converted_at=coalesce(converted_at,p_occurred_at),updated_at=now()
     WHERE id=v_journey.id;
  END IF;
  v_open:=public.maybe_open_next_conversation_journey_v1(v_conversion.journey_id);
  RETURN jsonb_build_object('conversion',to_jsonb(v_conversion),'deduplicated',v_existing,
    'origin_journey_id',v_conversion.journey_id,'new_journey_created',coalesce((v_open->>'new_journey_created')::boolean,false),
    'new_journey',v_open->'new_journey');
END $$;

CREATE OR REPLACE FUNCTION public.mark_conversation_journey_qualification_v1(
  p_persona_id uuid,p_lead_ref bigint,p_confirmed boolean,p_handed_off boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_journey public.conversation_journeys%ROWTYPE; v_open jsonb;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_persona_id::text||':'||p_lead_ref::text,0));
  SELECT * INTO v_journey FROM public.conversation_journeys
   WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref AND is_current FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'current journey not found' USING ERRCODE='P0002'; END IF;
  UPDATE public.conversation_journeys SET
    state=CASE WHEN p_handed_off THEN 'handed_off' WHEN p_confirmed THEN 'qualified_confirmed' ELSE 'awaiting_confirmation' END,
    qualification_completed_at=coalesce(qualification_completed_at,now()),
    qualification_confirmed_at=CASE WHEN p_confirmed THEN coalesce(qualification_confirmed_at,now()) ELSE qualification_confirmed_at END,
    handed_off_at=CASE WHEN p_handed_off THEN coalesce(handed_off_at,now()) ELSE handed_off_at END,
    updated_at=now() WHERE id=v_journey.id RETURNING * INTO v_journey;
  v_open:=public.maybe_open_next_conversation_journey_v1(v_journey.id);
  RETURN jsonb_build_object('journey',to_jsonb(v_journey),'new_journey_created',coalesce((v_open->>'new_journey_created')::boolean,false),'new_journey',v_open->'new_journey');
END $$;

CREATE OR REPLACE FUNCTION public.transition_sales_conversion_status_v1(
  p_conversion_id uuid,p_status text,p_idempotency_key text,p_refunded_amount_minor bigint DEFAULT NULL,
  p_metadata jsonb DEFAULT '{}'::jsonb,p_responsible_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_conversion public.sales_conversions%ROWTYPE;
BEGIN
  SELECT * INTO v_conversion FROM public.sales_conversions WHERE id=p_conversion_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'conversion not found' USING ERRCODE='P0002'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_conversion.idempotency_history) e
             WHERE e->>'key'=p_idempotency_key) THEN
    RETURN jsonb_build_object('conversion',to_jsonb(v_conversion),'deduplicated',true);
  END IF;
  IF p_status NOT IN ('cancelled','partially_refunded','refunded') THEN RAISE EXCEPTION 'invalid status transition'; END IF;
  UPDATE public.sales_conversions SET status=p_status,refunded_amount_minor=p_refunded_amount_minor,
    cancelled_at=CASE WHEN p_status='cancelled' THEN coalesce(cancelled_at,now()) ELSE cancelled_at END,
    refunded_at=CASE WHEN p_status IN ('partially_refunded','refunded') THEN coalesce(refunded_at,now()) ELSE refunded_at END,
    metadata=metadata||coalesce(p_metadata,'{}'),responsible_user_id=coalesce(p_responsible_user_id,responsible_user_id),
    transition_history=transition_history||jsonb_build_array(jsonb_build_object('from',status,'to',p_status,'at',now())),
    idempotency_history=idempotency_history||jsonb_build_array(jsonb_build_object('key',p_idempotency_key,'at',now())),updated_at=now()
   WHERE id=p_conversion_id RETURNING * INTO v_conversion;
  RETURN jsonb_build_object('conversion',to_jsonb(v_conversion),'deduplicated',false);
END $$;

CREATE OR REPLACE FUNCTION public.claim_inactivity_recovery_candidate_v1(
  p_inbound_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_buffer public.lead_buffer%ROWTYPE; v_paused boolean;
BEGIN
  SELECT * INTO v_buffer FROM public.lead_buffer WHERE id=p_inbound_id FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN RETURN jsonb_build_object('state','not_claimed'); END IF;
  IF v_buffer.direction<>'inbound' OR v_buffer.status<>'buffered'
     OR v_buffer.payload->'conversation_commit' IS NOT NULL
     OR EXISTS (SELECT 1 FROM public.conversation_turn_proofs WHERE canonical_inbound_id=p_inbound_id::text)
     OR EXISTS (SELECT 1 FROM public.lead_buffer o WHERE o.direction='outbound'
                AND (o.payload->>'canonical_inbound_id'=p_inbound_id::text
                     OR o.correlation_id=v_buffer.correlation_id)) THEN
    RETURN jsonb_build_object('state','ineligible');
  END IF;
  SELECT coalesce(handoff_level='full',false) INTO v_paused FROM public.leads WHERE id=v_buffer.lead_ref FOR UPDATE;
  IF v_paused THEN
    INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,payload,level,source)
    VALUES ('pending_response_detected','lead',v_buffer.lead_ref::text,v_buffer.persona_id,
      jsonb_build_object('canonical_inbound_id',p_inbound_id),'info','workers.inactivity_recovery');
    RETURN jsonb_build_object('state','paused','inbound_id',p_inbound_id);
  END IF;
  UPDATE public.lead_buffer SET status='retry',available_at=now(),locked_at=NULL,locked_by=NULL,
    updated_at=now() WHERE id=p_inbound_id;
  RETURN jsonb_build_object('state','requeued','inbound_id',p_inbound_id);
END $$;

REVOKE ALL ON FUNCTION public.ensure_current_conversation_journey_v1(uuid,bigint,uuid,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.assign_conversation_ledger_journey_v1() FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.assign_conversation_proof_journey_v1() FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.project_conversation_journey_from_proof_v1() FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.record_purchase_completed_v1(uuid,bigint,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.mark_conversation_journey_qualification_v1(uuid,bigint,boolean,boolean) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.transition_sales_conversion_status_v1(uuid,text,text,bigint,jsonb,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.claim_inactivity_recovery_candidate_v1(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ensure_current_conversation_journey_v1(uuid,bigint,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.maybe_open_next_conversation_journey_v1(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_purchase_completed_v1(uuid,bigint,text,text,timestamptz,text,bigint,text,jsonb,jsonb,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.mark_conversation_journey_qualification_v1(uuid,bigint,boolean,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.transition_sales_conversion_status_v1(uuid,text,text,bigint,jsonb,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_inactivity_recovery_candidate_v1(uuid) TO service_role;
