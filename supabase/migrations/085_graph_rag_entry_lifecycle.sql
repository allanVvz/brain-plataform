-- Align the legacy entry status column with the projection lifecycle used by v2.1.

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_status_check;

ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_status_check
  CHECK (status IN (
    'draft', 'pending_embedding', 'pending_validation', 'validated', 'active',
    'rejected', 'duplicate', 'stale', 'building', 'withdrawn'
  ));
