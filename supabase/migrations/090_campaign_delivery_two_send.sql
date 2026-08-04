-- Campaign delivery 2: real sending groundwork. Additive only. Sending itself
-- (the /send endpoint, provider template payloads, worker dispatch branch)
-- lands in application code on top of this schema; this migration only adds
-- the durable surfaces that code needs: a lightweight per-provider template
-- model, revision traceability back to the template used, and one new
-- terminal recipient state for a synchronous admission rejection (as opposed
-- to the async outbox lifecycle already tracked on lead_buffer/messages).
--
-- Both Meta and Evolution campaign sends are authorized the same way:
-- explicit lead selection/import, the existing consent + eligibility rules,
-- the frozen preview, and a live revalidation immediately before enqueueing.
-- There is deliberately no separate allowlist or recipient cap for either
-- provider beyond that pipeline.

CREATE TABLE IF NOT EXISTS public.message_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('meta_cloud', 'evolution_baileys')),
  template_key text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),

  -- Meta-only fields (NULL when provider = evolution_baileys).
  meta_template_name text,
  meta_template_language text,
  meta_template_category text CHECK (
    meta_template_category IS NULL
    OR meta_template_category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')
  ),
  meta_component_schema jsonb NOT NULL DEFAULT '[]'::jsonb,

  -- Evolution-only fields (NULL when provider = meta_cloud). Evolution has
  -- no Meta-style approval; this is a free-text body with {{var}} placeholders.
  evolution_body_template text,
  evolution_variables jsonb NOT NULL DEFAULT '[]'::jsonb,

  created_by_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (persona_id, provider, template_key),
  CHECK (
    (provider = 'meta_cloud' AND meta_template_name IS NOT NULL AND meta_template_language IS NOT NULL)
    OR
    (provider = 'evolution_baileys' AND evolution_body_template IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_message_templates_persona_provider
  ON public.message_templates(persona_id, provider, status);

ALTER TABLE public.campaign_revisions
  ADD COLUMN IF NOT EXISTS template_id uuid REFERENCES public.message_templates(id) ON DELETE SET NULL;

ALTER TABLE public.campaign_recipients DROP CONSTRAINT IF EXISTS campaign_recipients_sequence_status_check;
ALTER TABLE public.campaign_recipients
  ADD CONSTRAINT campaign_recipients_sequence_status_check
  CHECK (sequence_status IN (
    'selected', 'eligible', 'blocked', 'queued', 'send_failed', 'awaiting_reply',
    'retry_scheduled', 'responded', 'completed', 'cancelled'
  ));

-- message_templates only references personas directly (no audience/campaign/
-- lead cross-references like migration 087's tables), so the FK constraint
-- above is sufficient scope enforcement; no additional trigger is needed.

-- All operational campaign-send data is backend-only, matching the rest of
-- the campaign schema: the FastAPI service_role is the sole Data API
-- consumer, browser sessions use the authenticated API.
ALTER TABLE public.message_templates ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.message_templates FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.message_templates TO service_role;

-- create_campaign_draft_v1 (migration 087) does an explicit column-by-column
-- insert into campaign_revisions, so the new template_id column above is
-- never populated through it even though a caller may now pass one. Reissue
-- the function with template_id added; everything else is unchanged from 087.
CREATE OR REPLACE FUNCTION public.create_campaign_draft_v1(
  p_campaign jsonb,
  p_revision jsonb,
  p_import_ids jsonb,
  p_recipients jsonb,
  p_event jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_campaign_id uuid := (p_campaign->>'id')::uuid;
  v_revision_id uuid := (p_revision->>'id')::uuid;
  v_existing_id uuid;
BEGIN
  SELECT id INTO v_existing_id
  FROM public.campaigns
  WHERE idempotency_key = p_campaign->>'idempotency_key';
  IF v_existing_id IS NOT NULL THEN
    RETURN jsonb_build_object('campaign_id', v_existing_id, 'deduplicated', true);
  END IF;

  INSERT INTO public.campaigns (
    id, persona_id, slug, name, status, format, metadata, created_at, updated_at,
    campaign_kind, purpose, channel, provider, audience_id, current_revision,
    idempotency_key, reason, created_by_user_id
  ) VALUES (
    v_campaign_id, (p_campaign->>'persona_id')::uuid, p_campaign->>'slug',
    p_campaign->>'name', p_campaign->>'status', p_campaign->>'format',
    COALESCE(p_campaign->'metadata', '{}'::jsonb),
    (p_campaign->>'created_at')::timestamptz,
    (p_campaign->>'updated_at')::timestamptz,
    p_campaign->>'campaign_kind', p_campaign->>'purpose', p_campaign->>'channel',
    p_campaign->>'provider', (p_campaign->>'audience_id')::uuid,
    (p_campaign->>'current_revision')::integer, p_campaign->>'idempotency_key',
    p_campaign->>'reason', NULLIF(p_campaign->>'created_by_user_id', '')::uuid
  );

  INSERT INTO public.campaign_revisions (
    id, campaign_id, persona_id, revision, audience_id, campaign_kind, purpose,
    objective, channel, provider, graph_version, graph_checksum,
    audience_snapshot, content_snapshot, policy_snapshot, policy_checksum,
    revision_checksum, status,
    created_by_user_id, reason, created_at, template_id
  ) VALUES (
    v_revision_id, v_campaign_id, (p_revision->>'persona_id')::uuid,
    (p_revision->>'revision')::integer, (p_revision->>'audience_id')::uuid,
    p_revision->>'campaign_kind', p_revision->>'purpose', p_revision->>'objective',
    p_revision->>'channel', p_revision->>'provider',
    NULLIF(p_revision->>'graph_version', '')::integer, p_revision->>'graph_checksum',
    COALESCE(p_revision->'audience_snapshot', '{}'::jsonb),
    COALESCE(p_revision->'content_snapshot', '{}'::jsonb),
    COALESCE(p_revision->'policy_snapshot', '{}'::jsonb),
    p_revision->>'policy_checksum', p_revision->>'revision_checksum',
    p_revision->>'status',
    NULLIF(p_revision->>'created_by_user_id', '')::uuid,
    p_revision->>'reason', (p_revision->>'created_at')::timestamptz,
    NULLIF(p_revision->>'template_id', '')::uuid
  );

  INSERT INTO public.campaign_revision_imports (campaign_revision_id, import_batch_id)
  SELECT v_revision_id, value::uuid
  FROM jsonb_array_elements_text(COALESCE(p_import_ids, '[]'::jsonb));

  INSERT INTO public.campaign_recipients (
    campaign_id, campaign_revision_id, campaign_revision, lead_id, persona_id,
    applicable_consent_id, consent_status, sequence_status, suppression_status,
    contact_status, blocked_reason, policy_checksum
  )
  SELECT
    v_campaign_id, v_revision_id, (p_revision->>'revision')::integer,
    (item->>'lead_id')::bigint,
    (p_campaign->>'persona_id')::uuid,
    NULLIF(item->>'applicable_consent_id', '')::uuid,
    item->>'consent_status', item->>'sequence_status',
    item->>'suppression_status', item->>'contact_status',
    item->>'blocked_reason', p_revision->>'policy_checksum'
  FROM jsonb_array_elements(COALESCE(p_recipients, '[]'::jsonb)) AS item;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'campaign_draft_created', 'campaign', v_campaign_id,
    (p_campaign->>'persona_id')::uuid, COALESCE(p_event, '{}'::jsonb),
    'info', 'campaigns.create'
  );

  RETURN jsonb_build_object('campaign_id', v_campaign_id, 'deduplicated', false);
END;
$$;

GRANT EXECUTE ON FUNCTION public.create_campaign_draft_v1(jsonb, jsonb, jsonb, jsonb, jsonb)
  TO service_role;

NOTIFY pgrst, 'reload schema';
