-- GraphRAG v3 distinguishes a fully embedded but not yet active projection
-- (`ready`) from a projection already visible through a publication pointer.

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_projection_status_check;
ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_projection_status_check
  CHECK (projection_status IN ('pending','building','ready','published','withdrawn','failed'));

ALTER TABLE public.knowledge_rag_chunks
  DROP CONSTRAINT IF EXISTS knowledge_rag_chunks_projection_status_check;
ALTER TABLE public.knowledge_rag_chunks
  ADD CONSTRAINT knowledge_rag_chunks_projection_status_check
  CHECK (projection_status IN ('pending','building','ready','published','withdrawn','failed'));
