-- The control-plane materializes graph edges through a validation trigger.
-- Grant the immutable validation ledger explicitly to its isolated role and
-- allow validated operational Copy/Rule cards to reach Embed, as the graph
-- contract permits. FAQ validation remains unchanged for every other source.
DO $$
DECLARE
  definition text;
  needle constant text := 'IF tgt_type = ''embed'' THEN';
  replacement constant text := 'IF tgt_type = ''embed'' AND src_type NOT IN (''copy'', ''rule'') THEN';
BEGIN
  SELECT pg_get_functiondef('public.validate_knowledge_edge_contract()'::regprocedure)
    INTO definition;
  IF definition IS NULL OR position(needle IN definition) = 0 THEN
    RAISE EXCEPTION 'validate_knowledge_edge_contract embed guard was not found';
  END IF;
  EXECUTE replace(definition, needle, replacement);

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brain_control_plane') THEN
    GRANT INSERT ON TABLE public.graph_validation_events TO brain_control_plane;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brain_transport') THEN
    GRANT EXECUTE ON FUNCTION public.apply_published_outbound_schedule_v1() TO brain_transport;
  END IF;
END
$$;

NOTIFY pgrst, 'reload schema';
