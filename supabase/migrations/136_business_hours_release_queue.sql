-- Two structurally different scenarios accumulate WhatsApp reply backlog and,
-- today, release it all at once the instant someone fixes the underlying
-- cause -- including at 3am: (1) a workflow_binding going safety_paused
-- diverts inbound/outbound to lead_buffer.status='waiting_human', and no
-- function anywhere clears the pause or bulk-requeues that backlog (only
-- requeue_waiting_human_whatsapp_buffer, per-lead); (2) a deploy that leaves
-- `workers` stopped for hours (KEEP_WORKERS_PAUSED) leaves rows in
-- received/buffered/retry with a stale available_at that is already <= now()
-- the moment the worker restarts, so claim_whatsapp_buffer bursts up to
-- p_limit rows every 2s cycle. Confirmed live incident 2026-09-08/09: the
-- tock-fatal binding sat safety_paused ~24h with three real customers
-- unanswered in waiting_human.
--
-- lead_buffer.available_at is the only scheduling primitive the platform
-- has (no cron exists anywhere for messaging). This migration adds a
-- business-hours-aware way to rewrite it, plus a durable batch/item record
-- so a dashboard can show what is queued and let an operator pause or
-- reschedule an individual item -- lead_buffer rows are transient/mutating,
-- the wrong place to hang that state.

CREATE TABLE IF NOT EXISTS public.release_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid REFERENCES public.personas(id) ON DELETE CASCADE,
  scope text NOT NULL CHECK (scope IN ('safety_paused_binding', 'deploy_pause')),
  binding_id uuid REFERENCES public.workflow_bindings(id) ON DELETE SET NULL,
  release_sha text,
  status text NOT NULL DEFAULT 'releasing' CHECK (status IN (
    'releasing', 'registered', 'completed', 'cancelled'
  )),
  timezone text NOT NULL DEFAULT 'America/Sao_Paulo',
  window_start_local time NOT NULL DEFAULT '08:00',
  window_end_local time NOT NULL DEFAULT '20:00',
  stagger_seconds integer NOT NULL DEFAULT 4 CHECK (stagger_seconds > 0),
  item_count integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
  reason text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (scope <> 'safety_paused_binding' OR binding_id IS NOT NULL),
  CHECK (window_start_local < window_end_local)
);

CREATE INDEX IF NOT EXISTS idx_release_batches_persona_status
  ON public.release_batches(persona_id, status);
CREATE INDEX IF NOT EXISTS idx_release_batches_binding
  ON public.release_batches(binding_id)
  WHERE binding_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.release_batch_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES public.release_batches(id) ON DELETE CASCADE,
  lead_buffer_id uuid NOT NULL REFERENCES public.lead_buffer(id) ON DELETE CASCADE,
  lead_ref bigint,
  persona_id uuid,
  direction text NOT NULL,
  captured_status text NOT NULL,
  captured_available_at timestamptz NOT NULL,
  computed_available_at timestamptz NOT NULL,
  paused boolean NOT NULL DEFAULT false,
  paused_at timestamptz,
  paused_by uuid,
  pause_reason text,
  override_available_at timestamptz,
  override_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (batch_id, lead_buffer_id)
);

-- release_batch_items intentionally carries no "sent/delivered" status of its
-- own -- whether an item actually went out is always read live off
-- lead_buffer.status via lead_buffer_id (never deleted, only status-flipped),
-- so this table can't drift from what really happened.
CREATE INDEX IF NOT EXISTS idx_release_batch_items_batch
  ON public.release_batch_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_release_batch_items_lead_buffer
  ON public.release_batch_items(lead_buffer_id);
CREATE INDEX IF NOT EXISTS idx_release_batch_items_paused
  ON public.release_batch_items(batch_id)
  WHERE paused = true;

