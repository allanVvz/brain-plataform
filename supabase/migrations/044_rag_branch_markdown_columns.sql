-- 044_rag_branch_markdown_columns.sql
-- Denormalized branch context for RAG entries/chunks created from approved graph nodes.

ALTER TABLE public.knowledge_rag_entries
  ADD COLUMN IF NOT EXISTS branch_persona_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_brand_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_briefing_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_campaign_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_audience_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_product_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_copy_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS connected_node_type TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS connected_node_title TEXT NOT NULL DEFAULT '';

ALTER TABLE public.knowledge_rag_chunks
  ADD COLUMN IF NOT EXISTS branch_persona_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_brand_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_briefing_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_campaign_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_audience_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_product_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS branch_copy_md TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS connected_node_type TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS connected_node_title TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_connected_node_type
  ON public.knowledge_rag_entries(connected_node_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_chunks_connected_node_type
  ON public.knowledge_rag_chunks(connected_node_type);

COMMENT ON COLUMN public.knowledge_rag_entries.embedding_model IS
  'For graph-approved content, stores the node type connected to Embedded, for example faq.';

COMMENT ON COLUMN public.knowledge_rag_chunks.embedding_model IS
  'For graph-approved content, stores the node type connected to Embedded, for example faq.';
