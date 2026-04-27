-- 004_error_logging.sql
-- Ensures system_events and agent_logs exist with the correct columns.
-- Safe to run multiple times (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

-- ── system_events ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.system_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    entity_type  TEXT,
    entity_id    UUID,
    persona_id   UUID,
    payload      JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_system_events_event_type  ON public.system_events (event_type);
CREATE INDEX IF NOT EXISTS idx_system_events_persona_id  ON public.system_events (persona_id);
CREATE INDEX IF NOT EXISTS idx_system_events_created_at  ON public.system_events (created_at DESC);

-- ── agent_logs — ensure SRE columns exist ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.agent_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id      UUID,
    agent_type   TEXT,          -- component name, e.g. 'KbSyncWorker'
    action       TEXT,          -- '[ERROR] message' or '[INFO] message'
    decision     TEXT,          -- traceback or detail
    metadata     JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add index on agent_type for component-filtered queries in GET /logs/errors
CREATE INDEX IF NOT EXISTS idx_agent_logs_agent_type   ON public.agent_logs (agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_logs_created_at   ON public.agent_logs (created_at DESC);
-- Partial index for fast error-only queries
CREATE INDEX IF NOT EXISTS idx_agent_logs_errors
    ON public.agent_logs (created_at DESC)
    WHERE action LIKE '[ERROR]%' OR action LIKE '[WARN]%';

-- ── pipeline_status — ensure table exists ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.pipeline_status (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service      TEXT UNIQUE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'unknown',
    last_activity TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed known services if they don't exist yet
INSERT INTO public.pipeline_status (service, status)
VALUES
    ('vault_sync',           'unknown'),
    ('knowledge_validation', 'unknown'),
    ('knowledge_intake',     'unknown'),
    ('flow_validator',       'unknown'),
    ('n8n_mirror',           'unknown'),
    ('health_check',         'unknown')
ON CONFLICT (service) DO NOTHING;