-- Given a base timestamp and a 0-based position in a batch, return the next
-- timestamptz inside [p_window_start, p_window_end) local time in p_tz,
-- staggered p_index * p_stagger_seconds apart. A batch larger than one
-- window rolls forward across multiple days -- expected for a big backlog,
-- not a bug.
CREATE OR REPLACE FUNCTION public.next_business_hours_slot(
  p_from timestamptz,
  p_index integer,
  p_stagger_seconds integer DEFAULT 4,
  p_window_start time DEFAULT '08:00',
  p_window_end time DEFAULT '20:00',
  p_tz text DEFAULT 'America/Sao_Paulo'
)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_local timestamp;
  v_anchor_local timestamp;
  v_anchor_date date;
  v_window_seconds integer;
  v_seconds_into_window integer;
  v_total_seconds integer;
  v_day_offset integer;
BEGIN
  IF p_index < 0 THEN
    RAISE EXCEPTION 'p_index must be >= 0' USING ERRCODE = '22023';
  END IF;
  IF p_stagger_seconds <= 0 THEN
    RAISE EXCEPTION 'p_stagger_seconds must be > 0' USING ERRCODE = '22023';
  END IF;
  IF p_window_start >= p_window_end THEN
    RAISE EXCEPTION 'p_window_start must be before p_window_end' USING ERRCODE = '22023';
  END IF;

  v_local := p_from AT TIME ZONE p_tz;

  IF v_local::time < p_window_start THEN
    v_anchor_local := v_local::date + p_window_start;
  ELSIF v_local::time < p_window_end THEN
    v_anchor_local := v_local;
  ELSE
    v_anchor_local := (v_local::date + 1) + p_window_start;
  END IF;

  v_window_seconds := EXTRACT(EPOCH FROM (p_window_end - p_window_start))::integer;
  v_seconds_into_window := EXTRACT(EPOCH FROM (v_anchor_local::time - p_window_start))::integer;
  v_total_seconds := v_seconds_into_window + (p_index * p_stagger_seconds);

  v_day_offset := v_total_seconds / v_window_seconds;
  v_total_seconds := v_total_seconds % v_window_seconds;
  v_anchor_date := v_anchor_local::date + v_day_offset;

  RETURN (v_anchor_date + p_window_start + make_interval(secs => v_total_seconds)) AT TIME ZONE p_tz;
END;
$$;

