-- 014_allow_audience_rag_entries.sql
-- Allow audience as a first-class RAG entry type.

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_content_type_check;

ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_content_type_check
  CHECK (content_type IN (
    'faq',
    'product',
    'brand',
    'campaign',
    'rule',
    'tone',
    'copy',
    'briefing',
    'audience',
    'asset',
    'entity',
    'general_note'
  ));
