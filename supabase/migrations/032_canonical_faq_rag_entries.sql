-- 032_canonical_faq_rag_entries.sql
-- Canonical FAQ RAG lineage: one RAG entry/chunk per approved FAQ Q/A.

ALTER TABLE public.knowledge_rag_entries
  ADD COLUMN IF NOT EXISTS source_snapshot_id uuid REFERENCES public.approved_knowledge_snapshots(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS session_id text;

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_source_snapshot
  ON public.knowledge_rag_entries(source_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_source_node
  ON public.knowledge_rag_entries(source_node_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_session
  ON public.knowledge_rag_entries(session_id);

ALTER TABLE public.approved_knowledge_snapshots
  ADD COLUMN IF NOT EXISTS session_id text,
  ADD COLUMN IF NOT EXISTS tree_mode text NOT NULL DEFAULT 'pyramidal',
  ADD COLUMN IF NOT EXISTS branch_policy text NOT NULL DEFAULT 'top_down_pyramidal';

CREATE INDEX IF NOT EXISTS idx_approved_snapshots_session
  ON public.approved_knowledge_snapshots(session_id);

