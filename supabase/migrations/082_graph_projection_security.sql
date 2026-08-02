-- Defense in depth for internal projection/event tables exposed by PostgREST.
-- The FastAPI service_role remains the only runtime database writer/reader.

ALTER TABLE public.system_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_rag_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_rag_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.system_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_nodes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_edges FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_entries FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_chunks FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_links FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.assets FROM PUBLIC, anon, authenticated;

-- Shadow/cutover guard.  It is intentionally dormant until the deployment
-- sets `brain.enforce_projector_writes=on`; this avoids breaking legacy paths
-- before their adapters have reached zero traffic.
CREATE OR REPLACE FUNCTION public.guard_graph_projection_write_v2()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF current_setting('brain.enforce_projector_writes', true) = 'on'
     AND current_setting('brain.projector_write', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION 'direct projection writes are disabled; use Graph JSON projector'
      USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY[
    'knowledge_nodes', 'knowledge_edges', 'knowledge_rag_entries',
    'knowledge_rag_chunks', 'knowledge_rag_links'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_guard_graph_projection_write_v2 ON public.%I', v_table);
    EXECUTE format(
      'CREATE TRIGGER trg_guard_graph_projection_write_v2 BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.guard_graph_projection_write_v2()',
      v_table
    );
  END LOOP;
END;
$$;
