-- Graph JSON projections declare their own edges.  Remove only the old
-- automatically generated Persona -> node edges created before migration 057
-- prevented that guard from running for projections.

BEGIN;

DELETE FROM public.knowledge_edges e
USING public.knowledge_nodes n
WHERE e.target_node_id = n.id
  AND COALESCE(e.metadata->>'created_from', '') = 'db_primary_tree_guard'
  AND COALESCE(n.metadata, '{}'::jsonb) ? 'graph_json_id';

COMMIT;
