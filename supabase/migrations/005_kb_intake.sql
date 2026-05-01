-- 005_kb_intake.sql
-- Tracks raw file uploads from the KB Classifier chat flow.
-- Safe to run multiple times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS public.kb_intake (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT        NOT NULL,
    file_path   TEXT        NOT NULL,          -- path inside the 'knowledge' storage bucket
    persona_id  UUID,                           -- resolved after classification (nullable)
    status      TEXT        NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kb_intake_status     ON public.kb_intake (status);
CREATE INDEX IF NOT EXISTS idx_kb_intake_persona_id ON public.kb_intake (persona_id);
CREATE INDEX IF NOT EXISTS idx_kb_intake_created_at ON public.kb_intake (created_at DESC);
