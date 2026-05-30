-- =====================================================================
-- Legacy bootstrap for `leads` and `messages` tables.
-- These tables were NOT created by any of the 42 migrations (001..042).
-- They lived in the PROD schema before formal migrations existed and
-- are only ever ALTER'd in the migration set. The shape below is the
-- best-effort reconstruction from api/services/supabase_client.py and
-- the ALTER TABLE statements found across migrations.
--
-- TODO: replace with real pg_dump output of these two tables once the
-- PROD Supabase project is no longer restricted by exceed_egress_quota.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.leads (
  id              bigserial PRIMARY KEY,
  lead_id         text,
  nome            text,
  telefone        text,
  stage           text,
  origem          text,
  interesse_produto text,
  cidade          text,
  cep             text,
  ultima_mensagem text,
  last_update     timestamptz,
  ai_enabled      boolean DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS leads_lead_id_idx     ON public.leads(lead_id);
CREATE INDEX IF NOT EXISTS leads_telefone_idx    ON public.leads(telefone);
CREATE INDEX IF NOT EXISTS leads_stage_idx       ON public.leads(stage);
CREATE INDEX IF NOT EXISTS leads_updated_at_idx  ON public.leads(updated_at DESC);

CREATE TABLE IF NOT EXISTS public.messages (
  id            bigserial PRIMARY KEY,
  lead_id       bigint REFERENCES public.leads(id) ON DELETE CASCADE,
  role          text,
  content       text,
  direction     text,
  status        text,
  channel       text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_lead_id_idx    ON public.messages(lead_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON public.messages(created_at DESC);
