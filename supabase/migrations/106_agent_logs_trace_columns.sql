-- Phase 0 of LLM/agent observability: promotes a handful of keys that
-- conversation_runtime.py is about to start writing into agent_logs.metadata
-- / system_events.payload (trace_id, conversation_id, n8n_execution_id,
-- cost_usd, quality_score) into real indexable columns, using the same
-- GENERATED ALWAYS AS (...) STORED pattern already used for
-- knowledge_rag_chunks.search_document (093) and leads.ai_paused (103).
--
-- Purely additive: no NOT NULL, no new tables, no change to the existing
-- hybrid insert path in supabase_client.insert_agent_log(). Existing rows
-- have no 'trace_id'/'conversation_id'/etc key in their jsonb yet, so every
-- generated column backfills to NULL for them -- nothing to migrate.
--
-- trace_id is the existing lead_buffer.id (uuid) of the inbound message
-- that started the turn -- already the canonical per-turn key everywhere
-- else in this codebase (claim_conversation_commit, conversation_turn_proofs
-- .canonical_inbound_id). conversation_id is an explicit alias for
-- lead_ref: there is no separate "session" concept today, but naming it
-- distinctly means only the population site changes if one is ever added.

ALTER TABLE public.agent_logs
  ADD COLUMN IF NOT EXISTS trace_id uuid
    GENERATED ALWAYS AS ((metadata ->> 'trace_id')::uuid) STORED,
  ADD COLUMN IF NOT EXISTS conversation_id bigint
    GENERATED ALWAYS AS ((metadata ->> 'conversation_id')::bigint) STORED,
  ADD COLUMN IF NOT EXISTS n8n_execution_id text
    GENERATED ALWAYS AS (metadata ->> 'n8n_execution_id') STORED,
  ADD COLUMN IF NOT EXISTS cost_usd numeric(10, 6)
    GENERATED ALWAYS AS ((metadata ->> 'cost_usd')::numeric) STORED,
  -- Reserved for the (deliberately deferred) response-quality scoring phase
  -- -- written later as its own agent_logs row keyed by the same trace_id,
  -- not a mutation of the original turn's row.
  ADD COLUMN IF NOT EXISTS quality_score numeric
    GENERATED ALWAYS AS ((metadata ->> 'quality_score')::numeric) STORED;

CREATE INDEX IF NOT EXISTS idx_agent_logs_trace_id
  ON public.agent_logs (trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_logs_conversation_id
  ON public.agent_logs (conversation_id, created_at DESC) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_logs_n8n_execution_id
  ON public.agent_logs (n8n_execution_id) WHERE n8n_execution_id IS NOT NULL;

ALTER TABLE public.system_events
  ADD COLUMN IF NOT EXISTS trace_id uuid
    GENERATED ALWAYS AS ((payload ->> 'trace_id')::uuid) STORED;

CREATE INDEX IF NOT EXISTS idx_system_events_trace_id
  ON public.system_events (trace_id) WHERE trace_id IS NOT NULL;
