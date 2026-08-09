-- Splits the previous binary ai_paused gate into a graded handoff_level:
-- 'none' (normal operation), 'partial' (a handoff-worthy turn fired but the
-- lead's minimum registration -- nome_cliente + servico -- isn't known yet,
-- this turn or from an earlier session, so the AI keeps running: still
-- replies, still extracts/updates facts), 'full' (today's exact behavior:
-- AI fully silenced, inbound lead_buffer rows parked as waiting_human,
-- needs a manual resume). See conversation_runtime.commit() for where the
-- level is computed, and agents_service.py for pause/resume/acknowledge.
--
-- ai_paused becomes a generated column (same pattern as
-- knowledge_rag_chunks.search_document in migration 093) so every existing
-- reader (whatsapp_dispatch_worker's Gate 1, /process's Gate 1, the
-- dashboard badge) keeps working unchanged -- only writers move to
-- handoff_level from here on.
ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS handoff_level text NOT NULL DEFAULT 'none'
    CHECK (handoff_level IN ('none', 'partial', 'full'));

-- Scoped to ai_paused=true only -- everything else already correctly
-- defaults to 'none'. The lead/channel-binding integrity trigger
-- (migration 067, trg_enforce_lead_channel_binding) fires on ANY update to
-- ANY column on public.leads with no WHEN guard, so a blanket UPDATE here
-- would re-validate every row's channel_binding_id against its persona_id
-- and abort the whole migration over pre-existing data drift this backfill
-- has no business validating. Disabled for this one statement only, inside
-- this migration's own transaction, so it's back on before the transaction
-- commits either way.
ALTER TABLE public.leads DISABLE TRIGGER trg_enforce_lead_channel_binding;
UPDATE public.leads SET handoff_level = 'full' WHERE ai_paused = true;
ALTER TABLE public.leads ENABLE TRIGGER trg_enforce_lead_channel_binding;

ALTER TABLE public.leads DROP COLUMN ai_paused;
ALTER TABLE public.leads
  ADD COLUMN ai_paused boolean GENERATED ALWAYS AS (handoff_level = 'full') STORED;

