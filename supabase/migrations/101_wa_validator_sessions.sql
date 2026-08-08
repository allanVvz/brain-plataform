-- WA Validator sessions were stored in a plain in-process Python dict, so
-- with more than one gunicorn worker (GUNICORN_WORKERS=2 in production) a
-- "generate script" request and the following "run" request had roughly a
-- coin-flip chance of landing on different worker processes -- the second
-- request's worker never saw the session the first one created, producing
-- "Sessão não encontrada" for a session that genuinely exists, just in the
-- other worker's memory. Confirmed live 2026-08-08. This table lets any
-- worker (or a future replacement of the whole subprocess-runner path)
-- serve any session.

CREATE TABLE IF NOT EXISTS public.wa_validator_sessions (
  id text PRIMARY KEY,
  persona_slug text,
  flow_id text,
  data jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(data) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wa_validator_sessions_created_at
  ON public.wa_validator_sessions(created_at DESC);

ALTER TABLE public.wa_validator_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.wa_validator_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.wa_validator_sessions TO service_role;