-- Registers a release action for a pre-vetted list of lead_buffer ids
-- (the caller is responsible for building that list -- for
-- safety_paused_binding scope that means running each candidate lead through
-- agents_service.resume_answer_window() first, so this bulk path can never
-- resurrect a conversation the per-lead staleness check would leave silent;
-- for deploy_pause scope it's the pre-restart eligible-inbound inventory
-- ops/vps/resume-production-workers.sh already builds).
--
-- For safety_paused_binding scope, clearing the binding's safety_paused flag
-- and scheduling its backlog happen in the same transaction -- deliberately
-- one action, not two, so an operator can't register a release and forget
-- the channel is still paused (the dispatch worker would just divert
-- everything straight back to waiting_human).
CREATE OR REPLACE FUNCTION public.register_release_batch_v1(
  p_persona_id uuid,
  p_scope text,
  p_lead_buffer_ids uuid[],
  p_reason text,
  p_idempotency_key text,
  p_binding_id uuid DEFAULT NULL,
  p_release_sha text DEFAULT NULL,
  p_actor_user_id uuid DEFAULT NULL,
  p_stagger_seconds integer DEFAULT 4,
  p_window_start time DEFAULT '08:00',
  p_window_end time DEFAULT '20:00',
  p_tz text DEFAULT 'America/Sao_Paulo'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_batch_id uuid;
  v_count integer := 0;
  v_idx integer := 0;
  v_slot timestamptz;
  v_row record;
BEGIN
  IF p_scope NOT IN ('safety_paused_binding', 'deploy_pause') THEN
    RAISE EXCEPTION 'unsupported release batch scope' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(btrim(p_idempotency_key), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'idempotency key and reason are required' USING ERRCODE = '22023';
  END IF;
  IF p_scope = 'safety_paused_binding' AND p_binding_id IS NULL THEN
    RAISE EXCEPTION 'safety_paused_binding scope requires p_binding_id' USING ERRCODE = '22023';
  END IF;
  IF p_lead_buffer_ids IS NULL OR array_length(p_lead_buffer_ids, 1) IS NULL THEN
    RAISE EXCEPTION 'p_lead_buffer_ids must not be empty' USING ERRCODE = '22023';
  END IF;

  SELECT id INTO v_batch_id FROM public.release_batches WHERE idempotency_key = p_idempotency_key;
  IF v_batch_id IS NOT NULL THEN
    RETURN jsonb_build_object('batch_id', v_batch_id, 'deduplicated', true);
  END IF;

  IF p_scope = 'safety_paused_binding' THEN
    UPDATE public.workflow_bindings
       SET connection_status = 'connected',
           metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
             'safety_paused', false,
             'safety_resumed_at', now(),
             'safety_resume_reason', p_reason
           ),
           updated_at = now()
     WHERE id = p_binding_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'workflow binding not found' USING ERRCODE = 'P0002';
    END IF;
  END IF;

  INSERT INTO public.release_batches (
    persona_id, scope, binding_id, release_sha, status, timezone,
    window_start_local, window_end_local, stagger_seconds, item_count,
    reason, idempotency_key, created_by
  ) VALUES (
    p_persona_id, p_scope, p_binding_id, p_release_sha, 'releasing', p_tz,
    p_window_start, p_window_end, p_stagger_seconds, 0,
    p_reason, p_idempotency_key, p_actor_user_id
  ) RETURNING id INTO v_batch_id;

  FOR v_row IN
    SELECT b.id, b.status, b.available_at
      FROM public.lead_buffer b
     WHERE b.id = ANY(p_lead_buffer_ids)
       AND b.direction = 'inbound'
       AND b.status IN ('waiting_human', 'received', 'buffered', 'retry')
     ORDER BY b.created_at, b.id
     FOR UPDATE OF b SKIP LOCKED
  LOOP
    v_slot := public.next_business_hours_slot(
      now(), v_idx, p_stagger_seconds, p_window_start, p_window_end, p_tz
    );

    UPDATE public.lead_buffer
       SET status = CASE WHEN v_row.status = 'waiting_human' THEN 'retry' ELSE status END,
           available_at = v_slot,
           locked_at = NULL,
           locked_by = NULL,
           payload = COALESCE(payload, '{}'::jsonb)
             - 'decision_attempt_started_at' - 'decision_attempt_worker'
             - 'provider_attempt_started_at' - 'provider_attempt_worker',
           updated_at = now()
     WHERE id = v_row.id;

    INSERT INTO public.release_batch_items (
      batch_id, lead_buffer_id, lead_ref, persona_id, direction,
      captured_status, captured_available_at, computed_available_at
    )
    SELECT v_batch_id, lb.id, lb.lead_ref, lb.persona_id, lb.direction,
           v_row.status, v_row.available_at, v_slot
      FROM public.lead_buffer lb
     WHERE lb.id = v_row.id;

    v_idx := v_idx + 1;
    v_count := v_count + 1;
  END LOOP;

  UPDATE public.release_batches
     SET item_count = v_count, status = 'registered', updated_at = now()
   WHERE id = v_batch_id;

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'whatsapp.release_batch_registered', 'release_batch', v_batch_id::text, p_persona_id,
    jsonb_build_object(
      'scope', p_scope, 'binding_id', p_binding_id, 'release_sha', p_release_sha,
      'item_count', v_count, 'reason', p_reason, 'idempotency_key', p_idempotency_key,
      'actor_user_id', p_actor_user_id
    ),
    'info', 'whatsapp.release_queue'
  );

  RETURN jsonb_build_object('batch_id', v_batch_id, 'item_count', v_count, 'deduplicated', false);
END;
$$;

