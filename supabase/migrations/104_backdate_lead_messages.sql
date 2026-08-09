-- Test-only helper for the WA Validator: shifts a lead's message
-- created_at timestamps backward by N hours after a scripted phase
-- completes, so a later phase can exercise genuine time-gap-aware
-- behavior (see graph_agent_runtime_v3.build_context's
-- time_since_last_client_message) instead of every scripted message
-- landing within seconds of the last. PostgREST's update builder can't
-- express a relative "created_at - interval" update, hence the RPC.
CREATE OR REPLACE FUNCTION public.backdate_lead_messages(
  p_lead_ref bigint,
  p_hours numeric
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_count integer;
BEGIN
  IF p_hours IS NULL OR p_hours <= 0 THEN
    RAISE EXCEPTION 'p_hours must be positive: %', p_hours;
  END IF;

  UPDATE public.messages
     SET created_at = created_at - (p_hours || ' hours')::interval
   WHERE lead_id = p_lead_ref;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.backdate_lead_messages(bigint, numeric)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.backdate_lead_messages(bigint, numeric)
  TO service_role;
