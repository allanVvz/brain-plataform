-- Make semantic-group assignment idempotent when the lead already belongs to
-- the requested group. The INSERT trigger runs before ON CONFLICT, therefore
-- the old upsert could reject its own no-op replay.

CREATE OR REPLACE FUNCTION public.replace_lead_semantic_group_v1(
  p_lead_id bigint,
  p_target_persona_id uuid,
  p_audience_id uuid,
  p_created_by_user_id uuid,
  p_idempotency_key text,
  p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_lead public.leads%ROWTYPE;
  v_audience public.audiences%ROWTYPE;
  v_membership public.lead_audience_memberships%ROWTYPE;
  v_previous_persona_id uuid;
BEGIN
  IF NULLIF(btrim(p_idempotency_key), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'idempotency key and reason are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_lead FROM public.leads WHERE id = p_lead_id FOR UPDATE;
  IF v_lead.id IS NULL THEN
    RAISE EXCEPTION 'lead not found' USING ERRCODE = 'P0002';
  END IF;
  v_previous_persona_id := v_lead.persona_id;

  SELECT * INTO v_audience FROM public.audiences WHERE id = p_audience_id;
  IF v_audience.id IS NULL
     OR v_audience.persona_id <> p_target_persona_id
     OR COALESCE(v_audience.metadata->>'kind', 'semantic_group') <> 'semantic_group' THEN
    RAISE EXCEPTION 'semantic group not found in target persona' USING ERRCODE = '22023';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.system_events
    WHERE event_type = 'lead_semantic_group_changed'
      AND entity_id = p_lead_id::text
      AND payload->>'idempotency_key' = p_idempotency_key
  ) THEN
    RETURN jsonb_build_object('lead_id', p_lead_id, 'audience_id', p_audience_id, 'deduplicated', true);
  END IF;

  DELETE FROM public.lead_audience_memberships lam
  USING public.audiences a
  WHERE lam.audience_id = a.id
    AND lam.lead_id = p_lead_id
    AND COALESCE(a.metadata->>'kind', 'semantic_group') = 'semantic_group'
    AND a.id <> p_audience_id;

  UPDATE public.leads
  SET persona_id = p_target_persona_id, updated_at = now()
  WHERE id = p_lead_id;

  SELECT * INTO v_membership
  FROM public.lead_audience_memberships
  WHERE lead_id = p_lead_id AND audience_id = p_audience_id
  FOR UPDATE;

  IF v_membership.id IS NULL THEN
    INSERT INTO public.lead_audience_memberships (
      lead_id, audience_id, membership_type, created_by_user_id
    ) VALUES (
      p_lead_id, p_audience_id, 'primary', p_created_by_user_id
    )
    RETURNING * INTO v_membership;
  ELSE
    UPDATE public.lead_audience_memberships
    SET membership_type = 'primary'
    WHERE id = v_membership.id
    RETURNING * INTO v_membership;
  END IF;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'lead_semantic_group_changed', 'lead', p_lead_id::text, p_target_persona_id,
    jsonb_build_object(
      'previous_persona_id', v_previous_persona_id,
      'audience_id', p_audience_id,
      'idempotency_key', p_idempotency_key,
      'reason', p_reason,
      'actor_user_id', p_created_by_user_id
    ),
    'info', 'leads.group'
  );

  RETURN jsonb_build_object(
    'lead_id', p_lead_id,
    'audience_id', p_audience_id,
    'membership_id', v_membership.id,
    'deduplicated', false
  );
END;
$$;

REVOKE ALL ON FUNCTION public.replace_lead_semantic_group_v1(bigint, uuid, uuid, uuid, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_lead_semantic_group_v1(bigint, uuid, uuid, uuid, text, text)
  TO service_role;

NOTIFY pgrst, 'reload schema';
