-- Keep live Chatwoot messages ahead of historical backfill. Message timestamps
-- are projected from messages.created_at, so queue processing can be newest-first
-- without changing the customer-visible conversation chronology.
CREATE OR REPLACE FUNCTION public.claim_chatwoot_bridge_operations_v1(
  p_worker_id text,
  p_limit integer DEFAULT 20,
  p_lease_seconds integer DEFAULT 90
) RETURNS SETOF public.chatwoot_bridge_operations
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  IF nullif(btrim(p_worker_id),'') IS NULL THEN
    RAISE EXCEPTION 'worker id is required' USING ERRCODE='22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('chatwoot-bridge-claim-v1'));
  RETURN QUERY
  WITH candidates AS (
    SELECT o.id FROM public.chatwoot_bridge_operations o
     WHERE ((o.status IN ('pending','retry') AND o.available_at <= now())
        OR (o.status='processing' AND o.locked_at < now()
            - make_interval(secs => greatest(30,least(coalesce(p_lease_seconds,90),600)))))
       AND NOT EXISTS (
         SELECT 1 FROM public.chatwoot_bridge_operations p
          WHERE p.channel_binding_id=o.channel_binding_id AND p.lead_ref=o.lead_ref
            AND p.status='processing' AND p.id<>o.id
       )
       AND NOT EXISTS (
         SELECT 1 FROM public.chatwoot_bridge_operations q
          WHERE o.operation <> 'project_message'
            AND q.channel_binding_id=o.channel_binding_id AND q.lead_ref=o.lead_ref
            AND q.status IN ('pending','retry') AND q.available_at<=now()
            AND NOT (o.operation IN ('pause_ai','resume_ai','human_reply')
                     AND q.operation='project_message')
            AND (q.created_at,q.id)<(o.created_at,o.id)
       )
     ORDER BY CASE WHEN o.operation='project_message' THEN 1 ELSE 0 END,
              o.created_at DESC,o.brain_message_id DESC NULLS LAST,o.id
     LIMIT greatest(1,least(coalesce(p_limit,20),100))
     FOR UPDATE OF o SKIP LOCKED
  )
  UPDATE public.chatwoot_bridge_operations o
     SET status='processing',locked_at=now(),locked_by=p_worker_id,
         attempt_count=o.attempt_count+1,updated_at=now()
    FROM candidates c WHERE o.id=c.id
  RETURNING o.*;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_chatwoot_bridge_operations_v1(text,integer,integer)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_chatwoot_bridge_operations_v1(text,integer,integer)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_chatwoot_bridge_operations_v1(text,integer,integer)
  TO brain_transport;
NOTIFY pgrst, 'reload schema';
