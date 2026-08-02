-- 082 revoked named Data API roles, but historical grants to PUBLIC are also
-- inherited by anon/authenticated. Remove that transitive access and protect
-- legacy views that otherwise bypass table RLS.

REVOKE ALL ON TABLE public.system_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_nodes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_edges FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_entries FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_chunks FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_rag_links FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.assets FROM PUBLIC, anon, authenticated;

REVOKE ALL ON TABLE public.knowledge_graph_primary_tree FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.knowledge_nodes_canonical FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.v_knowledge_curation_backlog FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.v_knowledge_lineage FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.v_knowledge_products_missing_price FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.v_knowledge_validation_failures FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.system_events TO service_role;
GRANT ALL ON TABLE public.knowledge_items TO service_role;
GRANT ALL ON TABLE public.knowledge_nodes TO service_role;
GRANT ALL ON TABLE public.knowledge_edges TO service_role;
GRANT ALL ON TABLE public.knowledge_rag_entries TO service_role;
GRANT ALL ON TABLE public.knowledge_rag_chunks TO service_role;
GRANT ALL ON TABLE public.knowledge_rag_links TO service_role;
GRANT ALL ON TABLE public.assets TO service_role;
GRANT SELECT ON TABLE public.knowledge_graph_primary_tree TO service_role;
GRANT SELECT ON TABLE public.knowledge_nodes_canonical TO service_role;
GRANT SELECT ON TABLE public.v_knowledge_curation_backlog TO service_role;
GRANT SELECT ON TABLE public.v_knowledge_lineage TO service_role;
GRANT SELECT ON TABLE public.v_knowledge_products_missing_price TO service_role;
GRANT SELECT ON TABLE public.v_knowledge_validation_failures TO service_role;