-- Every existing writer of ai_paused=true now writes handoff_level instead.
-- p_level defaults to 'full' so every pre-existing caller (portal manual
-- handoff, fail-safe handoff, safety-violation guard) keeps its exact prior
-- behavior; only conversation_runtime.commit()'s graph-driven handoff path
-- passes an explicit 'partial' when registration is incomplete.
CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead(
  p_lead_ref bigint,
  p_level text DEFAULT 'full'
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
begin
  IF p_level NOT IN ('partial', 'full') THEN
    RAISE EXCEPTION 'invalid handoff level: %', p_level;
  END IF;

  update public.leads
  set handoff_level = p_level, updated_at = now()
  where id = p_lead_ref;

  IF p_level = 'full' THEN
    update public.lead_buffer
    set status = 'waiting_human',
        locked_at = null,
        locked_by = null,
        payload = COALESCE(payload, '{}'::jsonb)
          - 'decision_attempt_started_at' - 'decision_attempt_worker'
          - 'provider_attempt_started_at' - 'provider_attempt_worker',
        updated_at = now()
    where lead_ref = p_lead_ref
      and direction = 'inbound'
      and status in ('received', 'buffered', 'processing', 'pending_send', 'retry');
  END IF;
end;
$$;

CREATE OR REPLACE FUNCTION public.handoff_whatsapp_lead_state(
  p_lead_ref bigint,
  p_metadata jsonb,
  p_stage text,
  p_level text DEFAULT 'full'
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
BEGIN
  IF p_level NOT IN ('partial', 'full') THEN
    RAISE EXCEPTION 'invalid handoff level: %', p_level;
  END IF;

  UPDATE public.leads
     SET handoff_level = p_level,
         metadata = COALESCE(p_metadata, metadata, '{}'::jsonb),
         stage = COALESCE(NULLIF(p_stage, ''), stage),
         updated_at = now()
   WHERE id = p_lead_ref;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'lead not found: %', p_lead_ref;
  END IF;

  IF p_level = 'full' THEN
    UPDATE public.lead_buffer
       SET status = 'waiting_human',
           locked_at = null,
           locked_by = null,
           payload = COALESCE(payload, '{}'::jsonb)
             - 'decision_attempt_started_at' - 'decision_attempt_worker'
             - 'provider_attempt_started_at' - 'provider_attempt_worker',
           updated_at = now()
     WHERE lead_ref = p_lead_ref
       AND direction = 'inbound'
       AND status IN (
         'received', 'buffered', 'processing', 'pending_send', 'retry'
       );
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_whatsapp_safety_violation(
  p_binding_id uuid,
  p_lead_ref bigint,
  p_violation_key text,
  p_reason text,
  p_level text DEFAULT 'full'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_persona_id uuid;
  v_count integer;
  v_paused boolean := false;
BEGIN
  IF p_level NOT IN ('partial', 'full') THEN
    RAISE EXCEPTION 'invalid handoff level: %', p_level;
  END IF;

  SELECT persona_id
    INTO v_persona_id
    FROM public.workflow_bindings
   WHERE id = p_binding_id
   FOR UPDATE;

  IF v_persona_id IS NULL THEN
    RAISE EXCEPTION 'workflow binding not found';
  END IF;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  )
  VALUES (
    'whatsapp.safety_violation',
    'workflow_binding',
    p_binding_id,
    v_persona_id,
    jsonb_build_object(
      'violation_key', p_violation_key,
      'reason', p_reason,
      'lead_ref', p_lead_ref
    ),
    'error',
    'whatsapp.safety'
  );

  IF p_lead_ref IS NOT NULL THEN
    UPDATE public.leads
       SET handoff_level = p_level,
           updated_at = now()
     WHERE id = p_lead_ref
       AND persona_id = v_persona_id;

    IF p_level = 'full' THEN
      UPDATE public.lead_buffer
         SET status = 'waiting_human',
             locked_at = NULL,
             locked_by = NULL,
             payload = COALESCE(payload, '{}'::jsonb)
               - 'decision_attempt_started_at' - 'decision_attempt_worker'
               - 'provider_attempt_started_at' - 'provider_attempt_worker',
             updated_at = now()
       WHERE lead_ref = p_lead_ref
         AND channel_binding_id = p_binding_id
         AND status IN (
           'received', 'buffered', 'processing', 'pending_send', 'retry'
         );
    END IF;
  END IF;

  SELECT count(DISTINCT payload->>'violation_key')
    INTO v_count
    FROM public.system_events
   WHERE event_type = 'whatsapp.safety_violation'
     AND entity_type = 'workflow_binding'
     AND entity_id = p_binding_id::text
     AND created_at >= now() - interval '5 minutes';

  IF v_count >= 3 THEN
    UPDATE public.workflow_bindings
       SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
             'safety_paused', true,
             'safety_paused_at', now(),
             'safety_reason', p_reason,
             'safety_violation_count', v_count
           ),
           connection_status = 'safety_paused',
           updated_at = now()
     WHERE id = p_binding_id;
    v_paused := true;
  END IF;

  RETURN jsonb_build_object(
    'binding_id', p_binding_id,
    'violation_count', v_count,
    'safety_paused', v_paused
  );
END;
$$;

-- Clears a v3 conversation ledger's branch anchor without touching
-- collected facts. Used by resume-ai: resuming only clears handoff_level,
-- but if the ledger is still anchored to a branch whose handoff_rule keeps
-- matching (e.g. qualification_complete stays true because the facts are
-- still there), the very next inbound message re-authorizes handoff
-- immediately. Clearing active_branch_node_id lets the next turn
-- re-classify from scratch; conversation_facts (name, vehicle model, etc.)
-- are left untouched so collected data survives.
CREATE OR REPLACE FUNCTION public.reset_conversation_ledger_branch_v3(
  p_persona_id uuid,
  p_lead_ref bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_ledger public.conversation_ledgers%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_persona_id::text || ':' || p_lead_ref::text));

  SELECT * INTO v_ledger FROM public.conversation_ledgers
  WHERE persona_id = p_persona_id AND lead_ref = p_lead_ref
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('state', 'noop', 'reason', 'ledger_not_found');
  END IF;

  UPDATE public.conversation_ledgers SET
    active_branch_node_id = NULL,
    asked_question_node_ids = '{}',
    revision = revision + 1,
    updated_at = now()
  WHERE id = v_ledger.id
  RETURNING * INTO v_ledger;

  RETURN jsonb_build_object(
    'state', 'reset', 'ledger_id', v_ledger.id, 'revision', v_ledger.revision
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead(bigint, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.handoff_whatsapp_lead_state(bigint, jsonb, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_whatsapp_safety_violation(uuid, bigint, text, text, text) TO service_role;

REVOKE ALL ON FUNCTION public.reset_conversation_ledger_branch_v3(uuid, bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reset_conversation_ledger_branch_v3(uuid, bigint)
  TO service_role;
