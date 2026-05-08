-- ============================================================
-- Brain AI Platform — Migration 024
-- Align observability tables with the current application contract.
--
-- Why:
-- - the live database still exposes the legacy agent_logs shape
--   (agent_name/input/output/status/error_msg)
-- - the application now uses agent_type/action/decision/metadata
-- - knowledge flow validation confirms graph mirrors by source_table/source_id
-- ============================================================

ALTER TABLE public.agent_logs
  ADD COLUMN IF NOT EXISTS agent_type text,
  ADD COLUMN IF NOT EXISTS action text,
  ADD COLUMN IF NOT EXISTS decision text,
  ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}'::jsonb;

UPDATE public.agent_logs
SET
  agent_type = COALESCE(agent_type, agent_name),
  action = COALESCE(
    action,
    CASE
      WHEN status IN ('error', 'timeout') OR error_msg IS NOT NULL
        THEN '[ERROR] ' || LEFT(COALESCE(error_msg, status, 'error'), 200)
      ELSE '[INFO] ' || LEFT(COALESCE(status, 'success'), 200)
    END
  ),
  decision = COALESCE(decision, LEFT(COALESCE(error_msg, output::text, input::text, ''), 500)),
  metadata = COALESCE(
    NULLIF(metadata, '{}'::jsonb),
    jsonb_build_object(
      'legacy_schema', true,
      'component', COALESCE(agent_name, agent_type, 'agent'),
      'message', COALESCE(error_msg, status, 'log'),
      'traceback', COALESCE(error_msg, ''),
      'ts', created_at,
      'input', COALESCE(input, '{}'::jsonb),
      'output', COALESCE(output, '{}'::jsonb),
      'model_used', model_used,
      'latency_ms', latency_ms
    )
  )
WHERE agent_type IS NULL
   OR action IS NULL
   OR decision IS NULL
   OR metadata IS NULL
   OR metadata = '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_agent_logs_agent_type ON public.agent_logs (agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_logs_created_at ON public.agent_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_logs_errors
  ON public.agent_logs (created_at DESC)
  WHERE action LIKE '[ERROR]%' OR action LIKE '[WARN]%';

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_source_lookup
  ON public.knowledge_nodes (source_table, source_id);
