-- Validation events are written by a BEFORE INSERT trigger. Rejected edge
-- candidates never exist in knowledge_edges, so their candidate UUID cannot
-- be protected by a foreign key. Keep the UUID as audit evidence.

BEGIN;

ALTER TABLE public.graph_validation_events
  DROP CONSTRAINT IF EXISTS graph_validation_events_edge_id_fkey;

COMMENT ON COLUMN public.graph_validation_events.edge_id IS
  'Candidate or persisted edge UUID. Rejected BEFORE INSERT candidates do not exist in knowledge_edges.';

COMMIT;
