-- Generic, proof-preserving repair for a historical false ignored_twice fact.
-- Additive only. Production application requires separate authorization.

CREATE OR REPLACE FUNCTION public.repair_literal_conversation_fact_v1(
  p_ledger_id uuid,p_invalid_fact_id uuid,p_expected_revision bigint,
  p_field_key text,p_owner_node_id text,p_source_message_id text,
  p_evidence_span text,p_value_text text,p_confidence numeric,
  p_apply boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_ledger public.conversation_ledgers%ROWTYPE;
  v_invalid public.conversation_facts%ROWTYPE;
  v_message text; v_field_published boolean := false;
  v_normalized_evidence text; v_normalized_value text; v_new_fact_id uuid;
BEGIN
  SELECT * INTO v_ledger FROM public.conversation_ledgers
   WHERE id=p_ledger_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger not found' USING ERRCODE='P0002'; END IF;
  IF v_ledger.revision<>p_expected_revision THEN
    RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001';
  END IF;

  SELECT * INTO v_invalid FROM public.conversation_facts
   WHERE id=p_invalid_fact_id AND ledger_id=p_ledger_id AND is_current FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'current invalid fact not found' USING ERRCODE='P0002'; END IF;
  IF v_invalid.field_key<>p_field_key OR v_invalid.owner_node_id<>p_owner_node_id THEN
    RAISE EXCEPTION 'fact identity mismatch' USING ERRCODE='22023';
  END IF;
  IF v_invalid.status<>'unknown'
     OR coalesce(v_invalid.metadata->>'reason','')<>'ignored_twice' THEN
    RAISE EXCEPTION 'target is not an ignored_twice fact' USING ERRCODE='22023';
  END IF;
  IF p_confidence IS NULL OR p_confidence<0 OR p_confidence>1 THEN
    RAISE EXCEPTION 'confidence outside range' USING ERRCODE='22023';
  END IF;

  SELECT m.content INTO v_message FROM public.messages m
   WHERE m.lead_id=v_ledger.lead_ref
     AND (m.id::text=p_source_message_id OR m.sender_id=p_source_message_id)
     AND coalesce(m.direction,'inbound')='inbound'
   ORDER BY m.created_at DESC LIMIT 1;
  IF v_message IS NULL THEN RAISE EXCEPTION 'source inbound message not found' USING ERRCODE='P0002'; END IF;
  IF nullif(p_evidence_span,'') IS NULL OR strpos(v_message,p_evidence_span)=0 THEN
    RAISE EXCEPTION 'evidence is not literal in source message' USING ERRCODE='22023';
  END IF;
  v_normalized_evidence := regexp_replace(trim(p_evidence_span),'\s+',' ','g');
  v_normalized_value := regexp_replace(trim(p_value_text),'\s+',' ','g');
  IF v_normalized_value<>v_normalized_evidence THEN
    RAISE EXCEPTION 'literal value differs from evidence' USING ERRCODE='22023';
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.graph_publications publication
    CROSS JOIN LATERAL jsonb_array_elements(
      coalesce(publication.document_json->'common_contract'->'fields','[]'::jsonb)
      || coalesce((
        SELECT jsonb_agg(item.value)
          FROM jsonb_each(coalesce(publication.document_json->'branch_contracts','{}'::jsonb)) AS branch(key,value)
          CROSS JOIN LATERAL jsonb_array_elements(coalesce(branch.value->'fields','[]'::jsonb)) AS item(value)
      ),'[]'::jsonb)
    ) AS published_field(value)
    WHERE publication.id=v_ledger.publication_id
      AND published_field.value->>'key'=p_field_key
      AND published_field.value->>'owner_node_id'=p_owner_node_id
  ) INTO v_field_published;
  IF NOT v_field_published THEN
    RAISE EXCEPTION 'field owner is absent from ledger publication' USING ERRCODE='22023';
  END IF;

  IF NOT p_apply THEN
    RETURN jsonb_build_object(
      'changed',false,'apply',false,'ledger_id',p_ledger_id,
      'invalid_fact_id',p_invalid_fact_id,'expected_revision',p_expected_revision,
      'field_key',p_field_key,'owner_node_id',p_owner_node_id,
      'source_message_id',p_source_message_id,'evidence_span',p_evidence_span,
      'value',v_normalized_value,'confidence',p_confidence,
      'reason','literal_fact_repair_validated');
  END IF;

  UPDATE public.conversation_facts SET is_current=false,updated_at=now()
   WHERE id=p_invalid_fact_id AND is_current;
  IF NOT FOUND THEN RAISE EXCEPTION 'fact changed during repair' USING ERRCODE='40001'; END IF;
  INSERT INTO public.conversation_facts(
    ledger_id,field_key,owner_node_id,status,value_json,source_message_id,
    evidence_span,confidence,revision,supersedes_fact_id,is_current,metadata
  ) VALUES (
    p_ledger_id,p_field_key,p_owner_node_id,'known',to_jsonb(v_normalized_value),
    p_source_message_id,p_evidence_span,p_confidence,p_expected_revision+1,
    p_invalid_fact_id,true,jsonb_build_object(
      'repair','literal_fact_repair_v1','replaced_reason','ignored_twice',
      'source_fact_id',p_invalid_fact_id)
  ) RETURNING id INTO v_new_fact_id;
  UPDATE public.conversation_ledgers SET revision=revision+1,updated_at=now()
   WHERE id=p_ledger_id AND revision=p_expected_revision;
  IF NOT FOUND THEN RAISE EXCEPTION 'ledger revision conflict' USING ERRCODE='40001'; END IF;
  INSERT INTO public.system_events(event_type,entity_type,entity_id,persona_id,source,payload)
  VALUES ('conversation_literal_fact_repaired','conversation_ledger',p_ledger_id,
    v_ledger.persona_id,'repair_literal_conversation_fact_v1',jsonb_build_object(
      'invalid_fact_id',p_invalid_fact_id,'new_fact_id',v_new_fact_id,
      'field_key',p_field_key,'owner_node_id',p_owner_node_id,
      'source_message_id',p_source_message_id,
      'previous_revision',p_expected_revision,'revision',p_expected_revision+1));
  RETURN jsonb_build_object(
    'changed',true,'apply',true,'ledger_id',p_ledger_id,
    'invalid_fact_id',p_invalid_fact_id,'new_fact_id',v_new_fact_id,
    'previous_revision',p_expected_revision,'revision',p_expected_revision+1,
    'reason','literal_fact_repaired');
END $$;

REVOKE ALL ON FUNCTION public.repair_literal_conversation_fact_v1(
  uuid,uuid,bigint,text,text,text,text,text,numeric,boolean
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.repair_literal_conversation_fact_v1(
  uuid,uuid,bigint,text,text,text,text,text,numeric,boolean
) TO service_role;
