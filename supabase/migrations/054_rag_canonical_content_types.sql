-- Canonical Markdown publication projects every approved knowledge node into
-- knowledge_rag_entries/chunks. This expands the existing enum only; no table
-- is introduced.

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_content_type_check;

ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_content_type_check
  CHECK (content_type IN (
    'faq',
    'product',
    'product_group',
    'offer',
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
