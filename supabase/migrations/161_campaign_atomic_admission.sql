-- Campaign delivery admission is serialized per persona. The existing
-- idx_lead_buffer_queue_persona_created index (migration 141) supports the
-- capacity window, so this migration does not lock lead_buffer for an index.

CREATE OR REPLACE FUNCTION public.admit_campaign_outbound_v1(
  p_buffer jsonb, p_message jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_persona uuid := nullif(p_buffer->>'persona_id', '')::uuid;
  v_lead bigint := nullif(p_buffer->>'lead_ref', '')::bigint;
  v_campaign uuid := nullif(p_buffer->>'campaign_id', '')::uuid;
  v_recipient_id uuid := nullif(p_buffer->>'campaign_recipient_id', '')::uuid;
  v_revision integer := nullif(p_buffer->>'campaign_revision', '')::integer;
  v_step integer := nullif(p_buffer->>'campaign_step', '')::integer;
  v_binding uuid := nullif(p_buffer->>'channel_binding_id', '')::uuid;
  v_key text := nullif(p_buffer->>'idempotency_key', '');
  v_campaign_row public.campaigns%ROWTYPE;
  v_revision_row public.campaign_revisions%ROWTYPE;
  v_recipient public.campaign_recipients%ROWTYPE;
  v_template public.message_templates%ROWTYPE;
  v_consent public.contact_consents%ROWTYPE;
  v_existing public.lead_buffer%ROWTYPE;
  v_policy jsonb;
  v_hour_limit integer;
  v_day_limit integer;
  v_total_limit integer;
  v_hold_hours integer;
  v_result jsonb;
BEGIN
  IF v_persona IS NULL OR v_lead IS NULL OR v_campaign IS NULL OR
     v_recipient_id IS NULL OR v_revision IS NULL OR v_binding IS NULL OR
     v_key IS NULL OR v_step IS DISTINCT FROM 1 OR
     p_buffer->>'message_origin' IS DISTINCT FROM 'campaign' OR
     p_buffer->>'direction' IS DISTINCT FROM 'outbound' OR
     p_message->>'direction' IS DISTINCT FROM 'outbound' OR
     p_message->>'lead_id' IS DISTINCT FROM v_lead::text OR
     p_message->>'channel_binding_id' IS DISTINCT FROM v_binding::text OR
     p_message->>'campaign_id' IS DISTINCT FROM v_campaign::text OR
     p_message->>'campaign_revision' IS DISTINCT FROM v_revision::text OR
     p_message->>'campaign_recipient_id' IS DISTINCT FROM v_recipient_id::text THEN
    RAISE EXCEPTION 'invalid campaign admission envelope' USING ERRCODE = '22023';
  END IF;

  -- All campaigns for one persona compete for the same hourly/day capacity.
  PERFORM pg_advisory_xact_lock(hashtextextended(v_persona::text, 64157));
  SELECT * INTO v_existing FROM public.lead_buffer WHERE idempotency_key = v_key;
  IF FOUND THEN
    IF v_existing.persona_id IS DISTINCT FROM v_persona OR
       v_existing.lead_ref IS DISTINCT FROM v_lead OR
       v_existing.campaign_id IS DISTINCT FROM v_campaign OR
       v_existing.campaign_recipient_id IS DISTINCT FROM v_recipient_id THEN
      RAISE EXCEPTION 'campaign idempotency key belongs to another recipient' USING ERRCODE = '23514';
    END IF;
    RETURN jsonb_build_object('admitted', true, 'deduplicated', true,
      'buffer_id', v_existing.id, 'status', v_existing.status);
  END IF;

  SELECT * INTO v_campaign_row FROM public.campaigns WHERE id = v_campaign FOR UPDATE;
  SELECT * INTO v_revision_row FROM public.campaign_revisions
    WHERE campaign_id = v_campaign AND revision = v_revision;
  SELECT * INTO v_recipient FROM public.campaign_recipients WHERE id = v_recipient_id FOR UPDATE;
  IF v_campaign_row.id IS NULL OR v_revision_row.id IS NULL OR v_recipient.id IS NULL OR
     v_campaign_row.persona_id <> v_persona OR v_revision_row.persona_id <> v_persona OR
     v_recipient.persona_id <> v_persona OR v_recipient.lead_id <> v_lead OR
     v_recipient.campaign_id <> v_campaign OR v_recipient.campaign_revision <> v_revision OR
     v_revision_row.provider IS DISTINCT FROM v_campaign_row.provider OR
     v_revision_row.audience_id IS DISTINCT FROM v_campaign_row.audience_id OR
     v_campaign_row.current_revision <> v_revision OR
     v_campaign_row.status NOT IN ('draft', 'validated', 'running') OR
     v_recipient.sequence_status <> 'eligible' OR
     v_recipient.suppression_status <> 'none' OR
     v_recipient.contact_status <> 'valid' OR
     v_recipient.commercial_attempt_count <> 0 OR
     v_recipient.policy_checksum IS DISTINCT FROM p_buffer->>'policy_checksum' THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'recipient_or_revision_changed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.leads
    WHERE id = v_lead AND persona_id = v_persona AND coalesce(ai_paused, false) = false) OR
     NOT EXISTS (SELECT 1 FROM public.audiences
       WHERE id = v_revision_row.audience_id AND persona_id = v_persona) OR
     NOT EXISTS (SELECT 1 FROM public.lead_audience_memberships
       WHERE lead_id = v_lead AND audience_id = v_revision_row.audience_id) OR
     NOT EXISTS (SELECT 1 FROM public.workflow_bindings
       WHERE id = v_binding AND persona_id = v_persona AND active = true
         AND provider = v_campaign_row.provider
         AND coalesce((metadata->>'safety_paused')::boolean, false) = false
         AND connection_status IN ('connected', 'open')) THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'lead_or_binding_changed');
  END IF;

  SELECT * INTO v_consent FROM public.contact_consents
    WHERE persona_id = v_persona AND lead_id = v_lead AND channel = 'whatsapp'
      AND purpose = v_revision_row.purpose
    ORDER BY effective_at DESC, created_at DESC LIMIT 1;
  IF v_consent.status IN ('revoked', 'refused', 'review_required') OR
     (v_campaign_row.campaign_kind = 'promotional' AND
       (v_consent.id IS NULL OR v_consent.status <> 'granted' OR
        (v_consent.valid_until IS NOT NULL AND v_consent.valid_until <= now()))) THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'consent_changed');
  END IF;

  IF v_revision_row.template_id IS NOT NULL THEN
    SELECT * INTO v_template FROM public.message_templates WHERE id = v_revision_row.template_id;
    IF v_template.id IS NULL OR v_template.persona_id <> v_persona OR
       v_template.provider <> v_campaign_row.provider OR v_template.status <> 'active' OR
       (v_campaign_row.provider = 'meta_cloud' AND
        (v_template.meta_approval_status <> 'approved' OR v_template.meta_template_id IS NULL OR
         p_buffer->'payload'->'template'->>'name' IS DISTINCT FROM v_template.meta_template_name OR
         p_buffer->'payload'->'template'->>'language' IS DISTINCT FROM v_template.meta_template_language)) THEN
      RETURN jsonb_build_object('admitted', false, 'reason', 'template_changed');
    END IF;
  ELSIF v_campaign_row.provider = 'meta_cloud' THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'template_required');
  END IF;

  v_policy := coalesce(v_revision_row.policy_snapshot, '{}'::jsonb);
  v_hour_limit := least(greatest(coalesce((v_policy->>'hourly_send_limit')::integer, 20), 1), 20);
  v_day_limit := least(greatest(coalesce((v_policy->>'daily_send_limit')::integer, 100), 1), 100);
  v_total_limit := least(
    greatest(coalesce((v_policy->>'max_total_sends')::integer, 500), 1),
    greatest(coalesce((v_policy->>'max_unique_leads')::integer, 400), 1));
  v_hold_hours := greatest(coalesce((v_policy->>'response_hold_hours')::integer, 24), 1);
  IF (SELECT count(*) FROM public.lead_buffer WHERE persona_id = v_persona
      AND message_origin = 'campaign' AND direction = 'outbound'
      AND created_at > now() - interval '1 hour') >= v_hour_limit OR
     (SELECT count(*) FROM public.lead_buffer WHERE persona_id = v_persona
      AND message_origin = 'campaign' AND direction = 'outbound'
      AND created_at >= date_trunc('day', now() AT TIME ZONE 'America/Sao_Paulo')
        AT TIME ZONE 'America/Sao_Paulo') >= v_day_limit OR
     (SELECT count(*) FROM public.lead_buffer WHERE campaign_id = v_campaign
      AND direction = 'outbound') >= v_total_limit THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'capacity_exhausted');
  END IF;

  -- One initial campaign message per lead, with no overlap with an active
  -- reactivation or a response that arrived after the draft was frozen.
  IF EXISTS (SELECT 1 FROM public.lead_buffer WHERE persona_id = v_persona
      AND lead_ref = v_lead AND message_origin = 'campaign' AND direction = 'outbound') OR
     EXISTS (SELECT 1 FROM public.lead_buffer WHERE persona_id = v_persona
      AND lead_ref = v_lead AND message_origin = 'proactive' AND direction = 'outbound'
      AND (status IN ('awaiting_proof', 'preview_ready', 'pending_send', 'buffered', 'retry', 'processing')
        OR created_at > now() - make_interval(hours => v_hold_hours))) OR
     EXISTS (SELECT 1 FROM public.messages WHERE lead_id = v_lead
      AND direction = 'inbound' AND created_at > v_revision_row.created_at) OR
     v_recipient.response_received_at IS NOT NULL OR v_recipient.retries_stopped_at IS NOT NULL THEN
    RETURN jsonb_build_object('admitted', false, 'reason', 'lead_has_new_activity');
  END IF;

  v_result := public.enqueue_whatsapp_envelope(p_buffer, p_message);
  IF coalesce((v_result->>'deduplicated')::boolean, false) THEN
    RETURN jsonb_build_object('admitted', true, 'deduplicated', true,
      'buffer_id', v_result->>'buffer_id', 'status', v_result->>'status');
  END IF;
  UPDATE public.campaign_recipients SET sequence_status = 'queued',
    commercial_attempt_count = 1, last_commercial_attempt_at = now(), updated_at = now()
    WHERE id = v_recipient_id;
  RETURN v_result || jsonb_build_object('admitted', true, 'deduplicated', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.authorize_campaign_dispatch_v1(p_buffer_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_campaign public.campaigns%ROWTYPE;
  v_revision public.campaign_revisions%ROWTYPE;
  v_recipient public.campaign_recipients%ROWTYPE;
  v_template public.message_templates%ROWTYPE;
  v_consent public.contact_consents%ROWTYPE;
BEGIN
  SELECT * INTO v_buffer FROM public.lead_buffer WHERE id = p_buffer_id;
  IF v_buffer.id IS NULL OR v_buffer.message_origin <> 'campaign' OR
     v_buffer.direction <> 'outbound' OR v_buffer.status <> 'processing' THEN
    RETURN false;
  END IF;
  SELECT * INTO v_campaign FROM public.campaigns WHERE id = v_buffer.campaign_id;
  SELECT * INTO v_revision FROM public.campaign_revisions
    WHERE campaign_id = v_buffer.campaign_id AND revision = v_buffer.campaign_revision;
  SELECT * INTO v_recipient FROM public.campaign_recipients
    WHERE id = v_buffer.campaign_recipient_id;
  IF v_campaign.id IS NULL OR v_revision.id IS NULL OR v_recipient.id IS NULL OR
     v_campaign.persona_id <> v_buffer.persona_id OR
     v_revision.provider IS DISTINCT FROM v_campaign.provider OR
     v_campaign.status NOT IN ('draft', 'validated', 'running') OR
     v_campaign.current_revision <> v_buffer.campaign_revision OR
     v_recipient.sequence_status <> 'queued' OR
     v_recipient.suppression_status <> 'none' OR
     v_recipient.response_received_at IS NOT NULL OR
     v_recipient.retries_stopped_at IS NOT NULL OR
     NOT EXISTS (SELECT 1 FROM public.workflow_bindings
       WHERE id = v_buffer.channel_binding_id AND active = true
         AND persona_id = v_buffer.persona_id AND provider = v_campaign.provider
         AND coalesce((metadata->>'safety_paused')::boolean, false) = false
         AND connection_status IN ('connected', 'open')) OR
     NOT EXISTS (SELECT 1 FROM public.leads WHERE id = v_buffer.lead_ref
       AND persona_id = v_buffer.persona_id AND coalesce(ai_paused, false) = false) OR
     NOT EXISTS (SELECT 1 FROM public.lead_audience_memberships
       WHERE lead_id = v_buffer.lead_ref AND audience_id = v_revision.audience_id) OR
     EXISTS (SELECT 1 FROM public.messages WHERE lead_id = v_buffer.lead_ref
       AND direction = 'inbound' AND created_at > v_buffer.created_at) OR
     EXISTS (SELECT 1 FROM public.lead_buffer WHERE persona_id = v_buffer.persona_id
       AND lead_ref = v_buffer.lead_ref AND message_origin = 'proactive'
       AND direction = 'outbound' AND created_at > v_buffer.created_at) THEN
    RETURN false;
  END IF;
  SELECT * INTO v_consent FROM public.contact_consents
    WHERE persona_id = v_buffer.persona_id AND lead_id = v_buffer.lead_ref
      AND channel = 'whatsapp' AND purpose = v_revision.purpose
    ORDER BY effective_at DESC, created_at DESC LIMIT 1;
  IF v_consent.status IN ('revoked', 'refused', 'review_required') OR
     (v_campaign.campaign_kind = 'promotional' AND
       (v_consent.id IS NULL OR v_consent.status <> 'granted' OR
        (v_consent.valid_until IS NOT NULL AND v_consent.valid_until <= now()))) THEN
    RETURN false;
  END IF;
  IF v_revision.template_id IS NOT NULL THEN
    SELECT * INTO v_template FROM public.message_templates WHERE id = v_revision.template_id;
    IF v_template.id IS NULL OR v_template.persona_id <> v_buffer.persona_id OR
       v_template.provider <> v_campaign.provider OR v_template.status <> 'active' OR
       (v_campaign.provider = 'meta_cloud' AND
        (v_template.meta_approval_status <> 'approved' OR v_template.meta_template_id IS NULL OR
         v_buffer.payload->'template'->>'name' IS DISTINCT FROM v_template.meta_template_name OR
         v_buffer.payload->'template'->>'language' IS DISTINCT FROM v_template.meta_template_language)) THEN
      RETURN false;
    END IF;
  ELSIF v_campaign.provider = 'meta_cloud' THEN
    RETURN false;
  END IF;
  RETURN true;
END;
$$;

-- A reactivation can originate from a retired binding. Its final dispatch
-- check must observe replies on every binding of the same lead/persona.
CREATE OR REPLACE FUNCTION public.reactivation_dispatch_blocked_v1(p_buffer_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_source public.lead_buffer%ROWTYPE;
  v_source_id uuid;
BEGIN
  SELECT * INTO v_buffer FROM public.lead_buffer WHERE id = p_buffer_id;
  IF v_buffer.id IS NULL OR v_buffer.message_origin IS DISTINCT FROM 'proactive' THEN
    RETURN false;
  END IF;
  v_source_id := coalesce(v_buffer.queue_parent_buffer_id,
    nullif(v_buffer.payload->>'reactivation_source_buffer_id', '')::uuid);
  IF v_source_id IS NULL THEN
    RETURN false;
  END IF;
  SELECT * INTO v_source FROM public.lead_buffer WHERE id = v_source_id;
  IF v_source.id IS NULL OR v_source.lead_ref IS DISTINCT FROM v_buffer.lead_ref OR
     v_source.persona_id IS DISTINCT FROM v_buffer.persona_id OR
     v_source.direction <> 'outbound' OR
     v_source.status NOT IN ('sent', 'delivered', 'read') OR
     NOT EXISTS (SELECT 1 FROM public.leads WHERE id = v_buffer.lead_ref
       AND persona_id = v_buffer.persona_id AND coalesce(ai_paused, false) = false
       AND coalesce(handoff_level, 'none') = 'none') OR
     EXISTS (SELECT 1 FROM public.contact_consents c
       WHERE c.lead_id = v_buffer.lead_ref AND c.persona_id = v_buffer.persona_id
         AND c.channel = 'whatsapp' AND c.status IN ('refused', 'revoked')
         AND (c.valid_until IS NULL OR c.valid_until > now())) OR
     EXISTS (SELECT 1 FROM public.lead_buffer inbound
       WHERE inbound.direction = 'inbound' AND inbound.lead_ref = v_buffer.lead_ref
         AND inbound.persona_id = v_buffer.persona_id
         AND inbound.created_at > v_source.created_at) OR
     NOT EXISTS (SELECT 1 FROM public.conversation_turn_proofs proof
       JOIN public.graph_publications publication
         ON publication.id = proof.publication_id
        AND publication.persona_id = v_buffer.persona_id
        AND publication.status = 'active'
       WHERE proof.outbound_id = v_buffer.id::text
         AND coalesce((proof.proof_result->>'delivery_authorized')::boolean,
                      (proof.proof_result->>'valid')::boolean, false)) THEN
    RETURN true;
  END IF;
  RETURN false;
END;
$$;

REVOKE ALL ON FUNCTION public.admit_campaign_outbound_v1(jsonb,jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.authorize_campaign_dispatch_v1(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reactivation_dispatch_blocked_v1(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admit_campaign_outbound_v1(jsonb,jsonb)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.authorize_campaign_dispatch_v1(uuid)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.reactivation_dispatch_blocked_v1(uuid)
  TO service_role;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brain_transport') THEN
    GRANT EXECUTE ON FUNCTION public.admit_campaign_outbound_v1(jsonb,jsonb)
      TO brain_transport;
    GRANT EXECUTE ON FUNCTION public.authorize_campaign_dispatch_v1(uuid)
      TO brain_transport;
    GRANT EXECUTE ON FUNCTION public.reactivation_dispatch_blocked_v1(uuid)
      TO brain_transport;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