-- Per-item escape hatch. 'pause' parks the underlying lead_buffer row far in
-- the future rather than adding a new guard to the dispatch worker's hot
-- loop (deliberate tradeoff: zero worker-code risk, at the cost of a
-- documented sentinel timestamp instead of an explicit flag). 'resume'
-- restores whichever timestamp the item should have (override if one was
-- set, otherwise the originally computed slot). 'reschedule' sets an
-- explicit operator-chosen available_at and implicitly un-pauses.
CREATE OR REPLACE FUNCTION public.set_release_item_override_v1(
  p_item_id uuid,
  p_action text,
  p_reason text,
  p_idempotency_key text,
  p_new_available_at timestamptz DEFAULT NULL,
  p_actor_user_id uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_item public.release_batch_items%ROWTYPE;
  v_target timestamptz;
BEGIN
  IF p_action NOT IN ('pause', 'resume', 'reschedule') THEN
    RAISE EXCEPTION 'unsupported release item action' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(btrim(p_idempotency_key), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'idempotency key and reason are required' USING ERRCODE = '22023';
  END IF;
  IF p_action = 'reschedule' AND p_new_available_at IS NULL THEN
    RAISE EXCEPTION 'reschedule requires p_new_available_at' USING ERRCODE = '22023';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.system_events
     WHERE event_type = 'whatsapp.release_item_' || p_action
       AND entity_id = p_item_id::text
       AND payload->>'idempotency_key' = p_idempotency_key
  ) THEN
    RETURN jsonb_build_object('item_id', p_item_id, 'deduplicated', true);
  END IF;

  SELECT * INTO v_item FROM public.release_batch_items WHERE id = p_item_id FOR UPDATE;
  IF v_item.id IS NULL THEN
    RAISE EXCEPTION 'release batch item not found' USING ERRCODE = 'P0002';
  END IF;

  IF p_action = 'pause' THEN
    v_target := now() + interval '10 years';
    UPDATE public.release_batch_items
       SET paused = true, paused_at = now(), paused_by = p_actor_user_id,
           pause_reason = p_reason, updated_at = now()
     WHERE id = p_item_id;
  ELSIF p_action = 'resume' THEN
    v_target := COALESCE(v_item.override_available_at, v_item.computed_available_at);
    UPDATE public.release_batch_items
       SET paused = false, pause_reason = NULL, updated_at = now()
     WHERE id = p_item_id;
  ELSE
    v_target := p_new_available_at;
    UPDATE public.release_batch_items
       SET override_available_at = p_new_available_at, override_by = p_actor_user_id,
           paused = false, pause_reason = NULL, updated_at = now()
     WHERE id = p_item_id;
  END IF;

  UPDATE public.lead_buffer
     SET available_at = v_target, updated_at = now()
   WHERE id = v_item.lead_buffer_id
     AND status IN ('retry', 'buffered', 'received');

  INSERT INTO public.system_events (
    event_type, entity_type, entity_id, persona_id, payload, level, source
  ) VALUES (
    'whatsapp.release_item_' || p_action, 'release_batch_item', p_item_id::text, v_item.persona_id,
    jsonb_build_object(
      'batch_id', v_item.batch_id, 'lead_buffer_id', v_item.lead_buffer_id,
      'lead_ref', v_item.lead_ref, 'reason', p_reason, 'idempotency_key', p_idempotency_key,
      'actor_user_id', p_actor_user_id, 'new_available_at', v_target
    ),
    'info', 'whatsapp.release_queue'
  );

  RETURN jsonb_build_object(
    'item_id', p_item_id, 'action', p_action, 'available_at', v_target, 'deduplicated', false
  );
END;
$$;

ALTER TABLE public.release_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.release_batch_items ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.release_batches FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.release_batch_items FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.release_batches TO service_role;
GRANT ALL ON TABLE public.release_batch_items TO service_role;

REVOKE ALL ON FUNCTION public.next_business_hours_slot(timestamptz, integer, integer, time, time, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.next_business_hours_slot(timestamptz, integer, integer, time, time, text)
  TO service_role;

REVOKE ALL ON FUNCTION public.register_release_batch_v1(
  uuid, text, uuid[], text, text, uuid, text, uuid, integer, time, time, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_release_batch_v1(
  uuid, text, uuid[], text, text, uuid, text, uuid, integer, time, time, text
) TO service_role;

REVOKE ALL ON FUNCTION public.set_release_item_override_v1(uuid, text, text, text, timestamptz, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_release_item_override_v1(uuid, text, text, text, timestamptz, uuid)
  TO service_role;
