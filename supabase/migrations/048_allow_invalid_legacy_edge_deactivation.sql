-- Allow invalid legacy graph edges to be deactivated safely.
--
-- The hierarchy validator introduced in migrations 041/042 used to run for
-- every UPDATE.  That made an old invalid edge impossible to soft-delete:
-- changing metadata.active from true to false still raised INVALID_MAIN_EDGE.
-- Active inserts, updates and reactivations remain fully validated.

BEGIN;

DROP TRIGGER IF EXISTS trg_validate_knowledge_edge_contract
ON public.knowledge_edges;

CREATE TRIGGER trg_validate_knowledge_edge_contract
BEFORE INSERT OR UPDATE ON public.knowledge_edges
FOR EACH ROW
WHEN (COALESCE((NEW.metadata->>'active')::boolean, true) = true)
EXECUTE FUNCTION public.validate_knowledge_edge_contract();

COMMIT;

