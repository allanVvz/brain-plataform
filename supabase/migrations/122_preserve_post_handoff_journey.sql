-- A support turn after a qualified handoff must not reopen confirmation.
-- The lead can be resumed for the current request while the journey remains
-- handed off; only a new, explicitly confirmed change may create a new handoff.

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
  IF v_confirmation_state='post_qualification_support' THEN
    UPDATE public.conversation_journeys SET
      state=CASE WHEN state IN ('converted','closed') THEN state ELSE 'handed_off' END,
      handed_off_at=coalesce(handed_off_at,NEW.created_at),
      metadata=metadata||jsonb_build_object(
        'confirmation_state','post_qualification_support','last_proof_id',NEW.id
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

REVOKE ALL ON FUNCTION public.project_conversation_journey_from_proof_v1()
  FROM PUBLIC,anon,authenticated;
