-- Move direct WA Validator execution to the workers process and provide a
-- guarded 12-hour retention routine. No new table is introduced: the
-- existing wa_validator_sessions JSON document is the durable queue.

CREATE INDEX IF NOT EXISTS idx_wa_validator_sessions_queue
  ON public.wa_validator_sessions ((data->>'status'), created_at);

CREATE OR REPLACE FUNCTION public.enqueue_wa_validator_session(
  p_session_id text, p_mode text DEFAULT 'direct'
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.wa_validator_sessions%ROWTYPE;
  v_status text;
  v_count integer;
BEGIN
  IF p_mode NOT IN ('direct') THEN
    RAISE EXCEPTION 'unsupported validator queue mode';
  END IF;
  SELECT * INTO v_row
    FROM public.wa_validator_sessions
   WHERE id=p_session_id
   FOR UPDATE;
  IF v_row.id IS NULL THEN
    RAISE EXCEPTION 'validator session not found' USING ERRCODE='P0002';
  END IF;
  v_status := coalesce(v_row.data->>'status','ready');
  IF v_status <> 'ready' THEN
    RETURN jsonb_build_object(
      'queued',false,'state',v_status,'session',v_row.data
    );
  END IF;
  SELECT count(*) INTO v_count
    FROM public.wa_validator_sessions s
   WHERE s.persona_slug=v_row.persona_slug
     AND s.id<>v_row.id
     AND s.data->>'status' IN ('queued','starting','running')
     AND s.updated_at>now()-interval '10 minutes';
  IF v_count>=2 THEN
    RETURN jsonb_build_object(
      'queued',false,'state','rate_limited','session',v_row.data
    );
  END IF;
  UPDATE public.wa_validator_sessions
     SET data = data || jsonb_build_object(
       'status','queued',
       'queue_mode',p_mode,
       'queued_at',now()
     ),
         updated_at=now()
   WHERE id=p_session_id
   RETURNING * INTO v_row;
  RETURN jsonb_build_object(
    'queued',true,'state','queued','session',v_row.data
  );
END; $$;

CREATE OR REPLACE FUNCTION public.claim_next_wa_validator_session(
  p_worker_id text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_row public.wa_validator_sessions%ROWTYPE;
BEGIN
  SELECT * INTO v_row
    FROM public.wa_validator_sessions
   WHERE data->>'status'='queued'
     AND coalesce(data->>'queue_mode','direct')='direct'
   ORDER BY created_at
   FOR UPDATE SKIP LOCKED
   LIMIT 1;
  IF v_row.id IS NULL THEN
    RETURN jsonb_build_object('claimed',false,'state','empty');
  END IF;
  UPDATE public.wa_validator_sessions
     SET data = data || jsonb_build_object(
       'status','running',
       'worker_id',p_worker_id,
       'claimed_at',now()
     ),
         updated_at=now()
   WHERE id=v_row.id
   RETURNING * INTO v_row;
  RETURN jsonb_build_object(
    'claimed',true,'state','running','session',v_row.data
  );
END; $$;

CREATE OR REPLACE FUNCTION public.cleanup_wa_validator_artifacts(
  p_before interval DEFAULT interval '12 hours',
  p_dry_run boolean DEFAULT true
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_cutoff timestamptz := now() - greatest(p_before, interval '1 hour');
  v_lead_ids bigint[] := '{}';
  v_session_ids text[] := '{}';
  v_buffer_ids text[] := '{}';
  v_unsafe_lead_ids bigint[] := '{}';
  v_message_count integer := 0;
  v_buffer_count integer := 0;
  v_proof_count integer := 0;
  v_ledger_count integer := 0;
  v_event_count integer := 0;
BEGIN
  -- One inventory/cleanup transaction at a time across all worker replicas.
  PERFORM pg_advisory_xact_lock(hashtext('wa_validator_retention_v1'));

  SELECT coalesce(array_agg(s.id ORDER BY s.created_at), '{}')
    INTO v_session_ids
    FROM public.wa_validator_sessions s
   WHERE s.created_at < v_cutoff
     AND coalesce(s.data->>'status','') NOT IN ('queued','starting','running');

  SELECT coalesce(array_agg(l.id ORDER BY l.created_at), '{}')
    INTO v_lead_ids
    FROM public.leads l
   WHERE l.created_at < v_cutoff
     AND (
       coalesce((l.metadata->'validation'->>'is_validation')::boolean,false)
       OR coalesce(l.metadata->>'validation_session_id','') <> ''
       OR coalesce(l.metadata->>'validator_session_id','') <> ''
       OR coalesce(l.metadata->'validation'->>'session_id','') <> ''
       OR coalesce(l.lead_id,'') LIKE 'validator\_%' ESCAPE '\'
     )
     -- A lead remains protected while its owning session is recent OR in a
     -- non-terminal state, even when that state became stale long ago. The
     -- production audit found exactly this shape (an old `running` session
     -- whose lead was safely paused); retention must never decide recovery.
     AND NOT EXISTS (
       SELECT 1
         FROM public.wa_validator_sessions protected
         WHERE protected.id = coalesce(
             nullif(l.metadata->'validation'->>'session_id',''),
             nullif(l.metadata->>'validation_session_id',''),
             nullif(l.metadata->>'validator_session_id','')
          )
          AND (
            protected.created_at >= v_cutoff
            OR coalesce(protected.data->>'status','') IN (
              'queued','starting','running'
            )
          )
     );

  SELECT coalesce(array_agg(b.id::text), '{}')
    INTO v_buffer_ids
    FROM public.lead_buffer b
   WHERE b.lead_ref = ANY(v_lead_ids);

  -- A synthetic marker is necessary but never sufficient for deletion. Any
  -- real-looking destination/provider identity aborts the entire apply.
  SELECT coalesce(array_agg(DISTINCT candidate.lead_ref), '{}')
    INTO v_unsafe_lead_ids
    FROM (
      SELECT l.id AS lead_ref
        FROM public.leads l
       WHERE l.id=ANY(v_lead_ids)
         AND (
           (
             coalesce(l.external_contact_id,'') <> ''
             AND coalesce(l.external_contact_id,'') NOT LIKE 'validator\_%' ESCAPE '\'
           )
           OR coalesce(l.metadata->'identities'->>'remote_jid','') <> ''
           OR coalesce(l.metadata->'identities'->>'remote_jid_alt','') <> ''
         )
      UNION ALL
      SELECT b.lead_ref
        FROM public.lead_buffer b
       WHERE b.lead_ref=ANY(v_lead_ids)
         AND b.direction='outbound'
         AND (
           coalesce(b.status,'') IN (
             'received','buffered','processing','pending_send','retry','awaiting_proof'
           )
           OR b.locked_at IS NOT NULL
           OR (coalesce(b.external_message_id,'') <> ''
              AND b.external_message_id NOT LIKE 'ai\_reply.validator:%' ESCAPE '\'
              AND b.external_message_id NOT LIKE 'validator:%')
           OR coalesce(b.payload->>'to','') <> ''
           OR coalesce(b.payload->>'recipient','') <> ''
           OR coalesce(b.payload->>'external_recipient_id','') <> ''
         )
      UNION ALL
      SELECT m.lead_id
        FROM public.messages m
       WHERE m.lead_id=ANY(v_lead_ids)
         AND coalesce(m.direction,'')='outbound'
         AND coalesce(m.external_message_id,'') <> ''
         AND m.external_message_id NOT LIKE 'ai\_reply.validator:%' ESCAPE '\'
         AND m.external_message_id NOT LIKE 'validator:%'
    ) candidate;

  SELECT count(*) INTO v_message_count FROM public.messages WHERE lead_id=ANY(v_lead_ids);
  SELECT count(*) INTO v_buffer_count FROM public.lead_buffer WHERE lead_ref=ANY(v_lead_ids);
  SELECT count(*) INTO v_ledger_count FROM public.conversation_ledgers WHERE lead_ref=ANY(v_lead_ids);
  SELECT count(*) INTO v_proof_count
    FROM public.conversation_turn_proofs p
   WHERE p.ledger_id IN (
     SELECT id FROM public.conversation_ledgers WHERE lead_ref=ANY(v_lead_ids)
   ) OR p.canonical_inbound_id=ANY(v_buffer_ids);
  SELECT count(*) INTO v_event_count
    FROM public.system_events e
   WHERE e.payload->>'session_id'=ANY(v_session_ids)
      OR e.payload->>'canonical_inbound_id'=ANY(v_buffer_ids);

  IF p_dry_run THEN
    RETURN jsonb_build_object(
      'dry_run',true,'cutoff',v_cutoff,
      'lead_count',cardinality(v_lead_ids),'lead_ids',to_jsonb(v_lead_ids),
      'session_count',cardinality(v_session_ids),'session_ids',to_jsonb(v_session_ids),
      'message_count',v_message_count,'buffer_count',v_buffer_count,
      'proof_count',v_proof_count,'ledger_count',v_ledger_count,
      'event_count',v_event_count,
      'safe',cardinality(v_unsafe_lead_ids)=0,
      'unsafe_lead_ids',to_jsonb(v_unsafe_lead_ids)
    );
  END IF;
  IF cardinality(v_unsafe_lead_ids)>0 THEN
    RAISE EXCEPTION 'validator retention aborted: real outbound linkage on leads %',
      v_unsafe_lead_ids;
  END IF;

  DELETE FROM public.system_events e
   WHERE e.payload->>'session_id'=ANY(v_session_ids)
      OR e.payload->>'canonical_inbound_id'=ANY(v_buffer_ids);
  DELETE FROM public.conversation_turn_proofs p
   WHERE p.ledger_id IN (
     SELECT id FROM public.conversation_ledgers WHERE lead_ref=ANY(v_lead_ids)
   ) OR p.canonical_inbound_id=ANY(v_buffer_ids);
  DELETE FROM public.chat_history
   WHERE session_id=ANY(v_session_ids)
      OR session_id=ANY(
        ARRAY(SELECT value::text FROM unnest(v_lead_ids) AS ids(value))
      );
  DELETE FROM public.lead_buffer WHERE lead_ref=ANY(v_lead_ids);
  DELETE FROM public.messages WHERE lead_id=ANY(v_lead_ids);
  DELETE FROM public.lead_audience_memberships WHERE lead_id=ANY(v_lead_ids);
  DELETE FROM public.conversation_ledgers WHERE lead_ref=ANY(v_lead_ids);
  DELETE FROM public.leads WHERE id=ANY(v_lead_ids);
  DELETE FROM public.wa_validator_sessions WHERE id=ANY(v_session_ids);

  INSERT INTO public.system_events(event_type,payload,level,source)
  VALUES (
    'wa_validator_retention_applied',
    jsonb_build_object(
      'cutoff',v_cutoff,'lead_count',cardinality(v_lead_ids),
      'session_count',cardinality(v_session_ids),'message_count',v_message_count,
      'buffer_count',v_buffer_count,'proof_count',v_proof_count,
      'ledger_count',v_ledger_count
    ),
    'info','workers.wa_validator'
  );
  RETURN jsonb_build_object(
    'dry_run',false,'cutoff',v_cutoff,'safe',true,
    'lead_count',cardinality(v_lead_ids),'lead_ids',to_jsonb(v_lead_ids),
    'session_count',cardinality(v_session_ids),'session_ids',to_jsonb(v_session_ids),
    'message_count',v_message_count,'buffer_count',v_buffer_count,
    'proof_count',v_proof_count,'ledger_count',v_ledger_count
  );
END; $$;

REVOKE ALL ON FUNCTION public.enqueue_wa_validator_session(text,text)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.claim_next_wa_validator_session(text)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.cleanup_wa_validator_artifacts(interval,boolean)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_wa_validator_session(text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_next_wa_validator_session(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.cleanup_wa_validator_artifacts(interval,boolean) TO service_role;
