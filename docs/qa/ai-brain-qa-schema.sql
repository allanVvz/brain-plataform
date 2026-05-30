-- =====================================================================
-- ai-brain-qa schema dump (concatenated migrations)
-- Project ref : qhnepdcqtkjjslqqiyvp
-- Project name: ai-brain-qa
-- Region      : us-east-1 (Supabase)
-- Generated   : 2026-05-27T06:22:38.394403+00:00
--
-- NOTE: This is NOT a live introspection (pg_dump). It is the concatenation
-- of the 42 migration files in supabase/migrations/ applied in numeric order.
-- It reflects the schema that *should* exist on QA assuming all migrations
-- ran cleanly. To get the live state, restore Supabase project access (the
-- project is currently restricted by exceed_egress_quota) and rerun via
-- psycopg2 introspection over pg_catalog/information_schema.
-- =====================================================================

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;



-- ---------------------------------------------------------------------
-- File: 001_platform_tables.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform — Migration 001
-- Novas tabelas para a plataforma (não toca nas existentes)
-- ============================================================

-- Habilitar extensão pgvector (se ainda não ativa)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Personas / Clientes ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS personas (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        text UNIQUE NOT NULL,
  name        text NOT NULL,
  tone        text,
  products    jsonb DEFAULT '[]',
  prompts     jsonb DEFAULT '{}',
  config      jsonb DEFAULT '{}',
  active      boolean DEFAULT true,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

-- Persona inicial: Tock Fatal
INSERT INTO personas (slug, name, tone, products, config)
VALUES (
  'tock-fatal',
  'Tock Fatal',
  'comercial, direto, jovem',
  '["blusa modal","casaco","vestido","conjunto","tricot","jaqueta"]',
  '{"kb_spreadsheet_id": "1qkgGKwT6sRuylLggrficVNImypFvpbYNYN7pKOwCg78"}'
)
ON CONFLICT (slug) DO NOTHING;

-- ── Flow Insights ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS flow_insights (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id          uuid REFERENCES personas(id) ON DELETE SET NULL,
  severity            text NOT NULL CHECK (severity IN ('critical','warning','info')),
  category            text NOT NULL CHECK (category IN ('performance','reliability','architecture','business')),
  title               text NOT NULL,
  description         text,
  recommendation      text,
  affected_component  text,
  score_impact        int DEFAULT 0,
  status              text DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
  created_at          timestamptz DEFAULT now(),
  resolved_at         timestamptz
);

CREATE INDEX IF NOT EXISTS flow_insights_status_idx ON flow_insights(status);
CREATE INDEX IF NOT EXISTS flow_insights_severity_idx ON flow_insights(severity);
CREATE INDEX IF NOT EXISTS flow_insights_created_idx ON flow_insights(created_at DESC);

-- ── System Health Snapshots ──────────────────────────────────
CREATE TABLE IF NOT EXISTS system_health (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id           uuid REFERENCES personas(id) ON DELETE SET NULL,
  score_total          int NOT NULL DEFAULT 0,
  score_performance    int NOT NULL DEFAULT 0,
  score_reliability    int NOT NULL DEFAULT 0,
  score_architecture   int NOT NULL DEFAULT 0,
  score_business       int NOT NULL DEFAULT 0,
  open_critical        int DEFAULT 0,
  open_warnings        int DEFAULT 0,
  snapshot_at          timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS system_health_snapshot_idx ON system_health(snapshot_at DESC);

-- ── Integration Status ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS integration_status (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id     uuid REFERENCES personas(id) ON DELETE SET NULL,
  service        text NOT NULL,
  status         text DEFAULT 'unknown' CHECK (status IN ('healthy','degraded','down','unknown')),
  response_ms    int,
  error_message  text,
  config         jsonb DEFAULT '{}',
  last_check     timestamptz DEFAULT now(),
  UNIQUE (persona_id, service)
);

-- ── Assets ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id  uuid REFERENCES personas(id) ON DELETE CASCADE,
  type        text CHECK (type IN ('image','copy','campaign','template')),
  name        text NOT NULL,
  url         text,
  metadata    jsonb DEFAULT '{}',
  source      text DEFAULT 'manual' CHECK (source IN ('maker','manual','mcp','imported')),
  created_at  timestamptz DEFAULT now()
);

-- ── Agent Execution Logs ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_logs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id   uuid REFERENCES personas(id) ON DELETE SET NULL,
  lead_id      text,
  agent_name   text NOT NULL,
  input        jsonb,
  output       jsonb,
  latency_ms   int,
  model_used   text,
  token_input  int,
  token_output int,
  status       text DEFAULT 'success' CHECK (status IN ('success','error','timeout')),
  error_msg    text,
  created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_logs_lead_idx ON agent_logs(lead_id);
CREATE INDEX IF NOT EXISTS agent_logs_created_idx ON agent_logs(created_at DESC);

-- ── n8n Executions Mirror ────────────────────────────────────
CREATE TABLE IF NOT EXISTS n8n_executions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      uuid REFERENCES personas(id) ON DELETE SET NULL,
  workflow_name   text,
  n8n_id          text UNIQUE NOT NULL,
  status          text,
  started_at      timestamptz,
  finished_at     timestamptz,
  duration_ms     int,
  node_errors     jsonb DEFAULT '[]',
  lead_id         text,
  created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS n8n_executions_status_idx ON n8n_executions(status);
CREATE INDEX IF NOT EXISTS n8n_executions_started_idx ON n8n_executions(started_at DESC);

-- ── Knowledge Base Entries (substitui in-memory vector store) ─
CREATE TABLE IF NOT EXISTS kb_entries (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id  uuid REFERENCES personas(id) ON DELETE CASCADE,
  kb_id       text NOT NULL,
  tipo        text DEFAULT 'faq',
  categoria   text DEFAULT 'geral',
  produto     text DEFAULT 'geral',
  intencao    text DEFAULT 'duvida_geral',
  titulo      text NOT NULL,
  conteudo    text NOT NULL,
  link        text,
  prioridade  int DEFAULT 99,
  status      text DEFAULT 'ATIVO',
  source      text DEFAULT 'sheets' CHECK (source IN ('sheets','manual')),
  embedding   vector(1536),
  updated_at  timestamptz DEFAULT now(),
  created_at  timestamptz DEFAULT now(),
  UNIQUE (kb_id, persona_id)
);

CREATE INDEX IF NOT EXISTS kb_entries_persona_idx ON kb_entries(persona_id);
CREATE INDEX IF NOT EXISTS kb_entries_status_idx ON kb_entries(status);

-- Índice vetorial para busca semântica (ativar após inserir dados)
-- CREATE INDEX kb_entries_embedding_idx ON kb_entries
-- USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── Função de busca semântica na KB ─────────────────────────
CREATE OR REPLACE FUNCTION match_kb_entries(
  query_embedding vector(1536),
  match_count int DEFAULT 5,
  filter_persona_id uuid DEFAULT NULL
)
RETURNS TABLE (
  id uuid,
  titulo text,
  conteudo text,
  link text,
  categoria text,
  produto text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    k.id,
    k.titulo,
    k.conteudo,
    k.link,
    k.categoria,
    k.produto,
    1 - (k.embedding <=> query_embedding) AS similarity
  FROM kb_entries k
  WHERE
    k.status = 'ATIVO'
    AND k.embedding IS NOT NULL
    AND (filter_persona_id IS NULL OR k.persona_id = filter_persona_id)
  ORDER BY k.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;




-- ---------------------------------------------------------------------
-- File: 002_knowledge_platform.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform — Migration 002
-- Knowledge management multi-client layer
-- ============================================================

-- ── Knowledge Sources ────────────────────────────────────────
-- Represents origins of knowledge: vault paths, Google Sheets, manual uploads
CREATE TABLE IF NOT EXISTS knowledge_sources (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id   uuid REFERENCES personas(id) ON DELETE CASCADE,
  source_type  text NOT NULL CHECK (source_type IN ('vault', 'sheets', 'upload', 'manual')),
  name         text NOT NULL,
  path         text,         -- local vault path or remote URL
  config       jsonb DEFAULT '{}',
  last_synced_at timestamptz,
  created_at   timestamptz DEFAULT now()
);

-- Insert default vault source (global, not persona-specific)
INSERT INTO knowledge_sources (source_type, name, path)
VALUES ('vault', 'Brain AI Vault', 'C:\Ai-Brain\Ai-Brain')
ON CONFLICT DO NOTHING;

-- ── Knowledge Items ───────────────────────────────────────────
-- Individual knowledge pieces before and after validation
CREATE TABLE IF NOT EXISTS knowledge_items (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id       uuid REFERENCES personas(id) ON DELETE SET NULL,
  source_id        uuid REFERENCES knowledge_sources(id) ON DELETE SET NULL,
  status           text DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','embedded')),
  content_type     text NOT NULL CHECK (content_type IN (
                     'brand','briefing','product','campaign','copy','asset',
                     'prompt','faq','maker_material','tone','competitor',
                     'audience','rule','other'
                   )),
  title            text NOT NULL,
  content          text NOT NULL,
  metadata         jsonb DEFAULT '{}',
  file_path        text,
  file_type        text,
  embedding        vector(1536),
  approved_at      timestamptz,
  rejected_reason  text,
  created_at       timestamptz DEFAULT now(),
  updated_at       timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_items_persona_idx ON knowledge_items(persona_id);
CREATE INDEX IF NOT EXISTS knowledge_items_status_idx  ON knowledge_items(status);
CREATE INDEX IF NOT EXISTS knowledge_items_type_idx    ON knowledge_items(content_type);
CREATE INDEX IF NOT EXISTS knowledge_items_created_idx ON knowledge_items(created_at DESC);

-- ── Sync Runs ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id       uuid REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  status          text DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
  files_found     int DEFAULT 0,
  files_new       int DEFAULT 0,
  files_updated   int DEFAULT 0,
  files_skipped   int DEFAULT 0,
  error_message   text,
  started_at      timestamptz DEFAULT now(),
  finished_at     timestamptz
);

CREATE INDEX IF NOT EXISTS sync_runs_started_idx ON sync_runs(started_at DESC);

-- ── Sync Logs ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_logs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id        uuid REFERENCES sync_runs(id) ON DELETE CASCADE,
  file_path     text NOT NULL,
  persona_id    uuid REFERENCES personas(id) ON DELETE SET NULL,
  action        text CHECK (action IN ('created','updated','skipped','error')),
  content_type  text,
  error_message text,
  created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sync_logs_run_idx ON sync_logs(run_id);

-- ── Workflow Bindings ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_bindings (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id        uuid REFERENCES personas(id) ON DELETE CASCADE,
  workflow_name     text NOT NULL,
  n8n_workflow_id   text,
  whatsapp_number   text,
  active            boolean DEFAULT true,
  created_at        timestamptz DEFAULT now(),
  UNIQUE (workflow_name, persona_id)
);

-- Tock Fatal CRM Vitoria binding
INSERT INTO workflow_bindings (persona_id, workflow_name, n8n_workflow_id)
SELECT id, 'Tock Vitoria CRM Low', NULL
FROM personas WHERE slug = 'tock-fatal'
ON CONFLICT (workflow_name, persona_id) DO NOTHING;

-- ── Brand Profiles ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS brand_profiles (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      uuid REFERENCES personas(id) ON DELETE CASCADE UNIQUE,
  tagline         text,
  positioning     text,
  differentials   jsonb DEFAULT '[]',
  values          jsonb DEFAULT '[]',
  palette         jsonb DEFAULT '[]',
  typography      jsonb DEFAULT '{}',
  tone_pillars    jsonb DEFAULT '[]',
  vocabulary      jsonb DEFAULT '[]',
  target_audience text,
  extra           jsonb DEFAULT '{}',
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

-- ── Campaigns ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaigns (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id  uuid REFERENCES personas(id) ON DELETE CASCADE,
  slug        text NOT NULL,
  name        text NOT NULL,
  status      text DEFAULT 'draft' CHECK (status IN ('draft','active','paused','finished')),
  format      text,
  metadata    jsonb DEFAULT '{}',
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now(),
  UNIQUE (slug, persona_id)
);

-- ── Personas: add missing clients ─────────────────────────────
INSERT INTO personas (slug, name, tone, products, config)
VALUES
  ('baita-conveniencia', 'Baita Conveniência',
   'honesto, ácido, gaúcho, presente',
   '["petisco","bebida","tabacaria","conveniência"]',
   '{}'
  ),
  ('vz-lupas', 'VZ Lupas',
   'premium, sustentável, lifestyle',
   '["Juliet","Radar","Gascan","Frogskins","Flak","Clifden","Trillbe","Holbrook","Latch","Split Shot","Sylas"]',
   '{}'
  )
ON CONFLICT (slug) DO NOTHING;

-- ── Leads: add optional persona link (non-breaking) ───────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS persona_id uuid REFERENCES personas(id) ON DELETE SET NULL;




-- ---------------------------------------------------------------------
-- File: 003_pipeline_events.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform — Migration 003
-- Pipeline events, enhanced knowledge validation
-- ============================================================

-- ── System Events ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type  text NOT NULL,
  entity_type text,
  entity_id   text,
  persona_id  uuid REFERENCES personas(id) ON DELETE SET NULL,
  payload     jsonb DEFAULT '{}',
  created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS system_events_type_idx    ON system_events(event_type);
CREATE INDEX IF NOT EXISTS system_events_created_idx ON system_events(created_at DESC);
CREATE INDEX IF NOT EXISTS system_events_persona_idx ON system_events(persona_id);

-- ── Pipeline Status ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_status (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service       text UNIQUE NOT NULL,
  status        text DEFAULT 'unknown' CHECK (status IN
                  ('online','offline','degraded','pending','processing','error','unknown')),
  last_activity timestamptz,
  metrics       jsonb DEFAULT '{}',
  updated_at    timestamptz DEFAULT now()
);

INSERT INTO pipeline_status (service, status) VALUES
  ('vault_sync',           'unknown'),
  ('knowledge_intake',     'online'),
  ('knowledge_validation', 'online'),
  ('embedding_service',    'unknown'),
  ('flow_validator',       'online'),
  ('n8n_crm_vitoria',      'unknown'),
  ('supabase',             'online'),
  ('whatsapp_webhook',     'unknown'),
  ('mcp_figma',            'unknown')
ON CONFLICT (service) DO NOTHING;

-- ── knowledge_items: extended status options ──────────────────
ALTER TABLE knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_status_check;

ALTER TABLE knowledge_items
  ADD CONSTRAINT knowledge_items_status_check CHECK (status IN (
    'pending','reviewing','approved','rejected',
    'needs_persona','needs_category','processed','embedded'
  ));

-- New columns on knowledge_items
ALTER TABLE knowledge_items
  ADD COLUMN IF NOT EXISTS tags          text[]  DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS agent_visibility text[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS embedding_status text   DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS asset_type    text,
  ADD COLUMN IF NOT EXISTS asset_function text,
  ADD COLUMN IF NOT EXISTS campaign_id   uuid REFERENCES campaigns(id) ON DELETE SET NULL;

-- ── kb_entries: agent routing + embedding status ──────────────
ALTER TABLE kb_entries
  ADD COLUMN IF NOT EXISTS agent_visibility text[] DEFAULT '{"SDR","Closer","Classifier"}',
  ADD COLUMN IF NOT EXISTS embedding_status text    DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS tags             text[]  DEFAULT '{}';

-- ── assets: richer validation metadata ───────────────────────
ALTER TABLE assets
  ADD COLUMN IF NOT EXISTS asset_type     text,
  ADD COLUMN IF NOT EXISTS asset_function text,
  ADD COLUMN IF NOT EXISTS campaign_id    uuid REFERENCES campaigns(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS tags           text[]  DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS description    text,
  ADD COLUMN IF NOT EXISTS embedding_status text  DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS approval_status  text  DEFAULT 'approved'
    CHECK (approval_status IN ('pending','approved','rejected'));




-- ---------------------------------------------------------------------
-- File: 004_error_logging.sql
-- ---------------------------------------------------------------------

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




-- ---------------------------------------------------------------------
-- File: 005_kb_intake.sql
-- ---------------------------------------------------------------------

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




-- ---------------------------------------------------------------------
-- File: 006_knowledge_items_schema_fix.sql
-- ---------------------------------------------------------------------

-- 006_knowledge_items_schema_fix.sql
-- Add missing columns and expand status CHECK constraint on knowledge_items

ALTER TABLE knowledge_items
  ADD COLUMN IF NOT EXISTS tags jsonb DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS agent_visibility jsonb DEFAULT '["SDR","Closer","Classifier"]',
  ADD COLUMN IF NOT EXISTS asset_type text,
  ADD COLUMN IF NOT EXISTS asset_function text;

-- Drop the old restrictive CHECK constraint and replace with the full set of statuses
ALTER TABLE knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_status_check;

ALTER TABLE knowledge_items
  ADD CONSTRAINT knowledge_items_status_check
  CHECK (status IN (
    'pending',
    'needs_persona',
    'needs_category',
    'reviewing',
    'approved',
    'rejected',
    'embedded'
  ));




-- ---------------------------------------------------------------------
-- File: 007_agents_routing.sql
-- ---------------------------------------------------------------------

-- 007_agents_routing.sql
-- Per-persona agents (bots) and role routing (SDR / Closer / Followup).
-- Each persona has its own agents; each role is assigned to an agent
-- or to NULL (= human handoff). Multiple personas can have agents
-- with the same bot_name (e.g., two clients both naming a bot "Sofia").
-- Safe to run multiple times.

-- ── 1. agents ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.agents (
  id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id            UUID         NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  bot_name              TEXT         NOT NULL,
  description           TEXT,
  whatsapp_number       TEXT,                  -- E.164, ex: +5511999998888
  whatsapp_contact_name TEXT,                  -- nome no WhatsApp Web (E2E)
  n8n_webhook_url       TEXT,                  -- destino quando humano/AI envia
  n8n_webhook_secret    TEXT,                  -- HMAC opcional
  config                JSONB        NOT NULL DEFAULT '{}'::jsonb,
  active                BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  UNIQUE (persona_id, bot_name)
);

CREATE INDEX IF NOT EXISTS idx_agents_persona_id ON public.agents (persona_id);
CREATE INDEX IF NOT EXISTS idx_agents_active     ON public.agents (active);

-- ── 2. persona_role_assignments ──────────────────────────────
-- Quem cuida de cada role nessa persona.
-- agent_id = NULL  →  role atendida por humano.
CREATE TABLE IF NOT EXISTS public.persona_role_assignments (
  persona_id  UUID         NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  role        TEXT         NOT NULL CHECK (role IN ('sdr','closer','followup')),
  agent_id    UUID                  REFERENCES public.agents(id)   ON DELETE SET NULL,
  active      BOOLEAN      NOT NULL DEFAULT TRUE,
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (persona_id, role)
);

CREATE INDEX IF NOT EXISTS idx_role_assignments_agent_id ON public.persona_role_assignments (agent_id);

-- ── 3. leads.ai_paused ───────────────────────────────────────
-- Quando true, /process não roda agente para esse lead.
-- Usado para handoff manual ou automático (humano cuidando).
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS ai_paused BOOLEAN DEFAULT FALSE;

-- ── 4. messages.sender_id ────────────────────────────────────
-- Identifica QUAL humano (ou agent_id) enviou. Texto livre por ora.
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS sender_id TEXT;

-- ── 5. Seed: Tock Fatal → Sofia (SDR + Closer); followup = humano ──
-- Idempotente via ON CONFLICT.

INSERT INTO public.agents (persona_id, bot_name, description, whatsapp_contact_name)
SELECT id, 'Sofia', 'Agente de vendas principal do Tock Fatal', 'Sofia'
FROM public.personas WHERE slug = 'tock-fatal'
ON CONFLICT (persona_id, bot_name) DO NOTHING;

-- SDR → Sofia
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT p.id, 'sdr', a.id
FROM public.personas p
JOIN public.agents a ON a.persona_id = p.id AND a.bot_name = 'Sofia'
WHERE p.slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO UPDATE
  SET agent_id = EXCLUDED.agent_id,
      active   = TRUE,
      updated_at = now();

-- Closer → Sofia (mesma)
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT p.id, 'closer', a.id
FROM public.personas p
JOIN public.agents a ON a.persona_id = p.id AND a.bot_name = 'Sofia'
WHERE p.slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO UPDATE
  SET agent_id = EXCLUDED.agent_id,
      active   = TRUE,
      updated_at = now();

-- Followup → humano (agent_id NULL)
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT id, 'followup', NULL
FROM public.personas WHERE slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO NOTHING;




-- ---------------------------------------------------------------------
-- File: 008_knowledge_graph.sql
-- ---------------------------------------------------------------------

-- 008_knowledge_graph.sql
-- Semantic knowledge graph: nodes (entities) + edges (relations).
-- Aditive: nada existente é alterado. Tabelas atuais
--   (knowledge_items, kb_entries, knowledge_sources, sync_runs, sync_logs)
--   continuam intactas. Caso essas tabelas estejam vazias o sistema antigo
--   funciona normalmente.
-- Safe to run multiple times.

-- pg_trgm é usado para o índice de busca por similaridade no título.
-- Se a extensão não estiver disponível, o CREATE EXTENSION falha silenciosamente
-- via DO block; o índice trgm é depois tornado opcional.
DO $$
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
  EXCEPTION WHEN OTHERS THEN
    -- ignorar; busca cai pra ILIKE simples
    NULL;
  END;
END$$;

-- ── 1. knowledge_nodes ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.knowledge_nodes (
  id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id    UUID                  REFERENCES public.personas(id) ON DELETE CASCADE,
  source_table  TEXT,                                       -- 'knowledge_items' | 'kb_entries' | NULL
  source_id     UUID,                                       -- linha original (quando aplicável)
  node_type     TEXT         NOT NULL,                      -- persona | product | campaign | faq | copy | asset | rule | tone | audience | tag | kb_entry | knowledge_item
  slug          TEXT         NOT NULL,
  title         TEXT         NOT NULL,
  summary       TEXT,
  tags          TEXT[]       NOT NULL DEFAULT '{}',
  metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- asset_type, asset_function, file_path, etc.
  status        TEXT         NOT NULL DEFAULT 'active',
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Unique por (persona_id, node_type, slug). NULL persona_id é permitido como "global".
-- Usamos COALESCE para tratar NULL corretamente no UNIQUE INDEX.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_nodes_persona_type_slug
  ON public.knowledge_nodes (COALESCE(persona_id::text, ''), node_type, slug);

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_persona  ON public.knowledge_nodes (persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_type     ON public.knowledge_nodes (node_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_status   ON public.knowledge_nodes (status);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_tags     ON public.knowledge_nodes USING GIN (tags);

-- Trgm é ótimo, mas opcional — só cria se a extensão existir.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_title_trgm
             ON public.knowledge_nodes USING GIN (title gin_trgm_ops)';
  END IF;
END$$;

-- ── 2. knowledge_edges ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.knowledge_edges (
  id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID                  REFERENCES public.personas(id) ON DELETE CASCADE,
  source_node_id  UUID         NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,
  target_node_id  UUID         NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,
  relation_type   TEXT         NOT NULL, -- belongs_to_persona | about_product | part_of_campaign | supports_campaign | uses_asset | answers_question | supports_copy | has_tag | same_topic_as | visible_to_agent | mentions
  weight          NUMERIC      NOT NULL DEFAULT 1,
  metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_edges_triple
  ON public.knowledge_edges (source_node_id, target_node_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source   ON public.knowledge_edges (source_node_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_target   ON public.knowledge_edges (target_node_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_relation ON public.knowledge_edges (relation_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_persona  ON public.knowledge_edges (persona_id);




-- ---------------------------------------------------------------------
-- File: 009_knowledge_curation_architecture.sql
-- ---------------------------------------------------------------------

-- 009_knowledge_curation_architecture.sql
-- Canonical knowledge curation layer.
--
-- Goal:
--   Connect Git/vault files, intake queue rows, KB rows and semantic graph nodes
--   through one stable artifact identity. This prevents duplicate knowledge from
--   becoming separate "truths" and gives the KB Classifier/Curator a place to
--   propose merges, node hierarchy, importance and graph relations before apply.
--
-- Safe to run multiple times. Existing tables remain the source of operational
-- compatibility; this migration adds lineage and curation structure around them.

-- ── 1. Configurable ontology ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_node_type_registry (
  node_type           TEXT PRIMARY KEY,
  label               TEXT NOT NULL,
  description         TEXT,
  default_level       INT NOT NULL DEFAULT 50,
  default_importance  NUMERIC NOT NULL DEFAULT 0.50 CHECK (default_importance >= 0 AND default_importance <= 1),
  color               TEXT,
  icon                TEXT,
  config              JSONB NOT NULL DEFAULT '{}'::jsonb,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order          INT NOT NULL DEFAULT 100,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('entity',    'Entidade',  'Cliente, organização, pessoa, lugar ou conceito nomeado.', 10, 0.95, '#7c6fff', 'network',       10),
  ('brand',     'Brand',     'Identidade, posicionamento e atributos de marca.',         20, 0.90, '#a78bfa', 'badge',         20),
  ('campaign',  'Campanha',  'Ação comercial ou comunicação com objetivo próprio.',      30, 0.80, '#fb923c', 'megaphone',     30),
  ('product',   'Produto',   'Produto, categoria, coleção ou oferta.',                   40, 0.85, '#60a5fa', 'box',           40),
  ('briefing',  'Briefing',  'Contexto, estratégia, requisitos e instruções.',           50, 0.75, '#c084fc', 'file-text',      50),
  ('tone',      'Tom',       'Voz, estilo, vocabulário e restrições de linguagem.',       60, 0.70, '#22d3ee', 'palette',       60),
  ('copy',      'Copy',      'Texto reutilizável para mensagens, posts ou anúncios.',     70, 0.65, '#64748b', 'text',          70),
  ('faq',       'FAQ',       'Pergunta e resposta operacional.',                          75, 0.65, '#4ade80', 'circle-help',   75),
  ('asset',     'Asset',     'Arquivo visual, vídeo, logo, template ou material maker.',  80, 0.55, '#f59e0b', 'image',         80),
  ('rule',      'Regra',     'Política ou regra executável por agente.',                  65, 0.80, '#f87171', 'scale',         65),
  ('audience',  'Audiência', 'Público-alvo, persona compradora ou segmento.',             55, 0.70, '#f472b6', 'users',         55),
  ('persona',   'Persona',   'Raiz de escopo do cliente/persona no sistema.',              0, 1.00, '#7c6fff', 'user',           0),
  ('tag',       'Tag',       'Marcador auxiliar, não deve ser fonte primária de verdade.', 90, 0.30, '#94a3b8', 'tag',           90),
  ('knowledge_item', 'Fila', 'Espelho técnico de knowledge_items.',                       95, 0.40, '#94a3b8', 'inbox',         95),
  ('kb_entry',  'KB Entry',  'Espelho técnico de kb_entries.',                            95, 0.50, '#94a3b8', 'database',      96)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();

CREATE TABLE IF NOT EXISTS public.knowledge_relation_type_registry (
  relation_type       TEXT PRIMARY KEY,
  label               TEXT NOT NULL,
  inverse_label       TEXT,
  source_node_types   TEXT[] NOT NULL DEFAULT '{}',
  target_node_types   TEXT[] NOT NULL DEFAULT '{}',
  default_weight      NUMERIC NOT NULL DEFAULT 1 CHECK (default_weight >= 0),
  directional         BOOLEAN NOT NULL DEFAULT TRUE,
  config              JSONB NOT NULL DEFAULT '{}'::jsonb,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order          INT NOT NULL DEFAULT 100,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order)
VALUES
  ('belongs_to_persona', 'pertence à persona', 'possui', '{}', '{"persona"}', 1.00, TRUE, 10),
  ('defines_brand',      'define brand',       'é definido por', '{"briefing","rule","tone"}', '{"brand"}', 0.90, TRUE, 20),
  ('has_tone',           'usa tom',            'tom de', '{"brand","campaign","product","copy"}', '{"tone"}', 0.80, TRUE, 30),
  ('about_product',      'sobre produto',      'tem conhecimento', '{}', '{"product"}', 0.85, TRUE, 40),
  ('part_of_campaign',   'parte da campanha',  'contém', '{"product","copy","asset","faq","briefing"}', '{"campaign"}', 0.75, TRUE, 50),
  ('answers_question',   'responde pergunta',  'é respondido por', '{"faq","kb_entry"}', '{"product","campaign","brand","entity"}', 0.80, TRUE, 60),
  ('supports_copy',      'suporta copy',       'é suportado por', '{"copy"}', '{"product","campaign","brand"}', 0.70, TRUE, 70),
  ('uses_asset',         'usa asset',          'é usado por', '{"product","campaign","copy","brand"}', '{"asset"}', 0.65, TRUE, 80),
  ('briefed_by',         'briefado por',       'briefa', '{"product","campaign","copy","asset"}', '{"briefing"}', 0.70, TRUE, 90),
  ('same_topic_as',      'mesmo tópico',       'mesmo tópico', '{}', '{}', 0.45, FALSE, 100),
  ('duplicate_of',       'duplicado de',       'tem duplicado', '{}', '{}', 1.00, TRUE, 110),
  ('derived_from',       'derivado de',        'origina', '{}', '{}', 0.90, TRUE, 120),
  ('contains',           'contém',             'contido em', '{}', '{}', 0.75, TRUE, 130)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();

-- ── 2. Canonical artifact layer ───────────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_artifacts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id            UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  canonical_key         TEXT NOT NULL,
  canonical_hash        TEXT NOT NULL,
  title                 TEXT NOT NULL,
  content_type          TEXT NOT NULL,
  summary               TEXT,
  curation_status       TEXT NOT NULL DEFAULT 'pending'
                        CHECK (curation_status IN ('pending','proposed','validated','rejected','stale','duplicate')),
  importance            NUMERIC NOT NULL DEFAULT 0.50 CHECK (importance >= 0 AND importance <= 1),
  level                 INT NOT NULL DEFAULT 50,
  confidence            NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  duplicate_of          UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  current_knowledge_item_id UUID REFERENCES public.knowledge_items(id) ON DELETE SET NULL,
  current_kb_entry_id       UUID REFERENCES public.kb_entries(id) ON DELETE SET NULL,
  vault_file_path       TEXT,
  source_uri            TEXT,
  git_remote_url        TEXT,
  git_branch            TEXT,
  git_commit_sha        TEXT,
  content_hash          TEXT,
  classifier_agent_id   UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_artifacts_persona_hash
  ON public.knowledge_artifacts (COALESCE(persona_id::text, ''), canonical_hash);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_persona ON public.knowledge_artifacts(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_type ON public.knowledge_artifacts(content_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_status ON public.knowledge_artifacts(curation_status);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_importance ON public.knowledge_artifacts(importance DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_duplicate_of ON public.knowledge_artifacts(duplicate_of);

CREATE TABLE IF NOT EXISTS public.knowledge_artifact_versions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id       UUID NOT NULL REFERENCES public.knowledge_artifacts(id) ON DELETE CASCADE,
  version_no        INT NOT NULL,
  source_table      TEXT NOT NULL CHECK (source_table IN ('knowledge_items','kb_entries','manual','vault','classifier')),
  source_id         UUID,
  title             TEXT,
  content_type      TEXT,
  content_hash      TEXT,
  raw_content       TEXT,
  classification    JSONB NOT NULL DEFAULT '{}'::jsonb,
  vault_file_path   TEXT,
  git_commit_sha    TEXT,
  created_by_agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, version_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_artifact_versions_source
  ON public.knowledge_artifact_versions (source_table, source_id)
  WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_artifact_versions_artifact ON public.knowledge_artifact_versions(artifact_id);

-- ── 3. Classifier/curator prompts, skills and proposals ───────────

CREATE TABLE IF NOT EXISTS public.agent_prompt_profiles (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_role     TEXT NOT NULL,
  name           TEXT NOT NULL,
  version        TEXT NOT NULL DEFAULT 'v1',
  system_prompt  TEXT NOT NULL,
  tools          TEXT[] NOT NULL DEFAULT '{}',
  skills         TEXT[] NOT NULL DEFAULT '{}',
  config         JSONB NOT NULL DEFAULT '{}'::jsonb,
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (agent_role, name, version)
);

INSERT INTO public.agent_prompt_profiles
  (agent_role, name, version, system_prompt, tools, skills, config)
VALUES
  (
    'classifier',
    'kb-classifier-curator',
    'v1',
    'Voce e o KB Classifier/Curator. Classifique conhecimento, detecte duplicatas, proponha artifact canonical_key, node_type, relacoes, importancia, nivel, confianca e acao de curadoria. Nunca aplique mutacoes destrutivas sem proposta auditavel.',
    '{"vault_write","git_add_commit_push","vault_sync","graph_bootstrap","duplicate_lookup"}',
    '{"classification","curation","deduplication","graph_modeling"}',
    '{"max_questions":2,"proposal_required":true,"duplicate_policy":"propose_merge"}'::jsonb
  )
ON CONFLICT (agent_role, name, version) DO UPDATE SET
  system_prompt = EXCLUDED.system_prompt,
  tools = EXCLUDED.tools,
  skills = EXCLUDED.skills,
  config = EXCLUDED.config,
  updated_at = now();

CREATE TABLE IF NOT EXISTS public.knowledge_curation_runs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id       UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  agent_id         UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  prompt_profile_id UUID REFERENCES public.agent_prompt_profiles(id) ON DELETE SET NULL,
  mode             TEXT NOT NULL DEFAULT 'dry_run'
                   CHECK (mode IN ('dry_run','apply','intake','reprocess')),
  status           TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','completed','failed','cancelled')),
  input_scope      JSONB NOT NULL DEFAULT '{}'::jsonb,
  stats            JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message    TEXT,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_curation_runs_persona ON public.knowledge_curation_runs(persona_id);
CREATE INDEX IF NOT EXISTS idx_curation_runs_status ON public.knowledge_curation_runs(status);

CREATE TABLE IF NOT EXISTS public.knowledge_curation_proposals (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            UUID REFERENCES public.knowledge_curation_runs(id) ON DELETE SET NULL,
  persona_id        UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  artifact_id       UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  proposal_type     TEXT NOT NULL CHECK (proposal_type IN (
                       'create_artifact','update_artifact','create_node','update_node',
                       'create_edge','update_edge','merge_duplicate','reclassify',
                       'validate','reject','stale'
                     )),
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','applied','rejected','superseded','failed')),
  target_table      TEXT,
  target_id         UUID,
  duplicate_of_artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  confidence        NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  priority          INT NOT NULL DEFAULT 50,
  rationale         TEXT,
  source_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
  proposed_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
  applied_at        TIMESTAMPTZ,
  created_by_agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  reviewed_by       TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_curation_proposals_status ON public.knowledge_curation_proposals(status);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_artifact ON public.knowledge_curation_proposals(artifact_id);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_persona ON public.knowledge_curation_proposals(persona_id);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_type ON public.knowledge_curation_proposals(proposal_type);

-- ── 4. Attach existing operational tables to artifacts ────────────

ALTER TABLE public.knowledge_items
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS canonical_hash TEXT,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS git_commit_sha TEXT,
  ADD COLUMN IF NOT EXISTS curation_status TEXT DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

ALTER TABLE public.kb_entries
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS canonical_hash TEXT,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS curation_status TEXT DEFAULT 'validated',
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

ALTER TABLE public.knowledge_nodes
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD COLUMN IF NOT EXISTS curation_proposal_id UUID REFERENCES public.knowledge_curation_proposals(id) ON DELETE SET NULL;

ALTER TABLE public.knowledge_edges
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD COLUMN IF NOT EXISTS curation_proposal_id UUID REFERENCES public.knowledge_curation_proposals(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_items_artifact ON public.knowledge_items(artifact_id);
CREATE INDEX IF NOT EXISTS idx_kb_entries_artifact ON public.kb_entries(artifact_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_artifact ON public.knowledge_nodes(artifact_id);

-- ── 5. Backfill canonical artifact records ────────────────────────
-- Canonical hash intentionally ignores content so repeated saves of the same
-- concept converge into one artifact. content_hash tracks version changes.

WITH ki_src AS (
  SELECT DISTINCT ON (
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    ki.*,
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash,
    concat_ws(':', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))) AS computed_canonical_key
  FROM public.knowledge_items ki
  ORDER BY
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE ki.status WHEN 'embedded' THEN 1 WHEN 'approved' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
    ki.updated_at DESC NULLS LAST,
    ki.created_at DESC NULLS LAST
)
INSERT INTO public.knowledge_artifacts (
  persona_id, canonical_key, canonical_hash, title, content_type, summary,
  curation_status, importance, level, confidence,
  current_knowledge_item_id, vault_file_path, content_hash, metadata,
  created_at, updated_at
)
SELECT
  ki.persona_id,
  ki.computed_canonical_key,
  ki.computed_canonical_hash,
  ki.title,
  ki.content_type,
  left(ki.content, 500),
  CASE
    WHEN ki.status IN ('approved','embedded') THEN 'validated'
    WHEN ki.status = 'rejected' THEN 'rejected'
    ELSE 'pending'
  END,
  COALESCE((ki.metadata->>'importance')::numeric, tr.default_importance, 0.50),
  COALESCE((ki.metadata->>'level')::int, tr.default_level, 50),
  NULL,
  ki.id,
  ki.file_path,
  md5(COALESCE(ki.content, '')),
  jsonb_build_object('backfilled_from', 'knowledge_items', 'source_id', ki.source_id),
  ki.created_at,
  ki.updated_at
FROM ki_src ki
LEFT JOIN public.knowledge_node_type_registry tr ON tr.node_type = ki.content_type
ON CONFLICT DO NOTHING;

WITH ki_current AS (
  SELECT DISTINCT ON (
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    ki.*,
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash
  FROM public.knowledge_items ki
  ORDER BY
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE ki.status WHEN 'embedded' THEN 1 WHEN 'approved' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
    ki.updated_at DESC NULLS LAST,
    ki.created_at DESC NULLS LAST
)
UPDATE public.knowledge_artifacts a
SET
  current_knowledge_item_id = COALESCE(a.current_knowledge_item_id, ki.id),
  vault_file_path = COALESCE(a.vault_file_path, ki.file_path),
  content_hash = COALESCE(a.content_hash, md5(COALESCE(ki.content, ''))),
  updated_at = now()
FROM ki_current ki
WHERE a.canonical_hash = ki.computed_canonical_hash
  AND COALESCE(a.persona_id::text, '') = COALESCE(ki.persona_id::text, '')
  AND (
    a.current_knowledge_item_id IS NULL
    OR a.vault_file_path IS NULL
    OR a.content_hash IS NULL
  );

UPDATE public.knowledge_items ki
SET
  canonical_key = a.canonical_key,
  canonical_hash = a.canonical_hash,
  content_hash = md5(COALESCE(ki.content, '')),
  artifact_id = a.id,
  importance = COALESCE(ki.importance, a.importance),
  level = COALESCE(ki.level, a.level),
  curation_status = CASE
    WHEN ki.status IN ('approved','embedded') THEN 'validated'
    WHEN ki.status = 'rejected' THEN 'rejected'
    ELSE COALESCE(ki.curation_status, 'pending')
  END
FROM public.knowledge_artifacts a
WHERE a.canonical_hash = md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  AND COALESCE(a.persona_id::text, '') = COALESCE(ki.persona_id::text, '');

INSERT INTO public.knowledge_artifact_versions (
  artifact_id, version_no, source_table, source_id, title, content_type,
  content_hash, raw_content, classification, vault_file_path, git_commit_sha, created_at
)
SELECT
  ki.artifact_id,
  row_number() OVER (PARTITION BY ki.artifact_id ORDER BY ki.created_at, ki.id)::int,
  'knowledge_items',
  ki.id,
  ki.title,
  ki.content_type,
  ki.content_hash,
  ki.content,
  COALESCE(ki.metadata, '{}'::jsonb),
  ki.file_path,
  ki.git_commit_sha,
  ki.created_at
FROM public.knowledge_items ki
WHERE ki.artifact_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- Backfill KB entries as artifact links. Tipo is normalized only enough for
-- curation; the old tipo/categoria fields remain untouched.
WITH kb_norm AS (
  SELECT
    kb.*,
    CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
      WHEN 'produto' THEN 'product'
      WHEN 'campanha' THEN 'campaign'
      WHEN 'tom' THEN 'tone'
      WHEN 'regra' THEN 'rule'
      WHEN 'maker' THEN 'maker_material'
      WHEN 'geral' THEN 'other'
      ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
    END AS normalized_type
  FROM public.kb_entries kb
),
kb_src AS (
  SELECT DISTINCT ON (
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    kb.*,
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash,
    concat_ws(':', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))) AS computed_canonical_key
  FROM kb_norm kb
  ORDER BY
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE kb.status WHEN 'ATIVO' THEN 1 WHEN 'active' THEN 1 WHEN 'validated' THEN 1 ELSE 2 END,
    kb.updated_at DESC NULLS LAST,
    kb.created_at DESC NULLS LAST
)
INSERT INTO public.knowledge_artifacts (
  persona_id, canonical_key, canonical_hash, title, content_type, summary,
  curation_status, importance, level, confidence,
  current_kb_entry_id, source_uri, content_hash, metadata,
  created_at, updated_at
)
SELECT
  kb.persona_id,
  kb.computed_canonical_key,
  kb.computed_canonical_hash,
  kb.titulo,
  kb.normalized_type,
  left(kb.conteudo, 500),
  CASE WHEN kb.status IN ('ATIVO','active','validated') THEN 'validated' ELSE 'pending' END,
  COALESCE(kb.prioridade, 99)::numeric / 100.0,
  COALESCE(tr.default_level, 50),
  NULL,
  kb.id,
  kb.link,
  md5(COALESCE(kb.conteudo, '')),
  jsonb_build_object('backfilled_from', 'kb_entries', 'kb_id', kb.kb_id, 'tipo', kb.tipo, 'categoria', kb.categoria),
  kb.created_at,
  kb.updated_at
FROM kb_src kb
LEFT JOIN public.knowledge_node_type_registry tr ON tr.node_type = kb.normalized_type
ON CONFLICT DO NOTHING;

WITH kb_current AS (
  SELECT DISTINCT ON (
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    kb.*,
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash
  FROM (
    SELECT
      kb.*,
      CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
        WHEN 'produto' THEN 'product'
        WHEN 'campanha' THEN 'campaign'
        WHEN 'tom' THEN 'tone'
        WHEN 'regra' THEN 'rule'
        WHEN 'maker' THEN 'maker_material'
        WHEN 'geral' THEN 'other'
        ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
      END AS normalized_type
    FROM public.kb_entries kb
  ) kb
  ORDER BY
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE kb.status WHEN 'ATIVO' THEN 1 WHEN 'active' THEN 1 WHEN 'validated' THEN 1 ELSE 2 END,
    kb.updated_at DESC NULLS LAST,
    kb.created_at DESC NULLS LAST
)
UPDATE public.knowledge_artifacts a
SET
  current_kb_entry_id = COALESCE(a.current_kb_entry_id, kb.id),
  source_uri = COALESCE(a.source_uri, kb.link),
  content_hash = COALESCE(a.content_hash, md5(COALESCE(kb.conteudo, ''))),
  updated_at = now()
FROM kb_current kb
WHERE a.canonical_hash = kb.computed_canonical_hash
  AND COALESCE(a.persona_id::text, '') = COALESCE(kb.persona_id::text, '')
  AND (
    a.current_kb_entry_id IS NULL
    OR a.source_uri IS NULL
    OR a.content_hash IS NULL
  );

WITH kb_norm AS (
  SELECT
    kb.*,
    CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
      WHEN 'produto' THEN 'product'
      WHEN 'campanha' THEN 'campaign'
      WHEN 'tom' THEN 'tone'
      WHEN 'regra' THEN 'rule'
      WHEN 'maker' THEN 'maker_material'
      WHEN 'geral' THEN 'other'
      ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
    END AS normalized_type
  FROM public.kb_entries kb
)
UPDATE public.kb_entries kb
SET
  canonical_key = a.canonical_key,
  canonical_hash = a.canonical_hash,
  content_hash = md5(COALESCE(kb.conteudo, '')),
  artifact_id = a.id,
  importance = COALESCE(kb.importance, a.importance),
  level = COALESCE(kb.level, a.level),
  curation_status = CASE WHEN kb.status IN ('ATIVO','active','validated') THEN 'validated' ELSE COALESCE(kb.curation_status, 'pending') END
FROM kb_norm n
JOIN public.knowledge_artifacts a
  ON a.canonical_hash = md5(concat_ws('|', COALESCE(n.persona_id::text, 'global'), n.normalized_type, lower(regexp_replace(n.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
 AND COALESCE(a.persona_id::text, '') = COALESCE(n.persona_id::text, '')
WHERE kb.id = n.id;

INSERT INTO public.knowledge_artifact_versions (
  artifact_id, version_no, source_table, source_id, title, content_type,
  content_hash, raw_content, classification, vault_file_path, created_at
)
SELECT
  kb.artifact_id,
  COALESCE(existing.max_version_no, 0)
    + row_number() OVER (PARTITION BY kb.artifact_id ORDER BY kb.created_at, kb.id)::int,
  'kb_entries',
  kb.id,
  kb.titulo,
  COALESCE(kb.categoria, kb.tipo, 'other'),
  kb.content_hash,
  kb.conteudo,
  jsonb_build_object('kb_id', kb.kb_id, 'tipo', kb.tipo, 'categoria', kb.categoria, 'produto', kb.produto, 'tags', kb.tags),
  kb.link,
  kb.created_at
FROM public.kb_entries kb
LEFT JOIN (
  SELECT artifact_id, max(version_no) AS max_version_no
  FROM public.knowledge_artifact_versions
  GROUP BY artifact_id
) existing ON existing.artifact_id = kb.artifact_id
WHERE kb.artifact_id IS NOT NULL
ON CONFLICT DO NOTHING;

UPDATE public.knowledge_nodes n
SET
  artifact_id = ki.artifact_id,
  canonical_key = COALESCE(ki.canonical_key, n.canonical_key),
  importance = COALESCE(
    n.importance,
    ki.importance,
    (SELECT tr.default_importance FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    0.50
  ),
  level = COALESCE(
    n.level,
    ki.level,
    (SELECT tr.default_level FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    50
  )
FROM public.knowledge_items ki
WHERE n.source_table = 'knowledge_items'
  AND n.source_id = ki.id;

UPDATE public.knowledge_nodes n
SET
  artifact_id = kb.artifact_id,
  canonical_key = COALESCE(kb.canonical_key, n.canonical_key),
  importance = COALESCE(
    n.importance,
    kb.importance,
    (SELECT tr.default_importance FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    0.50
  ),
  level = COALESCE(
    n.level,
    kb.level,
    (SELECT tr.default_level FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    50
  )
FROM public.kb_entries kb
WHERE n.source_table = 'kb_entries'
  AND n.source_id = kb.id;

UPDATE public.knowledge_nodes n
SET
  importance = COALESCE(n.importance, tr.default_importance),
  level = COALESCE(n.level, tr.default_level)
FROM public.knowledge_node_type_registry tr
WHERE tr.node_type = n.node_type;

-- ── 6. Operational audit views ────────────────────────────────────

CREATE OR REPLACE VIEW public.v_knowledge_lineage AS
SELECT
  a.id AS artifact_id,
  a.persona_id,
  p.slug AS persona_slug,
  a.title,
  a.content_type,
  a.curation_status,
  a.importance,
  a.level,
  a.confidence,
  a.vault_file_path,
  a.git_commit_sha,
  a.current_knowledge_item_id,
  a.current_kb_entry_id,
  count(DISTINCT n.id) AS graph_nodes,
  count(DISTINCT v.id) AS versions
FROM public.knowledge_artifacts a
LEFT JOIN public.personas p ON p.id = a.persona_id
LEFT JOIN public.knowledge_nodes n ON n.artifact_id = a.id
LEFT JOIN public.knowledge_artifact_versions v ON v.artifact_id = a.id
GROUP BY a.id, p.slug;

CREATE OR REPLACE VIEW public.v_knowledge_curation_backlog AS
SELECT
  a.id AS artifact_id,
  a.persona_id,
  p.slug AS persona_slug,
  a.title,
  a.content_type,
  a.curation_status,
  a.importance,
  a.level,
  a.confidence,
  a.duplicate_of,
  a.canonical_key,
  a.canonical_hash,
  a.current_knowledge_item_id,
  a.current_kb_entry_id,
  a.created_at,
  a.updated_at,
  CASE
    WHEN a.duplicate_of IS NOT NULL THEN 'duplicate'
    WHEN a.curation_status IN ('pending','proposed') THEN 'needs_review'
    WHEN NOT EXISTS (SELECT 1 FROM public.knowledge_nodes n WHERE n.artifact_id = a.id) THEN 'missing_graph'
    ELSE 'ok'
  END AS backlog_reason
FROM public.knowledge_artifacts a
LEFT JOIN public.personas p ON p.id = a.persona_id
WHERE a.curation_status IN ('pending','proposed','duplicate')
   OR a.duplicate_of IS NOT NULL
   OR NOT EXISTS (SELECT 1 FROM public.knowledge_nodes n WHERE n.artifact_id = a.id);




-- ---------------------------------------------------------------------
-- File: 010_knowledge_validation_rules.sql
-- ---------------------------------------------------------------------

-- 010_knowledge_validation_rules.sql
--
-- Camada de regras de validacao de conteudo por tipo de conhecimento.
--
-- Goal:
--   Tornar regras como "todo produto deve ter preco" configuraveis em vez de
--   espalhadas em codigo. Cada regra aponta para um content_type/node_type e
--   um JSON Pointer dentro de metadata. Curator/classifier consulta esta
--   tabela para decidir entre validar artifact ou abrir proposta.
--
-- Safe to run multiple times. Nao toca em dados de cliente.

-- ── 1. Regras configuraveis por tipo ─────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_validation_rules (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key        TEXT NOT NULL UNIQUE,            -- ex: 'product.price.required'
  applies_to      TEXT NOT NULL,                   -- content_type/node_type alvo (ex 'product')
  scope           TEXT NOT NULL DEFAULT 'artifact' -- 'artifact' | 'node' | 'both'
                  CHECK (scope IN ('artifact','node','both')),
  description     TEXT,
  -- ── O que avaliar ──
  -- field_path: caminho dentro do metadata jsonb (notacao 'a.b.c').
  -- O field_path null + check_kind 'custom' permite usar custom_predicate.
  field_path      TEXT,
  check_kind      TEXT NOT NULL DEFAULT 'present_non_null'
                  CHECK (check_kind IN (
                    'present_non_null',     -- campo existe e nao e null/''/[]
                    'numeric_positive',     -- numero > 0
                    'currency_object',      -- {amount, currency, display}
                    'enum',                 -- valor em config.allowed
                    'regex',                -- match config.pattern
                    'custom'                -- avaliado em codigo
                  )),
  -- Config livre por kind (ex: {"allowed":["BRL","USD"]} ou {"pattern":"^https?://"})
  config          JSONB NOT NULL DEFAULT '{}'::jsonb,
  severity        TEXT NOT NULL DEFAULT 'block'    -- block: impede validar; warn: cria proposta mas valida
                  CHECK (severity IN ('block','warn','info')),
  -- O que fazer quando a regra falha
  on_violation    TEXT NOT NULL DEFAULT 'propose_correction'
                  CHECK (on_violation IN (
                    'propose_correction',   -- abre knowledge_curation_proposals
                    'mark_pending',         -- mantem artifact pending
                    'reject',               -- artifact -> 'rejected'
                    'noop'
                  )),
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validation_rules_applies_to
  ON public.knowledge_validation_rules(applies_to)
  WHERE active = TRUE;

-- ── 2. Seed: regras de produto que ja podemos exigir hoje ────────
-- (Idempotente. Operadores podem desativar via UPDATE active=false)

INSERT INTO public.knowledge_validation_rules
  (rule_key, applies_to, scope, description, field_path, check_kind, config, severity, on_violation)
VALUES
  ('product.price.required',
   'product', 'both',
   'Todo produto validado precisa carregar preco estruturado em metadata.price.',
   'price', 'currency_object',
   '{"required_keys":["amount","currency","display"]}'::jsonb,
   'block', 'propose_correction'),

  ('product.price.amount.positive',
   'product', 'both',
   'metadata.price.amount deve ser numero > 0.',
   'price.amount', 'numeric_positive',
   '{}'::jsonb,
   'block', 'propose_correction'),

  ('product.price.currency.iso',
   'product', 'both',
   'metadata.price.currency deve ser ISO de 3 letras.',
   'price.currency', 'regex',
   '{"pattern":"^[A-Z]{3}$"}'::jsonb,
   'warn', 'propose_correction'),

  ('product.colors_count.numeric',
   'product', 'both',
   'metadata.colors_count, quando presente, deve ser numerico positivo.',
   'colors_count', 'numeric_positive',
   '{"allow_null":true}'::jsonb,
   'info', 'noop'),

  ('asset.url_or_file_path.required',
   'asset', 'both',
   'Asset valido precisa ter file_path ou metadata.url.',
   NULL, 'custom',
   '{"any_of":["file_path","url"]}'::jsonb,
   'warn', 'propose_correction')
ON CONFLICT (rule_key) DO UPDATE SET
  applies_to     = EXCLUDED.applies_to,
  scope          = EXCLUDED.scope,
  description    = EXCLUDED.description,
  field_path     = EXCLUDED.field_path,
  check_kind     = EXCLUDED.check_kind,
  config         = EXCLUDED.config,
  severity       = EXCLUDED.severity,
  on_violation   = EXCLUDED.on_violation,
  updated_at     = now();

-- ── 3. View: artifacts com violacao ativa ────────────────────────
-- Heuristica simples para casos sem custom predicate. Curator/teste
-- usam isto como ponto de partida para abrir proposals.

CREATE OR REPLACE VIEW public.v_knowledge_validation_failures AS
WITH rule_targets AS (
  SELECT
    r.id          AS rule_id,
    r.rule_key,
    r.applies_to,
    r.field_path,
    r.check_kind,
    r.config,
    r.severity,
    r.on_violation,
    a.id          AS artifact_id,
    a.persona_id,
    a.title,
    a.content_type,
    a.curation_status,
    a.metadata
  FROM public.knowledge_validation_rules r
  JOIN public.knowledge_artifacts a
    ON a.content_type = r.applies_to
  WHERE r.active = TRUE
    AND r.scope IN ('artifact','both')
    AND r.check_kind <> 'custom'
),
observed AS (
  SELECT
    t.*,
    CASE
      WHEN t.field_path IS NULL THEN NULL
      ELSE t.metadata #> string_to_array(t.field_path, '.')
    END AS observed_value,
    CASE
      WHEN t.field_path IS NULL THEN NULL
      ELSE t.metadata #>> string_to_array(t.field_path, '.')
    END AS observed_text
  FROM rule_targets t
)
SELECT
  rule_id,
  rule_key,
  artifact_id,
  persona_id,
  title,
  content_type,
  curation_status,
  field_path,
  severity,
  on_violation,
  observed_value
FROM observed t
WHERE
  -- present_non_null: campo presente e nao e null/''/[]
  (check_kind = 'present_non_null'
   AND (field_path IS NULL
        OR observed_value IS NULL
        OR observed_value = 'null'::jsonb
        OR observed_text = ''
        OR (jsonb_typeof(observed_value) = 'array' AND jsonb_array_length(observed_value) = 0)))
  OR
  -- numeric_positive: ausente, nao numerico, ou <= 0
  (check_kind = 'numeric_positive'
   AND CASE
         WHEN observed_value IS NULL OR observed_value = 'null'::jsonb
           THEN COALESCE((config->>'allow_null')::boolean, FALSE) = FALSE
         WHEN jsonb_typeof(observed_value) <> 'number'
           THEN TRUE
         ELSE (observed_value::text)::numeric <= 0
       END)
  OR
  -- currency_object: precisa ser jsonb object com amount/currency/display
  (check_kind = 'currency_object'
   AND (jsonb_typeof(observed_value) IS DISTINCT FROM 'object'
        OR observed_value->'amount'   IS NULL
        OR observed_value->'currency' IS NULL
        OR observed_value->'display'  IS NULL
        OR jsonb_typeof(observed_value->'amount') <> 'number'
        OR CASE
             WHEN jsonb_typeof(observed_value->'amount') = 'number'
             THEN (observed_value->>'amount')::numeric <= 0
             ELSE TRUE
           END))
  OR
  -- regex: ausente OU nao casa
  (check_kind = 'regex'
   AND (observed_text IS NULL
        OR observed_text !~ COALESCE(t.config->>'pattern', '^$')));

COMMENT ON VIEW public.v_knowledge_validation_failures IS
  'Artefatos que violam regras ativas de knowledge_validation_rules. Curator deve gerar knowledge_curation_proposals para os com on_violation=propose_correction. Regras com check_kind=custom sao avaliadas no codigo, nao por esta view.';

-- ── 4. View especializada: produtos sem preco valido ─────────────

CREATE OR REPLACE VIEW public.v_knowledge_products_missing_price AS
WITH product_prices AS (
  SELECT
    a.id           AS artifact_id,
    a.persona_id,
    a.title,
    a.curation_status,
    a.metadata,
    a.metadata->'price' AS price
  FROM public.knowledge_artifacts a
  WHERE a.content_type = 'product'
)
SELECT
  artifact_id,
  persona_id,
  title,
  curation_status,
  metadata
FROM product_prices
WHERE
     jsonb_typeof(price) IS DISTINCT FROM 'object'
  OR price->'amount'   IS NULL
  OR price->'currency' IS NULL
  OR price->'display'  IS NULL
  OR jsonb_typeof(price->'amount') <> 'number'
  OR CASE
       WHEN jsonb_typeof(price->'amount') = 'number'
       THEN (price->>'amount')::numeric <= 0
       ELSE TRUE
     END;




-- ---------------------------------------------------------------------
-- File: 011_persona_routing.sql
-- ---------------------------------------------------------------------

-- 011_persona_routing.sql
-- Adds per-persona routing mode (internal vs n8n) and webhook config.
-- Backwards compatible: process_mode defaults to 'internal' so the existing
-- /process flow keeps working untouched until a persona opts into n8n mode.

ALTER TABLE personas
  ADD COLUMN IF NOT EXISTS process_mode TEXT
    DEFAULT 'internal'
    CHECK (process_mode IN ('internal', 'n8n'));

ALTER TABLE personas
  ADD COLUMN IF NOT EXISTS outbound_webhook_url TEXT;

ALTER TABLE personas
  ADD COLUMN IF NOT EXISTS outbound_webhook_secret TEXT;

-- Token expected in the X-Webhook-Token header when n8n calls POST /process
-- on this persona's behalf. Optional — when null, /process accepts any caller.
ALTER TABLE personas
  ADD COLUMN IF NOT EXISTS inbound_webhook_token TEXT;

COMMENT ON COLUMN personas.process_mode IS
  'internal = Brain AI classifies + replies + sends. n8n = Brain AI only persists; n8n owns the reply.';
COMMENT ON COLUMN personas.outbound_webhook_url IS
  'Webhook used by /messages/send to deliver human/operator replies to WhatsApp via n8n. Used in BOTH process_modes.';
COMMENT ON COLUMN personas.inbound_webhook_token IS
  'Shared secret expected in X-Webhook-Token header when n8n calls POST /process for this persona.';




-- ---------------------------------------------------------------------
-- File: 012_lead_whatsapp_phone_number_id.sql
-- ---------------------------------------------------------------------

-- 012_lead_whatsapp_phone_number_id.sql
-- Stores the WhatsApp Business phone_number_id that owns/responds to a lead.
-- This is required for human handoff: messages sent from Brain AI to n8n need
-- to know which WhatsApp number should send the operator reply.

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id TEXT;

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id TEXT;

ALTER TABLE workflow_bindings
  ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id TEXT;

COMMENT ON COLUMN leads.whatsapp_phone_number_id IS
  'WhatsApp Business phone_number_id currently responsible for sending replies to this lead.';

COMMENT ON COLUMN messages.whatsapp_phone_number_id IS
  'WhatsApp Business phone_number_id used or expected for this message.';

COMMENT ON COLUMN workflow_bindings.whatsapp_phone_number_id IS
  'Default WhatsApp Business phone_number_id for this persona/workflow binding.';

-- Sofia bot / Tock Fatal current WhatsApp Business sender.
UPDATE workflow_bindings wb
SET whatsapp_phone_number_id = '949967854877404'
FROM personas p
WHERE wb.persona_id = p.id
  AND p.slug = 'tock-fatal'
  AND (wb.whatsapp_phone_number_id IS NULL OR wb.whatsapp_phone_number_id = '');

-- Backfill existing Tock leads so operator replies from Brain AI know which
-- WhatsApp Business number must send the message.
UPDATE leads l
SET whatsapp_phone_number_id = '949967854877404'
FROM personas p
WHERE l.persona_id = p.id
  AND p.slug = 'tock-fatal'
  AND (l.whatsapp_phone_number_id IS NULL OR l.whatsapp_phone_number_id = '');




-- ---------------------------------------------------------------------
-- File: 013_knowledge_rag_intake.sql
-- ---------------------------------------------------------------------

-- 013_knowledge_rag_intake.sql
-- Database-first KB intake and RAG-ready knowledge layer.
-- Keeps legacy knowledge_items/kb_entries intact while adding canonical,
-- chunkable entries designed for retrieval and graph promotion.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.knowledge_intake_messages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id    UUID REFERENCES public.personas(id) ON DELETE SET NULL,
  source        TEXT NOT NULL DEFAULT 'manual',
  source_ref    TEXT,
  raw_text      TEXT NOT NULL,
  raw_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
  submitted_by  TEXT,
  status        TEXT NOT NULL DEFAULT 'received'
                CHECK (status IN (
                  'received',
                  'classified',
                  'rag_created',
                  'pending_validation',
                  'validated',
                  'rejected',
                  'duplicate',
                  'error'
                )),
  processed_at  TIMESTAMPTZ,
  error         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_intake_persona
  ON public.knowledge_intake_messages(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_intake_status
  ON public.knowledge_intake_messages(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_intake_created
  ON public.knowledge_intake_messages(created_at DESC);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_entries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  artifact_id     UUID,
  intake_id       UUID REFERENCES public.knowledge_intake_messages(id) ON DELETE SET NULL,

  content_type    TEXT NOT NULL CHECK (content_type IN (
                    'faq',
                    'product',
                    'brand',
                    'campaign',
                    'rule',
                    'tone',
                    'copy',
                    'briefing',
                    'asset',
                    'entity',
                    'general_note'
                  )),
  semantic_level  INT NOT NULL DEFAULT 50,

  title           TEXT NOT NULL,
  question        TEXT,
  answer          TEXT,
  content         TEXT NOT NULL,
  summary         TEXT,

  canonical_key   TEXT NOT NULL,
  slug            TEXT NOT NULL,

  language        TEXT NOT NULL DEFAULT 'pt-BR',
  status          TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN (
                    'draft',
                    'pending_embedding',
                    'pending_validation',
                    'validated',
                    'active',
                    'rejected',
                    'duplicate',
                    'stale'
                  )),

  tags            TEXT[] NOT NULL DEFAULT '{}',
  entities        TEXT[] NOT NULL DEFAULT '{}',
  products        TEXT[] NOT NULL DEFAULT '{}',
  campaigns       TEXT[] NOT NULL DEFAULT '{}',
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

  embedding       vector(1536),
  embedding_model TEXT,
  embedded_at     TIMESTAMPTZ,

  confidence      NUMERIC NOT NULL DEFAULT 0.5,
  importance      NUMERIC NOT NULL DEFAULT 0.5,

  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  validated_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_rag_entries_persona_key
  ON public.knowledge_rag_entries(persona_id, canonical_key);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_persona
  ON public.knowledge_rag_entries(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_type
  ON public.knowledge_rag_entries(content_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_status
  ON public.knowledge_rag_entries(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_slug
  ON public.knowledge_rag_entries(slug);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_tags
  ON public.knowledge_rag_entries USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_products
  ON public.knowledge_rag_entries USING GIN(products);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_campaigns
  ON public.knowledge_rag_entries USING GIN(campaigns);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_chunks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rag_entry_id    UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,

  chunk_index     INT NOT NULL,
  chunk_text      TEXT NOT NULL,
  chunk_summary   TEXT,

  embedding       vector(1536),
  embedding_model TEXT,
  embedded_at     TIMESTAMPTZ,

  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(rag_entry_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_chunks_entry
  ON public.knowledge_rag_chunks(rag_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_chunks_persona
  ON public.knowledge_rag_chunks(persona_id);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  source_entry_id UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  target_entry_id UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  relation_type   TEXT NOT NULL,
  weight          NUMERIC NOT NULL DEFAULT 1,
  confidence      NUMERIC NOT NULL DEFAULT 0.5,
  created_by      TEXT NOT NULL DEFAULT 'system',
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(source_entry_id, target_entry_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_persona
  ON public.knowledge_rag_links(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_source
  ON public.knowledge_rag_links(source_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_target
  ON public.knowledge_rag_links(target_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_relation
  ON public.knowledge_rag_links(relation_type);

COMMENT ON TABLE public.knowledge_intake_messages IS
  'Raw inbox for any knowledge submitted to the KB before classification.';
COMMENT ON TABLE public.knowledge_rag_entries IS
  'Canonical RAG-ready knowledge units scoped by persona and content type.';
COMMENT ON TABLE public.knowledge_rag_chunks IS
  'Embedding chunks for RAG entries. Short FAQs usually have one chunk.';
COMMENT ON TABLE public.knowledge_rag_links IS
  'Semantic hierarchy/relationship links between RAG entries.';




-- ---------------------------------------------------------------------
-- File: 014_allow_audience_rag_entries.sql
-- ---------------------------------------------------------------------

-- 014_allow_audience_rag_entries.sql
-- Allow audience as a first-class RAG entry type.

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_content_type_check;

ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_content_type_check
  CHECK (content_type IN (
    'faq',
    'product',
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




-- ---------------------------------------------------------------------
-- File: 015_ensure_knowledge_node_primary_edge.sql
-- ---------------------------------------------------------------------

-- 015_ensure_knowledge_node_primary_edge.sql
-- Ensure every persona-scoped knowledge node has a structural primary edge.

CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type = 'persona' THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
      AND e.relation_type IN (
        'belongs_to_persona',
        'contains',
        'part_of_campaign',
        'about_product',
        'briefed_by',
        'answers_question',
        'supports_copy',
        'uses_asset',
        'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id,
    node_type,
    slug,
    title,
    metadata,
    status
  )
  VALUES (
    NEW.persona_id,
    'persona',
    'self',
    'Persona',
    '{"role":"root"}'::jsonb,
    'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id,
    source_node_id,
    target_node_id,
    relation_type,
    weight,
    metadata
  )
  VALUES (
    NEW.persona_id,
    persona_node_id,
    NEW.id,
    'belongs_to_persona',
    1,
    '{"primary_tree":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type)
  DO NOTHING;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ensure_knowledge_node_primary_edge ON public.knowledge_nodes;

CREATE TRIGGER trg_ensure_knowledge_node_primary_edge
AFTER INSERT OR UPDATE OF persona_id, node_type
ON public.knowledge_nodes
FOR EACH ROW
EXECUTE FUNCTION public.ensure_knowledge_node_primary_edge();




-- ---------------------------------------------------------------------
-- File: 016_system_events_import_metadata.sql
-- ---------------------------------------------------------------------

-- 016_system_events_import_metadata.sql
-- Keep lead import audit data in existing system_events table.

ALTER TABLE public.system_events
  ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'info',
  ADD COLUMN IF NOT EXISTS source TEXT;

CREATE INDEX IF NOT EXISTS idx_system_events_entity
  ON public.system_events(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_system_events_source
  ON public.system_events(source);




-- ---------------------------------------------------------------------
-- File: 017_gallery_node_assets.sql
-- ---------------------------------------------------------------------

-- 017_gallery_node_assets.sql
-- Gallery uses existing graph tables and mirrors connected nodes into assets.

ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS knowledge_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS gallery_edge_id UUID REFERENCES public.knowledge_edges(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_assets_knowledge_node_id
  ON public.assets(knowledge_node_id)
  WHERE knowledge_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assets_gallery_edge
  ON public.assets(gallery_edge_id);

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, active)
VALUES
  ('gallery', 'Gallery', 'Bloco protegido para referencias visuais e materiais de criacao.', 112, 0.82, '#f0abfc', 'images', 112, true),
  ('embedded', 'Embedded', 'Bloco protegido para conteudos enviados ao RAG.', 120, 0.78, '#ffffff', 'database', 120, true)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('gallery_asset', 'na gallery', 'contem', '{"gallery"}', '{"brand","briefing","product","campaign","copy","asset","faq","rule","tone","audience","entity","kb_entry","knowledge_item"}', 0.90, true, 82, true)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;




-- ---------------------------------------------------------------------
-- File: 018_auth_users_permissions.sql
-- ---------------------------------------------------------------------

-- Brain AI auth and persona-level permissions.
-- Supabase CLI was not available in this workspace, so this migration was
-- created manually and should be applied with the existing deployment process.

create extension if not exists pgcrypto;

create table if not exists public.app_users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  username text unique,
  password_hash text not null,
  name text,
  role text not null default 'user' check (role in ('admin', 'user', 'viewer', 'operator')),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_login_at timestamptz
);

create index if not exists idx_app_users_role on public.app_users(role);
create index if not exists idx_app_users_active on public.app_users(is_active);

create table if not exists public.user_persona_access (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.app_users(id) on delete cascade,
  client_id text not null,
  persona_id uuid not null references public.personas(id) on delete cascade,
  persona_slug text,
  can_view boolean not null default true,
  can_edit boolean not null default false,
  can_manage boolean not null default false,
  created_at timestamptz not null default now(),
  unique (user_id, persona_id)
);

create index if not exists idx_user_persona_access_user on public.user_persona_access(user_id);
create index if not exists idx_user_persona_access_persona on public.user_persona_access(persona_id);
create index if not exists idx_user_persona_access_client on public.user_persona_access(client_id);

alter table public.app_users enable row level security;
alter table public.user_persona_access enable row level security;

drop policy if exists "app_users_service_only" on public.app_users;
create policy "app_users_service_only"
  on public.app_users
  for all
  using (false)
  with check (false);

drop policy if exists "user_persona_access_service_only" on public.user_persona_access;
create policy "user_persona_access_service_only"
  on public.user_persona_access
  for all
  using (false)
  with check (false);




-- ---------------------------------------------------------------------
-- File: 019_leads_canal_column.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform - Migration 019
-- Adiciona coluna canal em leads (whatsapp, instagram, bulk_import, ...)
-- Necessario para o pipeline ensure_lead_for_persona escrever a origem
-- do canal atual sem perder o INSERT por coluna desconhecida.
-- ============================================================

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS canal text;

CREATE INDEX IF NOT EXISTS leads_canal_idx ON leads(canal);

-- Forca a invalidacao do schema cache do PostgREST para que o supabase-py
-- enxergue a nova coluna sem precisar reiniciar a instancia.
NOTIFY pgrst, 'reload schema';




-- ---------------------------------------------------------------------
-- File: 020_audiences_lead_memberships.sql
-- ---------------------------------------------------------------------

-- 020_audiences_lead_memberships.sql
-- Persona-scoped audiences and canonical lead memberships.

CREATE TABLE IF NOT EXISTS public.audiences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  slug text NOT NULL,
  name text NOT NULL,
  description text,
  source_type text NOT NULL DEFAULT 'manual' CHECK (source_type IN ('manual', 'import', 'crm', 'shared')),
  is_system boolean NOT NULL DEFAULT false,
  created_by_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (persona_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_audiences_persona_id ON public.audiences(persona_id);
CREATE INDEX IF NOT EXISTS idx_audiences_source_type ON public.audiences(source_type);

CREATE TABLE IF NOT EXISTS public.lead_audience_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  audience_id uuid NOT NULL REFERENCES public.audiences(id) ON DELETE CASCADE,
  membership_type text NOT NULL DEFAULT 'primary' CHECK (membership_type IN ('primary', 'shared')),
  created_by_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lead_id, audience_id)
);

CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_lead_id ON public.lead_audience_memberships(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_audience_id ON public.lead_audience_memberships(audience_id);
CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_membership_type ON public.lead_audience_memberships(membership_type);




-- ---------------------------------------------------------------------
-- File: 021_backfill_lead_audiences.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform - Migration 021
-- Backfill: garante uma system audience "import" por persona com
-- leads existentes, e adiciona membership "primary" para cada lead
-- com persona_id atribuido. Idempotente.
-- ============================================================

-- 1. Cria a system audience "import" para cada persona que tem leads.
INSERT INTO public.audiences (persona_id, slug, name, description, source_type, is_system)
SELECT DISTINCT
  l.persona_id,
  'import' AS slug,
  'Import' AS name,
  'Audiencia padrao para leads importados via CSV ou consolidados antes de segmentacao manual.' AS description,
  'import' AS source_type,
  true AS is_system
FROM public.leads l
WHERE l.persona_id IS NOT NULL
ON CONFLICT (persona_id, slug) DO NOTHING;

-- 2. Para cada lead com persona_id, garante membership primary
--    na audience "import" da sua persona.
INSERT INTO public.lead_audience_memberships (lead_id, audience_id, membership_type)
SELECT
  l.id AS lead_id,
  a.id AS audience_id,
  'primary' AS membership_type
FROM public.leads l
JOIN public.audiences a
  ON a.persona_id = l.persona_id
 AND a.slug = 'import'
WHERE l.persona_id IS NOT NULL
ON CONFLICT (lead_id, audience_id) DO NOTHING;

-- 3. Forca o PostgREST a recarregar o schema cache para que o
--    supabase-py enxergue as tabelas novas sem reiniciar a instancia.
NOTIFY pgrst, 'reload schema';




-- ---------------------------------------------------------------------
-- File: 022_backfill_audiences_all_personas.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform - Migration 022
-- Garante que TODAS as personas (inclusive sem leads) tenham
-- a system audience com slug='import'. Idempotente.
-- ============================================================

-- 1. Cria audience system "import" para toda persona, ainda que sem leads.
INSERT INTO public.audiences (persona_id, slug, name, description, source_type, is_system)
SELECT
  p.id AS persona_id,
  'import' AS slug,
  'Import' AS name,
  'Audiencia padrao para leads importados via CSV ou consolidados antes de segmentacao manual.' AS description,
  'import' AS source_type,
  true AS is_system
FROM public.personas p
ON CONFLICT (persona_id, slug) DO NOTHING;

-- 2. Reaplica o backfill de membership: leads novos sem membership recebem
--    primary na audience import da sua persona. Idempotente.
INSERT INTO public.lead_audience_memberships (lead_id, audience_id, membership_type)
SELECT
  l.id AS lead_id,
  a.id AS audience_id,
  'primary' AS membership_type
FROM public.leads l
JOIN public.audiences a
  ON a.persona_id = l.persona_id
 AND a.slug = 'import'
WHERE l.persona_id IS NOT NULL
ON CONFLICT (lead_id, audience_id) DO NOTHING;

-- 3. Recarrega o schema cache do PostgREST.
NOTIFY pgrst, 'reload schema';




-- ---------------------------------------------------------------------
-- File: 023_kb_entries_source_check.sql
-- ---------------------------------------------------------------------

-- ============================================================
-- Brain AI Platform — Migration 023
-- Expand kb_entries.source CHECK to allow graph_embed.
--
-- Why: services/supabase_client.py::sync_embedded_kb_node mirrors
-- knowledge nodes promoted via the graph (FAQ/Copy/Tom/Regra/Entidade →
-- Embedded edge) into kb_entries with source='graph_embed'. The original
-- constraint only allowed ('sheets','manual'), causing a 23514 violation
-- and a 502 from POST /knowledge/graph-edges every time the operator
-- linked any approved knowledge to the Embedded node.
--
-- Business rule (CLAUDE.md §10, Embedded ↔ KB): every knowledge node
-- connected to Embedded must mirror to kb_entries so the persona's KB
-- list reflects what the agents actually retrieve.
-- ============================================================

ALTER TABLE kb_entries DROP CONSTRAINT IF EXISTS kb_entries_source_check;

ALTER TABLE kb_entries
  ADD CONSTRAINT kb_entries_source_check
  CHECK (source IN ('sheets', 'manual', 'graph_embed'));




-- ---------------------------------------------------------------------
-- File: 024_observability_alignment.sql
-- ---------------------------------------------------------------------

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




-- ---------------------------------------------------------------------
-- File: 025_user_integrations_and_stability.sql
-- ---------------------------------------------------------------------

-- Brain AI Platform - Migration 025
-- User-managed integrations, schema hardening for knowledge mirrors and FAQ embed stability.

create table if not exists public.user_integration_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.app_users(id) on delete cascade,
  service text not null,
  enabled boolean not null default false,
  status text not null default 'never_validated',
  config_json jsonb not null default '{}'::jsonb,
  secret_ciphertext text,
  last_validated_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, service)
);

create index if not exists idx_user_integration_connections_user on public.user_integration_connections(user_id);
create index if not exists idx_user_integration_connections_service on public.user_integration_connections(service);

alter table public.user_integration_connections enable row level security;

drop policy if exists "user_integration_connections_service_only" on public.user_integration_connections;
create policy "user_integration_connections_service_only"
  on public.user_integration_connections
  for all
  using (false)
  with check (false);

alter table public.kb_entries
  add column if not exists embedding_status text;

create index if not exists idx_system_health_snapshot_at on public.system_health(snapshot_at desc);

create index if not exists idx_knowledge_nodes_source_persona_lookup
  on public.knowledge_nodes (source_table, source_id, persona_id, created_at desc);

create unique index if not exists idx_workflow_bindings_unique_name_persona
  on public.workflow_bindings (workflow_name, persona_id);




-- ---------------------------------------------------------------------
-- File: 026_approved_knowledge_snapshots_n8n_bridge.sql
-- ---------------------------------------------------------------------

-- 026_approved_knowledge_snapshots_n8n_bridge.sql
-- Canonical approved snapshot bridge:
-- knowledge_nodes/edges -> approved_knowledge_snapshots -> knowledge_rag_entries/chunks.
-- The N8N flow remains the RAG consumer; this migration only gives the
-- backend a durable validation and lineage target.

CREATE TABLE IF NOT EXISTS public.approved_knowledge_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  root_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  source_node_id uuid NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,

  source_table text NOT NULL DEFAULT 'knowledge_nodes',
  source_id uuid,
  artifact_id uuid REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,

  content_type text NOT NULL,
  title text NOT NULL,
  slug text NOT NULL,
  canonical_key text NOT NULL,
  content_hash text NOT NULL,

  hierarchy_path jsonb NOT NULL DEFAULT '[]'::jsonb,
  hierarchy_summary text,
  approved_summary text NOT NULL,
  approved_markdown text NOT NULL,

  parent_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  brand_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  briefing_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  campaign_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  audience_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  product_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  faq_context jsonb NOT NULL DEFAULT '{}'::jsonb,

  rag_entry_id uuid REFERENCES public.knowledge_rag_entries(id) ON DELETE SET NULL,

  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','pending_validation','approved','active','rejected','stale')),

  approved_by uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  approved_at timestamptz,

  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (persona_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_approved_snapshots_persona
  ON public.approved_knowledge_snapshots(persona_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_source_node
  ON public.approved_knowledge_snapshots(source_node_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_status
  ON public.approved_knowledge_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_type
  ON public.approved_knowledge_snapshots(content_type);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_rag_entry
  ON public.approved_knowledge_snapshots(rag_entry_id);
CREATE INDEX IF NOT EXISTS idx_approved_snapshots_hierarchy_path
  ON public.approved_knowledge_snapshots USING gin(hierarchy_path);

ALTER TABLE public.approved_knowledge_snapshots ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.approved_knowledge_snapshots IS
  'Canonical approved tree snapshots that bridge the semantic graph to RAG entries/chunks for N8N retrieval validation.';

-- Protected terminal nodes are visual/publication destinations, not children
-- of the primary semantic tree. Keep the trigger for real knowledge nodes only.
CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type IN ('persona', 'embedded', 'gallery') THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
      AND e.relation_type IN (
        'belongs_to_persona',
        'contains',
        'part_of_campaign',
        'about_product',
        'briefed_by',
        'answers_question',
        'supports_copy',
        'uses_asset',
        'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id,
    node_type,
    slug,
    title,
    metadata,
    status
  )
  VALUES (
    NEW.persona_id,
    'persona',
    'self',
    'Persona',
    '{"role":"root","protected":true}'::jsonb,
    'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id,
    source_node_id,
    target_node_id,
    relation_type,
    weight,
    metadata
  )
  VALUES (
    NEW.persona_id,
    persona_node_id,
    NEW.id,
    'belongs_to_persona',
    1,
    '{"primary_tree":true,"active":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type)
  DO NOTHING;

  RETURN NEW;
END;
$$;

-- Soft-disable legacy terminal primary edges that were created by the old guard.
UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'disabled_from', '026_approved_knowledge_snapshots_n8n_bridge',
    'disabled_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND src.node_type = 'persona'
  AND tgt.node_type IN ('embedded', 'gallery')
  AND e.relation_type = 'belongs_to_persona';




-- ---------------------------------------------------------------------
-- File: 027_repair_golden_dataset_hierarchy.sql
-- ---------------------------------------------------------------------

-- 027_repair_golden_dataset_hierarchy.sql
-- Repairs Golden Dataset graph hierarchy after legacy persona fallback /
-- mention pollution issues. Keeps N8N as RAG consumer; this only fixes graph
-- lineage used to create snapshots and chunks.

CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL OR NEW.node_type IN ('persona', 'embedded', 'gallery', 'tag', 'mention') THEN
    RETURN NEW;
  END IF;

  IF (NEW.metadata ? 'resolved_parent_node_id') THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE e.target_node_id = NEW.id
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
      AND COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
      AND e.relation_type IN (
        'belongs_to_persona',
        'contains',
        'part_of_campaign',
        'about_product',
        'briefed_by',
        'answers_question',
        'supports_copy',
        'uses_asset',
        'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id,
    node_type,
    slug,
    title,
    metadata,
    status
  )
  VALUES (
    NEW.persona_id,
    'persona',
    'self',
    'Persona',
    '{"role":"root","protected":true}'::jsonb,
    'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id,
    source_node_id,
    target_node_id,
    relation_type,
    weight,
    metadata
  )
  VALUES (
    NEW.persona_id,
    persona_node_id,
    NEW.id,
    'belongs_to_persona',
    1,
    '{"primary_tree":true,"active":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type)
  DO NOTHING;

  RETURN NEW;
END;
$$;

-- Mention is auxiliary, never a primary tree node.
UPDATE public.knowledge_nodes
SET metadata = COALESCE(metadata, '{}'::jsonb)
  || jsonb_build_object('visual_hidden', true, 'canonical_auxiliary', true)
WHERE node_type = 'mention';

UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_repair_golden_dataset_hierarchy',
    'deleted_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND (src.node_type = 'mention' OR tgt.node_type = 'mention');

-- Direction is parent -> child. node -> persona belongs edges pollute paths.
UPDATE public.knowledge_edges e
SET metadata = COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_node_to_persona_cleanup',
    'deleted_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND tgt.node_type = 'persona'
  AND src.node_type <> 'persona';

-- Restore top-down plan edges incorrectly soft-deleted as graph_ui_reparent.
UPDATE public.knowledge_edges e
SET metadata = (COALESCE(e.metadata, '{}'::jsonb) - 'deleted_at' - 'deleted_from')
  || jsonb_build_object(
    'active', true,
    'primary_tree', true,
    'restored_from', '027_repair_golden_dataset_hierarchy',
    'restored_at', now()
  )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND COALESCE(e.metadata->>'deleted_from', '') = 'graph_ui_reparent'
  AND (
    (src.node_type = 'brand' AND tgt.node_type = 'briefing')
    OR (src.node_type = 'briefing' AND tgt.node_type IN ('campaign','audience','product','copy','faq'))
    OR (src.node_type = 'campaign' AND tgt.node_type IN ('audience','product','copy','faq'))
    OR (src.node_type = 'audience' AND tgt.node_type IN ('product','copy','faq'))
    OR (src.node_type = 'product' AND tgt.node_type IN ('copy','faq','asset'))
  );

-- Materialize resolved_parent_node_id as active primary edge.
INSERT INTO public.knowledge_edges (
  persona_id,
  source_node_id,
  target_node_id,
  relation_type,
  weight,
  metadata
)
SELECT
  child.persona_id,
  parent.id,
  child.id,
  CASE
    WHEN parent.node_type = 'product' AND child.node_type = 'faq' THEN 'answers_question'
    WHEN parent.node_type = 'product' AND child.node_type = 'copy' THEN 'supports_copy'
    WHEN parent.node_type = 'product' AND child.node_type = 'asset' THEN 'uses_asset'
    WHEN parent.node_type = 'audience' AND child.node_type = 'product' THEN 'about_product'
    ELSE 'contains'
  END,
  1,
  jsonb_build_object(
    'active', true,
    'primary_tree', true,
    'created_from', '027_resolved_parent_repair',
    'parent_slug', parent.slug,
    'parent_type', parent.node_type
  )
FROM public.knowledge_nodes child
JOIN public.knowledge_nodes parent
  ON parent.id::text = child.metadata->>'resolved_parent_node_id'
WHERE child.node_type NOT IN ('persona','embedded','gallery','tag','mention')
  AND parent.node_type NOT IN ('embedded','gallery','tag','mention')
  AND child.persona_id = parent.persona_id
  AND child.id <> parent.id
ON CONFLICT (source_node_id, target_node_id, relation_type)
DO UPDATE SET
  metadata = (COALESCE(public.knowledge_edges.metadata, '{}'::jsonb) - 'deleted_at' - 'deleted_from')
    || EXCLUDED.metadata,
  weight = EXCLUDED.weight,
  persona_id = EXCLUDED.persona_id;

-- Once a node has a real non-persona primary parent, direct persona fallback
-- edges must be visual-hidden and non-primary.
UPDATE public.knowledge_edges fallback
SET metadata = COALESCE(fallback.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'active', false,
    'primary_tree', false,
    'visual_hidden', true,
    'deleted_from', '027_direct_persona_fallback_cleanup',
    'deleted_at', now()
  )
FROM public.knowledge_nodes persona_node, public.knowledge_nodes child
WHERE fallback.source_node_id = persona_node.id
  AND fallback.target_node_id = child.id
  AND persona_node.node_type = 'persona'
  AND child.node_type NOT IN ('brand','briefing')
  AND COALESCE((fallback.metadata->>'primary_tree')::boolean, false) = true
  AND EXISTS (
    SELECT 1
    FROM public.knowledge_edges real_parent
    JOIN public.knowledge_nodes parent_node ON parent_node.id = real_parent.source_node_id
    WHERE real_parent.target_node_id = child.id
      AND parent_node.node_type <> 'persona'
      AND COALESCE((real_parent.metadata->>'active')::boolean, true) = true
      AND COALESCE((real_parent.metadata->>'primary_tree')::boolean, false) = true
  );

-- Align stale metadata.classification.content_type with the real column.
UPDATE public.knowledge_items
SET metadata = COALESCE(metadata, '{}'::jsonb)
  || jsonb_build_object(
    'classification',
    COALESCE(metadata->'classification', '{}'::jsonb)
      || jsonb_build_object('content_type', content_type)
  )
WHERE metadata ? 'classification'
  AND COALESCE(metadata->'classification'->>'content_type', '') <> content_type;




-- ---------------------------------------------------------------------
-- File: 028_flexible_marketing_graph_contract.sql
-- ---------------------------------------------------------------------

-- 028_flexible_marketing_graph_contract.sql
-- Flexible marketing graph contract: entity cards, primary-tree read model,
-- and indexes used by CRIAR/E2E validation.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','other'
  ));

CREATE OR REPLACE VIEW public.knowledge_graph_primary_tree
WITH (security_invoker = true) AS
SELECT *
FROM public.knowledge_edges
WHERE COALESCE((metadata->>'active')::boolean, true) = true
  AND COALESCE((metadata->>'primary_tree')::boolean, false) = true
  AND COALESCE((metadata->>'visual_hidden')::boolean, false) = false;

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_persona_type_slug
  ON public.knowledge_nodes (persona_id, node_type, slug);

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_persona_source_target
  ON public.knowledge_edges (persona_id, source_node_id, target_node_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_persona_content_type
  ON public.knowledge_items (persona_id, content_type);

COMMENT ON VIEW public.knowledge_graph_primary_tree IS
  'Active visible primary-tree edges for CRIAR / graph-data tree rendering.';




-- ---------------------------------------------------------------------
-- File: 029_single_branch_primary_edge_policy.sql
-- ---------------------------------------------------------------------

-- 029_single_branch_primary_edge_policy.sql
-- Enforce the read-model contract: only one active visible primary_tree edge
-- per source -> target pair. Alternate semantic labels remain hidden lineage.

UPDATE public.knowledge_edges e
SET relation_type = 'offers_product',
    metadata = jsonb_set(
      jsonb_set(COALESCE(e.metadata, '{}'::jsonb), '{canonicalized_relation_from}', to_jsonb(e.relation_type), true),
      '{canonical_relation}', '"audience_product_offers_product"'::jsonb,
      true
    )
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE e.source_node_id = src.id
  AND e.target_node_id = tgt.id
  AND src.node_type = 'audience'
  AND tgt.node_type = 'product'
  AND e.relation_type = 'about_product'
  AND NOT EXISTS (
    SELECT 1
    FROM public.knowledge_edges other
    WHERE other.source_node_id = e.source_node_id
      AND other.target_node_id = e.target_node_id
      AND other.relation_type = 'offers_product'
  );

WITH ranked AS (
  SELECT
    e.id,
    row_number() OVER (
      PARTITION BY e.source_node_id, e.target_node_id
      ORDER BY
        CASE e.relation_type
          WHEN 'offers_product' THEN 0
          WHEN 'supports_copy' THEN 1
          WHEN 'answers_question' THEN 2
          WHEN 'contains' THEN 3
          ELSE 9
        END,
        e.id
    ) AS rn
  FROM public.knowledge_edges e
  WHERE COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
    AND COALESCE((e.metadata->>'active')::boolean, true) = true
    AND COALESCE((e.metadata->>'visual_hidden')::boolean, false) = false
)
UPDATE public.knowledge_edges e
SET metadata =
  jsonb_set(
    jsonb_set(
      jsonb_set(COALESCE(e.metadata, '{}'::jsonb), '{primary_tree}', 'false'::jsonb, true),
      '{visual_hidden}', 'true'::jsonb,
      true
    ),
    '{demoted_from_primary_tree}',
    '"duplicate_source_target_migration_029"'::jsonb,
    true
  )
FROM ranked r
WHERE e.id = r.id
  AND r.rn > 1;




-- ---------------------------------------------------------------------
-- File: 030_safe_edge_semantics_and_faq_snapshot_review.sql
-- ---------------------------------------------------------------------

-- 030_safe_edge_semantics_and_faq_snapshot_review.sql
-- Safe semantics/rastreability enrichment for CRIAR single_branch.
-- This migration intentionally does not change relation_type or topology.

ALTER TABLE public.approved_knowledge_snapshots
  DROP CONSTRAINT IF EXISTS approved_knowledge_snapshots_status_check;

ALTER TABLE public.approved_knowledge_snapshots
  ADD CONSTRAINT approved_knowledge_snapshots_status_check
  CHECK (status IN ('draft','pending_validation','approved','active','needs_review','rejected','stale'));

WITH session_items AS (
  SELECT
    ki.id,
    ki.persona_id,
    ki.metadata,
    ki.metadata->>'session_id' AS session_id,
    COALESCE(ki.metadata->>'source_ref', ki.metadata->>'session_id') AS source_ref,
    COALESCE(ki.metadata->>'created_via', 'kb_intake_sofia') AS created_via,
    COALESCE(ki.metadata->>'tree_mode', 'single_branch') AS tree_mode,
    COALESCE(ki.metadata->>'branch_policy', 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_items ki
  WHERE ki.metadata->>'session_id' = '2a0015cd-d7f4-41f0-9573-df30229cb739'
)
UPDATE public.knowledge_nodes n
SET metadata =
  COALESCE(n.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'session_id', si.session_id,
    'source_ref', si.source_ref,
    'created_via', si.created_via,
    'tree_mode', si.tree_mode,
    'branch_policy', si.branch_policy
  )
FROM session_items si
WHERE n.source_table = 'knowledge_items'
  AND n.source_id = si.id
  AND n.persona_id = si.persona_id;

WITH session_nodes AS (
  SELECT
    n.id,
    n.node_type,
    n.slug,
    n.metadata->>'session_id' AS session_id,
    COALESCE(n.metadata->>'source_ref', n.metadata->>'session_id') AS source_ref,
    COALESCE(n.metadata->>'created_via', 'kb_intake_sofia') AS created_via,
    COALESCE(n.metadata->>'tree_mode', 'single_branch') AS tree_mode,
    COALESCE(n.metadata->>'branch_policy', 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_nodes n
  WHERE n.metadata->>'session_id' = '2a0015cd-d7f4-41f0-9573-df30229cb739'
),
session_edges AS (
  SELECT
    e.id,
    src.node_type AS source_type,
    tgt.node_type AS target_type,
    COALESCE(tgt.session_id, src.session_id) AS session_id,
    COALESCE(tgt.source_ref, src.source_ref) AS source_ref,
    COALESCE(tgt.created_via, src.created_via) AS created_via,
    COALESCE(tgt.tree_mode, src.tree_mode, 'single_branch') AS tree_mode,
    COALESCE(tgt.branch_policy, src.branch_policy, 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_edges e
  JOIN session_nodes src ON src.id = e.source_node_id
  JOIN session_nodes tgt ON tgt.id = e.target_node_id
  WHERE COALESCE((e.metadata->>'active')::boolean, true) = true
)
UPDATE public.knowledge_edges e
SET metadata =
  COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'session_id', se.session_id,
    'source_ref', se.source_ref,
    'created_via', se.created_via,
    'tree_mode', se.tree_mode,
    'branch_policy', se.branch_policy,
    'semantic_relation',
      CASE
        WHEN se.source_type = 'persona' AND se.target_type = 'briefing' THEN 'contains_briefing'
        WHEN se.source_type = 'briefing' AND se.target_type = 'audience' THEN 'defines_audience'
        WHEN se.source_type = 'audience' AND se.target_type = 'product' THEN 'offers_product'
        WHEN se.source_type = 'product' AND se.target_type = 'copy' THEN 'supports_copy'
        WHEN se.source_type = 'copy' AND se.target_type = 'faq' THEN 'answers_question'
        WHEN se.source_type = 'faq' AND se.target_type = 'embedded' THEN 'published_to_rag'
        ELSE e.relation_type
      END,
    'semantic_label',
      CASE
        WHEN se.source_type = 'persona' AND se.target_type = 'briefing' THEN 'Persona contem briefing'
        WHEN se.source_type = 'briefing' AND se.target_type = 'audience' THEN 'Briefing define publico'
        WHEN se.source_type = 'audience' AND se.target_type = 'product' THEN 'Publico recebe oferta de produto'
        WHEN se.source_type = 'product' AND se.target_type = 'copy' THEN 'Produto sustenta copy'
        WHEN se.source_type = 'copy' AND se.target_type = 'faq' THEN 'Copy responde pergunta'
        WHEN se.source_type = 'faq' AND se.target_type = 'embedded' THEN 'FAQ publicado no RAG'
        ELSE e.relation_type
      END
  )
  || CASE
    WHEN COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
      THEN jsonb_build_object('tree_role', 'primary_branch')
    ELSE '{}'::jsonb
  END
FROM session_edges se
WHERE e.id = se.id;




-- ---------------------------------------------------------------------
-- File: 031_allow_offer_content_type.sql
-- ---------------------------------------------------------------------

-- 031_allow_offer_content_type.sql
-- CRIAR plan mode needs explicit commercial offer nodes between product and copy.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','offer','other'
  ));

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('offer', 'Oferta', 'Preco, quantidade, pacote, kit ou variacao comercial entre produto e copy.', 35, 0.78, '#38bdf8', 'badge-dollar-sign', 45)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

-- Backfill legacy offer mirrors that were materialized as generic
-- knowledge_item nodes before offer became an official graph node type.
UPDATE public.knowledge_nodes n
SET
  node_type = 'offer',
  level = 35,
  importance = 0.78,
  metadata = jsonb_set(
    jsonb_set(
      COALESCE(n.metadata, '{}'::jsonb),
      '{repaired_from_node_type}',
      to_jsonb(n.node_type),
      true
    ),
    '{content_type}',
    '"offer"'::jsonb,
    true
  ),
  updated_at = now()
FROM public.knowledge_items i
WHERE n.source_table = 'knowledge_items'
  AND n.source_id::text = i.id::text
  AND i.content_type = 'offer'
  AND n.node_type <> 'offer';

-- Tags and generic technical mirrors are auxiliary metadata. Existing
-- guard-created persona -> tag edges and stale knowledge_item tree edges
-- must not participate in the primary tree or main visualization.
UPDATE public.knowledge_edges e
SET
  metadata = jsonb_set(
    jsonb_set(
      jsonb_set(
        COALESCE(e.metadata, '{}'::jsonb),
        '{primary_tree}',
        'false'::jsonb,
        true
      ),
      '{graph_layer}',
      '"auxiliary"'::jsonb,
      true
    ),
    '{visual_hidden}',
    'true'::jsonb,
    true
  ),
  updated_at = now()
FROM public.knowledge_nodes src, public.knowledge_nodes tgt
WHERE src.id = e.source_node_id
  AND tgt.id = e.target_node_id
  AND (
    src.node_type IN ('tag', 'mention', 'knowledge_item', 'kb_entry')
    OR tgt.node_type IN ('tag', 'mention', 'knowledge_item', 'kb_entry')
  )
  AND COALESCE((e.metadata->>'primary_tree')::boolean, false) = true;




-- ---------------------------------------------------------------------
-- File: 032_canonical_faq_rag_entries.sql
-- ---------------------------------------------------------------------

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





-- ---------------------------------------------------------------------
-- File: 033_asset_upload_pipeline.sql
-- ---------------------------------------------------------------------

-- 033_asset_upload_pipeline.sql
-- File upload pipeline for Sofia/CRIAR (immediate context) and ASSET card (validatable).
-- Adds storage buckets, extends public.assets, creates public.asset_readings.

-- ── Storage buckets ──────────────────────────────────────────────────────
INSERT INTO storage.buckets (id, name, public)
VALUES
  ('assets-raw',     'assets-raw',     false),
  ('assets-derived', 'assets-derived', false)
ON CONFLICT (id) DO NOTHING;

-- ── public.assets — expand columns ───────────────────────────────────────
ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS storage_bucket     text,
  ADD COLUMN IF NOT EXISTS storage_path       text,
  ADD COLUMN IF NOT EXISTS mime_type          text,
  ADD COLUMN IF NOT EXISTS file_size          bigint,
  ADD COLUMN IF NOT EXISTS original_filename  text,
  ADD COLUMN IF NOT EXISTS status             text DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS upload_context     text,
  ADD COLUMN IF NOT EXISTS updated_at         timestamptz DEFAULT now();

-- Status enum for assets — pending | reading | ready | failed | archived
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_status_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_status_check
  CHECK (status IS NULL OR status IN ('pending','reading','ready','failed','archived'));

-- upload_context enum — sofia_chat | create_sidebar | asset_card | imported
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_upload_context_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_upload_context_check
  CHECK (upload_context IS NULL OR upload_context IN ('sofia_chat','create_sidebar','asset_card','imported'));

-- Extend type CHECK to include real file kinds (was image|copy|campaign|template).
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_type_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_type_check
  CHECK (type IS NULL OR type IN ('image','video','pdf','text','copy','campaign','template'));

-- Extend source CHECK to include direct uploads.
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_source_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_source_check
  CHECK (source IN ('maker','manual','mcp','imported','upload'));

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.assets_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_assets_updated_at ON public.assets;
CREATE TRIGGER trg_assets_updated_at
  BEFORE UPDATE ON public.assets
  FOR EACH ROW EXECUTE FUNCTION public.assets_set_updated_at();

-- Indexes for the new flows
CREATE INDEX IF NOT EXISTS idx_assets_persona_id      ON public.assets(persona_id);
CREATE INDEX IF NOT EXISTS idx_assets_status          ON public.assets(status);
CREATE INDEX IF NOT EXISTS idx_assets_source          ON public.assets(source);
CREATE INDEX IF NOT EXISTS idx_assets_upload_context  ON public.assets(upload_context);
CREATE INDEX IF NOT EXISTS idx_assets_created_at_desc ON public.assets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_session_id      ON public.assets((metadata->>'session_id'));
CREATE INDEX IF NOT EXISTS idx_assets_storage_path    ON public.assets(storage_bucket, storage_path);

-- ── public.asset_readings — pipeline output history ──────────────────────
CREATE TABLE IF NOT EXISTS public.asset_readings (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id        uuid NOT NULL REFERENCES public.assets(id) ON DELETE CASCADE,
  persona_id      uuid,
  reading_type    text NOT NULL CHECK (reading_type IN (
    'classification','ocr','ai_fallback','pdf_text','video_mock','rename'
  )),
  title           text,
  summary         text,
  extracted_text  text,
  visual_summary  text,
  markdown        text,
  classification  jsonb DEFAULT '{}'::jsonb,
  confidence      numeric DEFAULT 0.5,
  model_used      text,
  status          text DEFAULT 'completed' CHECK (status IN ('pending','completed','partial','mocked','failed')),
  metadata        jsonb DEFAULT '{}'::jsonb,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_readings_asset      ON public.asset_readings(asset_id, reading_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_asset_readings_persona    ON public.asset_readings(persona_id);
CREATE INDEX IF NOT EXISTS idx_asset_readings_status     ON public.asset_readings(status);

CREATE OR REPLACE FUNCTION public.asset_readings_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_asset_readings_updated_at ON public.asset_readings;
CREATE TRIGGER trg_asset_readings_updated_at
  BEFORE UPDATE ON public.asset_readings
  FOR EACH ROW EXECUTE FUNCTION public.asset_readings_set_updated_at();

-- ── RLS placeholder ──────────────────────────────────────────────────────
-- The existing assets table is accessed via service role only; mirror that for asset_readings.
ALTER TABLE public.asset_readings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS asset_readings_service_role ON public.asset_readings;
CREATE POLICY asset_readings_service_role ON public.asset_readings
  FOR ALL TO service_role USING (true) WITH CHECK (true);




-- ---------------------------------------------------------------------
-- File: 034_repair_faq_edge_direction.sql
-- ---------------------------------------------------------------------

-- 034_repair_faq_edge_direction.sql
-- FAQ is a terminal commercial node. Commercial/context vectors point into FAQ;
-- the only valid outgoing FAQ edge is publication to Embedded.

UPDATE public.knowledge_node_type_registry
SET default_importance = 0.45,
    updated_at = now()
WHERE node_type = 'faq';

UPDATE public.knowledge_relation_type_registry
SET source_node_types = ARRAY['product', 'offer', 'copy', 'campaign', 'audience', 'brand', 'entity'],
    target_node_types = ARRAY['faq', 'kb_entry'],
    updated_at = now()
WHERE relation_type = 'answers_question';

WITH invalid_edges AS (
  SELECT
    e.id,
    e.persona_id,
    e.source_node_id AS faq_node_id,
    e.target_node_id AS parent_node_id,
    e.weight,
    e.metadata
  FROM public.knowledge_edges e
  JOIN public.knowledge_nodes src ON src.id = e.source_node_id
  JOIN public.knowledge_nodes tgt ON tgt.id = e.target_node_id
  WHERE src.node_type = 'faq'
    AND tgt.node_type IN ('product', 'offer', 'copy', 'campaign', 'audience')
    AND COALESCE((e.metadata->>'active')::boolean, true) IS TRUE
)
INSERT INTO public.knowledge_edges (
  persona_id,
  source_node_id,
  target_node_id,
  relation_type,
  weight,
  metadata
)
SELECT
  invalid_edges.persona_id,
  invalid_edges.parent_node_id,
  invalid_edges.faq_node_id,
  'answers_question',
  COALESCE(invalid_edges.weight, 1),
  jsonb_strip_nulls(
    COALESCE(invalid_edges.metadata, '{}'::jsonb)
    || jsonb_build_object(
      'active', true,
      'repaired_from_edge_id', invalid_edges.id,
      'repaired_direction', 'faq_terminal_inbound',
      'created_from', 'migration_034_repair_faq_edge_direction'
    )
    - 'deleted_from'
    - 'deleted_at'
  )
FROM invalid_edges
ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE
SET metadata = jsonb_strip_nulls(
      COALESCE(public.knowledge_edges.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', true,
        'repaired_from_edge_id', EXCLUDED.metadata->>'repaired_from_edge_id',
        'repaired_direction', 'faq_terminal_inbound',
        'reactivated_from', 'migration_034_repair_faq_edge_direction'
      )
    ),
    updated_at = now();

WITH invalid_edges AS (
  SELECT e.id, e.metadata
  FROM public.knowledge_edges e
  JOIN public.knowledge_nodes src ON src.id = e.source_node_id
  JOIN public.knowledge_nodes tgt ON tgt.id = e.target_node_id
  WHERE src.node_type = 'faq'
    AND tgt.node_type IN ('product', 'offer', 'copy', 'campaign', 'audience')
    AND COALESCE((e.metadata->>'active')::boolean, true) IS TRUE
)
UPDATE public.knowledge_edges e
SET metadata = jsonb_strip_nulls(
      COALESCE(e.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', false,
        'primary_tree', false,
        'visual_hidden', true,
        'deleted_from', 'migration_034_repair_faq_edge_direction',
        'deleted_at', now(),
        'invalid_reason', 'faq_terminal_node_cannot_point_to_commercial_parent'
      )
    ),
    updated_at = now()
FROM invalid_edges
WHERE e.id = invalid_edges.id;




-- ---------------------------------------------------------------------
-- File: 035_faq_pending_regeneration_status.sql
-- ---------------------------------------------------------------------

-- Allow FAQ items to be marked stale when related commercial context changes.
ALTER TABLE knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_status_check;

ALTER TABLE knowledge_items
  ADD CONSTRAINT knowledge_items_status_check
  CHECK (status IN ('pending','approved','rejected','embedded','needs_update','pending_regeneration'));




-- ---------------------------------------------------------------------
-- File: 036_enforce_asset_graph_contract.sql
-- ---------------------------------------------------------------------

-- 036_enforce_asset_graph_contract.sql
-- Asset files shown in marketing/assets must have a Graph node, a branch edge,
-- and an asset -> Gallery edge. This migration keeps the schema aligned with
-- the runtime contract; row repair is handled idempotently by the API because
-- choosing the correct commercial branch requires application semantics.

ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS knowledge_node_id uuid REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS gallery_edge_id uuid REFERENCES public.knowledge_edges(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_assets_knowledge_node_id
  ON public.assets(knowledge_node_id)
  WHERE knowledge_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assets_gallery_edge
  ON public.assets(gallery_edge_id);

CREATE INDEX IF NOT EXISTS idx_assets_graph_metadata_node
  ON public.assets((metadata->>'knowledge_node_id'))
  WHERE metadata ? 'knowledge_node_id';

CREATE INDEX IF NOT EXISTS idx_assets_graph_metadata_gallery_edge
  ON public.assets((metadata->>'gallery_edge_id'))
  WHERE metadata ? 'gallery_edge_id';

UPDATE public.knowledge_relation_type_registry
SET
  label = 'na gallery',
  inverse_label = 'contem',
  source_node_types = '{"asset"}',
  target_node_types = '{"gallery"}',
  default_weight = 0.90,
  directional = true,
  sort_order = 82,
  active = true
WHERE relation_type = 'gallery_asset';

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
SELECT
  'gallery_asset',
  'na gallery',
  'contem',
  '{"asset"}',
  '{"gallery"}',
  0.90,
  true,
  82,
  true
WHERE NOT EXISTS (
  SELECT 1 FROM public.knowledge_relation_type_registry WHERE relation_type = 'gallery_asset'
);

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('uses_asset', 'usa asset', 'e usado por', '{"brand","briefing","campaign","audience","product","offer","copy","rule"}', '{"asset"}', 0.85, true, 80, true)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = EXCLUDED.active;




-- ---------------------------------------------------------------------
-- File: 037_product_collection_and_categories.sql
-- ---------------------------------------------------------------------

-- 037_product_collection_and_categories.sql
-- Universal product collections on top of knowledge_nodes/knowledge_edges.
-- Additive and idempotent. No products table.

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('product_collection', 'Product Collection', 'Cardapio, catalogo ou colecao de produtos. O tipo concreto fica em metadata.collection_type.', 25, 0.88, '#34d399', 'book-open', 25),
  ('category', 'Category', 'Agrupamento logico de produtos dentro de uma product_collection.', 38, 0.72, '#fbbf24', 'folder', 38),
  ('product', 'Produto', 'Produto comercial conectado a categorias, colecoes, copy, FAQ e assets.', 45, 0.85, '#60a5fa', 'package', 45),
  ('copy', 'Copy', 'Texto reutilizavel para mensagens, posts ou anuncios.', 70, 0.65, '#64748b', 'text', 70),
  ('faq', 'FAQ', 'Pergunta e resposta operacional.', 75, 0.65, '#4ade80', 'circle-help', 75),
  ('asset', 'Asset', 'Arquivo visual, video, logo, template ou material maker.', 80, 0.55, '#f59e0b', 'image', 80),
  ('briefing', 'Briefing', 'Contexto, estrategia, requisitos e instrucoes.', 50, 0.75, '#c084fc', 'file-text', 50)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('brand_has_collection', 'brand tem colecao', 'colecao de brand', '{"brand"}', '{"product_collection"}', 0.90, TRUE, 51, TRUE),
  ('collection_has_briefing', 'colecao tem briefing', 'briefing de colecao', '{"product_collection"}', '{"briefing"}', 0.85, TRUE, 52, TRUE),
  ('collection_has_category', 'colecao tem categoria', 'categoria da colecao', '{"product_collection"}', '{"category"}', 0.85, TRUE, 53, TRUE),
  ('part_of_collection', 'parte da colecao', 'contem', '{"product","category","copy","faq","briefing"}', '{"product_collection"}', 0.75, TRUE, 54, TRUE),
  ('category_has_product', 'categoria tem produto', 'produto da categoria', '{"category"}', '{"product"}', 0.86, TRUE, 55, TRUE),
  ('in_category', 'na categoria', 'agrupa', '{"product"}', '{"category"}', 0.70, TRUE, 56, TRUE),
  ('product_has_copy', 'produto tem copy', 'copy de produto', '{"product"}', '{"copy"}', 0.75, TRUE, 57, TRUE),
  ('product_has_faq', 'produto tem FAQ', 'FAQ de produto', '{"product"}', '{"faq"}', 0.75, TRUE, 58, TRUE),
  ('product_has_asset', 'produto tem asset', 'asset de produto', '{"product"}', '{"asset"}', 0.75, TRUE, 59, TRUE),
  ('product_image', 'imagem do produto', 'representa produto', '{"asset"}', '{"product"}', 0.85, TRUE, 60, TRUE),
  ('faq_has_embed', 'FAQ publicado em embed', 'embed de FAQ', '{"faq"}', '{"embedded"}', 0.75, TRUE, 61, TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_collection
  ON public.knowledge_nodes ((metadata->>'collection_slug'))
  WHERE metadata ? 'collection_slug';

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_category
  ON public.knowledge_nodes ((metadata->>'category_slug'))
  WHERE metadata ? 'category_slug';

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_collection_type
  ON public.knowledge_nodes ((metadata->>'collection_type'))
  WHERE metadata ? 'collection_type';

CREATE OR REPLACE FUNCTION pg_temp.m037_upsert_node(
  p_persona_id uuid,
  p_node_type text,
  p_slug text,
  p_title text,
  p_summary text,
  p_tags text[],
  p_metadata jsonb,
  p_status text
) RETURNS uuid AS $f$
DECLARE
  v_id uuid;
BEGIN
  SELECT id INTO v_id
  FROM public.knowledge_nodes
  WHERE COALESCE(persona_id::text, '') = COALESCE(p_persona_id::text, '')
    AND node_type = p_node_type
    AND slug = p_slug
  LIMIT 1;

  IF v_id IS NULL THEN
    INSERT INTO public.knowledge_nodes
      (persona_id, node_type, slug, title, summary, tags, metadata, status)
    VALUES
      (p_persona_id, p_node_type, p_slug, p_title, p_summary,
       COALESCE(p_tags, ARRAY[]::text[]), COALESCE(p_metadata, '{}'::jsonb),
       COALESCE(p_status, 'active'))
    RETURNING id INTO v_id;
  ELSE
    UPDATE public.knowledge_nodes
       SET title = COALESCE(p_title, title),
           summary = COALESCE(p_summary, summary),
           tags = (SELECT ARRAY(SELECT DISTINCT unnest(COALESCE(tags, ARRAY[]::text[]) || COALESCE(p_tags, ARRAY[]::text[])))),
           metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(p_metadata, '{}'::jsonb),
           status = COALESCE(p_status, status),
           updated_at = now()
     WHERE id = v_id;
  END IF;

  RETURN v_id;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pg_temp.m037_upsert_edge(
  p_persona_id uuid,
  p_source uuid,
  p_target uuid,
  p_relation text,
  p_weight numeric,
  p_metadata jsonb
) RETURNS void AS $f$
BEGIN
  IF p_source IS NULL OR p_target IS NULL OR p_source = p_target THEN
    RETURN;
  END IF;

  INSERT INTO public.knowledge_edges
    (persona_id, source_node_id, target_node_id, relation_type, weight, metadata)
  VALUES
    (p_persona_id, p_source, p_target, p_relation,
     COALESCE(p_weight, 1.0), COALESCE(p_metadata, '{}'::jsonb))
  ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE SET
    persona_id = EXCLUDED.persona_id,
    weight = EXCLUDED.weight,
    metadata = COALESCE(public.knowledge_edges.metadata, '{}'::jsonb) || EXCLUDED.metadata || '{"active":true}'::jsonb,
    updated_at = now();
END
$f$ LANGUAGE plpgsql;

DO $$
DECLARE
  baita_persona_id uuid;
  persona_node_id uuid;
  brand_id uuid;
  collection_id uuid;
  briefing_id uuid;
  cat_cervejas_premium_id uuid;
  cat_cervejas_id uuid;
  cat_destilados_premium_id uuid;
  cat_a_noite_pede_id uuid;
  cat_vinhos_espumantes_id uuid;
  cat_energia_drinks_id uuid;
  cat_bateu_fome_id uuid;
  cat_munchies_id uuid;
  cat_headshop_id uuid;
  prod_jager_id uuid;
  prod_patagonia_id uuid;
  prod_suspeito_id uuid;
  prod_lagunitas_id uuid;
  primary_meta jsonb := jsonb_build_object('seed','037_product_collection','primary_tree',true,'active',true);
  aux_meta jsonb := jsonb_build_object('seed','037_product_collection','primary_tree',false,'active',true);
BEGIN
  SELECT id INTO baita_persona_id FROM public.personas WHERE slug IN ('baita-conveniencia', 'baita') ORDER BY CASE slug WHEN 'baita-conveniencia' THEN 0 ELSE 1 END LIMIT 1;
  IF baita_persona_id IS NULL THEN
    RAISE NOTICE 'Persona Baita not found, skipping product collection seed.';
    RETURN;
  END IF;

  persona_node_id := pg_temp.m037_upsert_node(baita_persona_id, 'persona', 'baita-conveniencia', 'Baita Conveniencia', 'Persona raiz da Baita Conveniencia.', ARRAY['baita','persona'], jsonb_build_object('persona_slug','baita-conveniencia','protected',true), 'validated');
  brand_id := pg_temp.m037_upsert_node(baita_persona_id, 'brand', 'baita', 'Baita''', 'Brand Baita'' conectada ao fluxo de produtos.', ARRAY['baita','brand'], jsonb_build_object('persona_slug','baita-conveniencia'), 'pending_validation');
  collection_id := pg_temp.m037_upsert_node(baita_persona_id, 'product_collection', 'cardapio-baita-v14', 'Cardapio Baita'' v14', 'Cardapio oficial da Baita'' Conveniencia, versao v14.', ARRAY['product_collection','cardapio','baita','v14'], jsonb_build_object('collection_type','menu','display_name','Cardapio Baita'' v14','version','v14','source_file','BAITA_MENU_SYSTEM_v14_2.md'), 'pending_validation');
  briefing_id := pg_temp.m037_upsert_node(baita_persona_id, 'briefing', 'editorial-premium-motion', 'Editorial Premium Motion', 'Briefing editorial para a colecao Baita'' v14: premium, movimento, textura noturna e foco em produto.', ARRAY['editorial','premium','motion','baita'], jsonb_build_object('editorial_style','premium_motion','collection_slug','cardapio-baita-v14'), 'pending_validation');

  cat_cervejas_premium_id := pg_temp.m037_upsert_node(baita_persona_id,'category','cervejas-premium','Cervejas Premium','Long necks, IPAs, weisses e premium imports.',ARRAY['cerveja','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',10),'pending_validation');
  cat_cervejas_id := pg_temp.m037_upsert_node(baita_persona_id,'category','cervejas','Cervejas','Cervejas mainstream em lata, long neck e 600ml.',ARRAY['cerveja'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',20),'pending_validation');
  cat_destilados_premium_id := pg_temp.m037_upsert_node(baita_persona_id,'category','destilados-premium','Destilados Premium','Licores, whiskies, gins e destilados premium.',ARRAY['destilado','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',30),'pending_validation');
  cat_a_noite_pede_id := pg_temp.m037_upsert_node(baita_persona_id,'category','a-noite-pede','A Noite Pede','Drinks prontos e bebidas para a noite.',ARRAY['drink','noite'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',40),'pending_validation');
  cat_vinhos_espumantes_id := pg_temp.m037_upsert_node(baita_persona_id,'category','vinhos-e-espumantes','Vinhos e Espumantes','Vinhos, frisantes e espumantes.',ARRAY['vinho','espumante'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',50),'pending_validation');
  cat_energia_drinks_id := pg_temp.m037_upsert_node(baita_persona_id,'category','energia-drinks','Energia & Drinks','Energeticos, isotonicos, refrigerantes e mixers.',ARRAY['energetico','drinks'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',60),'pending_validation');
  cat_bateu_fome_id := pg_temp.m037_upsert_node(baita_persona_id,'category','bateu-a-fome','Bateu a Fome?','Comidas, pasteis, sandubas, porcoes e pizzas.',ARRAY['comida','fome'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',70),'pending_validation');
  cat_munchies_id := pg_temp.m037_upsert_node(baita_persona_id,'category','munchies','Munchies','Bomboniere, salgadinhos, chocolates e snacks.',ARRAY['munchies','snacks'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',80),'pending_validation');
  cat_headshop_id := pg_temp.m037_upsert_node(baita_persona_id,'category','headshop-tabacaria','Headshop & Tabacaria','Cigarros, sedas, filtros, piteiras, tabacos e acessorios.',ARRAY['tabacaria','headshop'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',90),'pending_validation');

  prod_jager_id := pg_temp.m037_upsert_node(baita_persona_id,'product','licor-jagermeister-700ml','Licor Jagermeister 700ml','Licor amargo alemao com 56 ervas, raizes e especiarias. Servido bem gelado, classico de bar.',ARRAY['licor','jagermeister','destilado','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','destilados-premium','volume_ml',700,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_patagonia_id := pg_temp.m037_upsert_node(baita_persona_id,'product','patagonia-weisse-473ml','Patagonia Weisse 473ml','Cerveja de trigo argentina, refrescante e frutada.',ARRAY['cerveja','weisse','trigo','patagonia','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','cervejas-premium','volume_ml',473,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_suspeito_id := pg_temp.m037_upsert_node(baita_persona_id,'product','vinho-suspeito-750ml','Vinho Suspeito 750ml','Vinho natural brasileiro, rotulo Suspeito, em variacoes para o cardapio.',ARRAY['vinho','natural','suspeito'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','vinhos-e-espumantes','volume_ml',750,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_lagunitas_id := pg_temp.m037_upsert_node(baita_persona_id,'product','lagunitas-daytime-355ml','Lagunitas Daytime Session IPA 355ml','Session IPA da Lagunitas California, leve e aromatica.',ARRAY['cerveja','ipa','session','lagunitas','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','cervejas-premium','volume_ml',355,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, persona_node_id, brand_id, 'contains', 1.0, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, brand_id, collection_id, 'brand_has_collection', 0.9, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, briefing_id, 'collection_has_briefing', 0.85, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_cervejas_premium_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_cervejas_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_destilados_premium_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_a_noite_pede_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_vinhos_espumantes_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_energia_drinks_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_bateu_fome_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_munchies_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_headshop_id, 'collection_has_category', 0.85, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_destilados_premium_id, prod_jager_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_cervejas_premium_id, prod_patagonia_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_vinhos_espumantes_id, prod_suspeito_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_cervejas_premium_id, prod_lagunitas_id, 'category_has_product', 0.86, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_jager_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_patagonia_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_suspeito_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_lagunitas_id, collection_id, 'part_of_collection', 0.70, aux_meta);
END$$;




-- ---------------------------------------------------------------------
-- File: 038_system_events_audit_index.sql
-- ---------------------------------------------------------------------

-- 038_system_events_audit_index.sql
-- Speed up GET /logs/audit, which filters system_events by entity_type or
-- event_type and orders by created_at DESC. Without these indexes the audit
-- tab does a sequential scan that gets slower as the table grows.

CREATE INDEX IF NOT EXISTS idx_system_events_entity_created
  ON public.system_events (entity_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_system_events_event_created
  ON public.system_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_system_events_persona_created
  ON public.system_events (persona_id, created_at DESC)
  WHERE persona_id IS NOT NULL;




-- ---------------------------------------------------------------------
-- File: 039_graph_canonical_taxonomy.sql
-- ---------------------------------------------------------------------

-- 039_graph_canonical_taxonomy.sql
-- Canonical fractal graph taxonomy.
--
-- Establishes ONE source of truth for node types, relation types, and edge
-- kinds (primary | secondary | asset_pending | asset_approved). Extends the
-- existing registries (009) and reconciles 037's product_collection/category
-- under a single product_group canonical type.
--
-- Idempotent and additive.

-- ── 1. Extend node-type registry with canonical/alias columns ──────

ALTER TABLE public.knowledge_node_type_registry
  ADD COLUMN IF NOT EXISTS alias_of      TEXT,
  ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS canonical     BOOLEAN NOT NULL DEFAULT TRUE;

-- ── 2. Extend relation registry with edge-kind classification ──────

ALTER TABLE public.knowledge_relation_type_registry
  ADD COLUMN IF NOT EXISTS edge_kind          TEXT NOT NULL DEFAULT 'secondary',
  ADD COLUMN IF NOT EXISTS primary_one_to_one BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS canonical          BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.check_constraints
    WHERE constraint_schema = 'public'
      AND constraint_name = 'knowledge_relation_type_registry_edge_kind_check'
  ) THEN
    ALTER TABLE public.knowledge_relation_type_registry
      ADD CONSTRAINT knowledge_relation_type_registry_edge_kind_check
      CHECK (edge_kind IN ('primary','secondary','asset_pending','asset_approved'));
  END IF;
END$$;

-- ── 3. Insert/upsert canonical node types (12) ─────────────────────

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical)
VALUES
  ('persona',       'Persona',        'Raiz cognitiva do grafo. Origem da marca e contexto.',         0,  1.00, '#7c6fff', 'user',          0,  TRUE),
  ('brand',         'Brand',          'Identidade, posicionamento e atributos de marca.',            10, 0.95, '#a78bfa', 'badge',         10, TRUE),
  ('briefing',      'Briefing',       'Contexto estratégico operacional, direto sob Brand.',         20, 0.90, '#c084fc', 'file-text',     20, TRUE),
  ('campaign',      'Campaign',       'Ação comercial ou criativa, direto sob Briefing.',            30, 0.85, '#fb923c', 'megaphone',     30, TRUE),
  ('audience',      'Audience',       'Público-alvo da campanha. Pai semântico do product_group.',   40, 0.80, '#f472b6', 'users',         40, TRUE),
  ('product_group', 'Product Group',  'Categoria/coleção/grupo de produtos. Tipo único canônico.',   50, 0.78, '#34d399', 'folder',        50, TRUE),
  ('product',       'Product',        'Produto específico abaixo de product_group.',                 60, 0.85, '#60a5fa', 'package',       60, TRUE),
  ('offer',         'Offer',          'Proposta comercial aplicada ao produto.',                     70, 0.75, '#facc15', 'tag',           70, TRUE),
  ('copy',          'Copy',           'Argumento textual derivado da offer.',                        80, 0.70, '#64748b', 'text',          80, TRUE),
  ('faq',           'FAQ',            'Saída final textual. Filha direta de copy.',                  90, 0.65, '#4ade80', 'circle-help',   90, TRUE),
  ('gallery',       'Gallery',        'Saída final visual. Filha direta de copy.',                   90, 0.65, '#d946ef', 'image',         91, TRUE),
  ('asset',         'Asset',          'Camada lateral. Pode conectar a qualquer node ou a outro asset.', 95, 0.55, '#f59e0b', 'image', 95, TRUE)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  canonical = TRUE,
  alias_of = NULL,
  deprecated_at = NULL,
  active = TRUE,
  updated_at = now();

-- ── 4. Mark legacy types as aliases of canonical ones ──────────────

UPDATE public.knowledge_node_type_registry
   SET alias_of      = 'product_group',
       canonical     = FALSE,
       deprecated_at = COALESCE(deprecated_at, now()),
       updated_at    = now()
 WHERE node_type IN ('product_collection','category');

-- Non-canonical (kept active for backwards compat but flagged):
UPDATE public.knowledge_node_type_registry
   SET canonical  = FALSE,
       updated_at = now()
 WHERE node_type IN ('entity','tone','rule','tag','knowledge_item','kb_entry','embedded')
   AND canonical IS DISTINCT FROM FALSE;

-- ── 5. Backfill node_type in knowledge_nodes ───────────────────────
-- Convert product_collection / category to product_group canonical type.

UPDATE public.knowledge_nodes
   SET node_type = 'product_group',
       metadata  = COALESCE(metadata, '{}'::jsonb)
                || jsonb_build_object(
                     'legacy_node_type', node_type,
                     'canonicalized_at', now()::text
                   ),
       updated_at = now()
 WHERE node_type IN ('product_collection','category');

-- ── 6. Canonical primary relation graph ────────────────────────────

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types,
   default_weight, directional, sort_order, edge_kind, primary_one_to_one, canonical)
VALUES
  ('brand_has_briefing',        'brand tem briefing',        'briefing de brand',
     '{"brand"}',         '{"briefing"}',       0.95, TRUE,  100, 'primary', TRUE,  TRUE),
  ('briefing_has_campaign',     'briefing tem campanha',     'campanha do briefing',
     '{"briefing"}',      '{"campaign"}',       0.90, TRUE,  110, 'primary', FALSE, TRUE),
  ('campaign_has_audience',     'campanha tem audiência',    'audiência da campanha',
     '{"campaign"}',      '{"audience"}',       0.90, TRUE,  120, 'primary', FALSE, TRUE),
  ('audience_has_product_group','audiência tem grupo',       'grupo da audiência',
     '{"audience"}',      '{"product_group"}',  0.85, TRUE,  130, 'primary', FALSE, TRUE),
  ('product_group_has_product', 'grupo tem produto',         'produto do grupo',
     '{"product_group"}', '{"product"}',        0.85, TRUE,  140, 'primary', FALSE, TRUE),
  ('product_has_offer',         'produto tem oferta',        'oferta do produto',
     '{"product"}',       '{"offer"}',          0.80, TRUE,  150, 'primary', FALSE, TRUE),
  ('offer_has_copy',             'oferta tem copy',          'copy da oferta',
     '{"offer"}',         '{"copy"}',           0.80, TRUE,  160, 'primary', FALSE, TRUE),
  ('copy_has_faq',              'copy tem FAQ',              'FAQ da copy',
     '{"copy"}',          '{"faq"}',            0.80, TRUE,  170, 'primary', TRUE,  TRUE),
  ('copy_has_gallery',          'copy tem gallery',          'gallery da copy',
     '{"copy"}',          '{"gallery"}',        0.80, TRUE,  180, 'primary', TRUE,  TRUE),
  ('persona_has_brand',         'persona tem brand',         'brand da persona',
     '{"persona"}',       '{"brand"}',          1.00, TRUE,   90, 'primary', TRUE,  TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  edge_kind = EXCLUDED.edge_kind,
  primary_one_to_one = EXCLUDED.primary_one_to_one,
  canonical = TRUE,
  active = TRUE,
  updated_at = now();

-- ── 7. Asset lateral relations (pending + approved + gallery) ──────

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types,
   default_weight, directional, sort_order, edge_kind, primary_one_to_one, canonical)
VALUES
  ('asset_pending',   'asset pendente',          'pendência de aprovação',
     '{}', '{"asset"}', 0.50, TRUE, 200, 'asset_pending',  FALSE, TRUE),
  ('asset_approved',  'asset aprovado',          'aprovação de asset',
     '{}', '{"asset"}', 0.90, TRUE, 201, 'asset_approved', FALSE, TRUE),
  ('gallery_has_asset','gallery tem asset',      'asset da gallery',
     '{"gallery"}', '{"asset"}', 0.95, TRUE, 202, 'asset_approved', FALSE, TRUE),
  ('asset_related',   'asset relacionado',       'relacionado',
     '{"asset"}', '{"asset"}', 0.40, FALSE, 203, 'secondary', FALSE, TRUE),
  ('secondary',       'conexão secundária',      'conexão secundária',
     '{}', '{}', 0.30, FALSE, 999, 'secondary', FALSE, TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  edge_kind = EXCLUDED.edge_kind,
  primary_one_to_one = EXCLUDED.primary_one_to_one,
  canonical = TRUE,
  active = TRUE,
  updated_at = now();

-- ── 8. Mark legacy relations as non-canonical aliases ──────────────
-- Legacy hierarchy from 037 (brand_has_collection, collection_has_briefing,
-- collection_has_category, category_has_product, etc) stays active for read
-- compatibility but is flagged so middleware in window 3 can refuse to write
-- new primary edges using them.

UPDATE public.knowledge_relation_type_registry
   SET canonical  = FALSE,
       updated_at = now()
 WHERE relation_type IN (
   'brand_has_collection',
   'collection_has_briefing',
   'collection_has_category',
   'part_of_collection',
   'category_has_product',
   'in_category',
   'product_has_copy',
   'product_has_faq',
   'product_has_asset',
   'product_image',
   'faq_has_embed',
   'defines_brand',
   'has_tone',
   'about_product',
   'part_of_campaign',
   'answers_question',
   'supports_copy',
   'uses_asset',
   'briefed_by',
   'same_topic_as',
   'duplicate_of',
   'derived_from',
   'contains',
   'belongs_to_persona',
   'gallery_asset'
 ) AND canonical IS DISTINCT FROM FALSE;

-- ── 9. Compatibility view exposing canonicalized node_type ─────────

CREATE OR REPLACE VIEW public.knowledge_nodes_canonical AS
SELECT
  n.*,
  COALESCE(r.alias_of, n.node_type) AS canonical_node_type
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_node_type_registry r
  ON r.node_type = n.node_type;

COMMENT ON VIEW public.knowledge_nodes_canonical IS
  'Knowledge nodes exposing canonical_node_type that resolves alias_of from '
  'knowledge_node_type_registry (e.g. product_collection -> product_group).';

-- ── 10. Helper indexes for taxonomy lookup ─────────────────────────

CREATE INDEX IF NOT EXISTS idx_kn_type_registry_canonical
  ON public.knowledge_node_type_registry (canonical, sort_order)
  WHERE canonical = TRUE;

CREATE INDEX IF NOT EXISTS idx_kr_type_registry_edge_kind
  ON public.knowledge_relation_type_registry (edge_kind, canonical, sort_order)
  WHERE canonical = TRUE;




-- ---------------------------------------------------------------------
-- File: 040_personas_catalog_url.sql
-- ---------------------------------------------------------------------

-- 040_personas_catalog_url.sql
-- Adds personas.catalog_url so each persona can point to its public catalog
-- (dashboard /persona surfaces this and the cardapio link uses it directly
-- when present, falling back to NEXT_PUBLIC_CARDAPIO_BASE_URL/{slug}).
--
-- Idempotent and additive. Safe to re-run.

ALTER TABLE public.personas
  ADD COLUMN IF NOT EXISTS catalog_url text;

COMMENT ON COLUMN public.personas.catalog_url IS
  'Public catalog URL for this persona. When NULL the frontend derives the URL '
  'from NEXT_PUBLIC_CARDAPIO_BASE_URL + persona.slug. Set per-persona to point '
  'to a custom domain or a different cardapio deploy.';

-- Seed sensible defaults for personas we know already have catalogs in QA/PROD.
-- INSERT-IF-NULL semantics: never overwrites a value the operator already set.

UPDATE public.personas
   SET catalog_url = 'https://baita-cardapio.vercel.app/baita-conveniencia'
 WHERE slug = 'baita-conveniencia'
   AND catalog_url IS NULL;

UPDATE public.personas
   SET catalog_url = 'https://baita-cardapio-qa.vercel.app/vz-lupas'
 WHERE slug = 'vz-lupas'
   AND catalog_url IS NULL;




-- ---------------------------------------------------------------------
-- File: 041_hierarchical_graph_validation_contract.sql
-- ---------------------------------------------------------------------

-- 041_hierarchical_graph_validation_contract.sql
-- Enforce canonical top-down hierarchy and FAQ->Embed gate.
-- Additive, idempotent, and rollback-friendly.

-- 1) Explicit edge semantics
ALTER TABLE public.knowledge_edges
  ADD COLUMN IF NOT EXISTS edge_type TEXT;

UPDATE public.knowledge_edges e
SET edge_type = CASE
  WHEN COALESCE((e.metadata->>'primary_tree')::boolean, false) = true THEN 'main'
  WHEN r.edge_kind = 'primary' THEN 'main'
  ELSE 'reference'
END
FROM public.knowledge_relation_type_registry r
WHERE e.relation_type = r.relation_type
  AND e.edge_type IS NULL;

UPDATE public.knowledge_edges
SET edge_type = 'reference'
WHERE edge_type IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.check_constraints
    WHERE constraint_schema = 'public'
      AND constraint_name = 'knowledge_edges_edge_type_check'
  ) THEN
    ALTER TABLE public.knowledge_edges
      ADD CONSTRAINT knowledge_edges_edge_type_check
      CHECK (edge_type IN ('main', 'reference'));
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_edge_type
  ON public.knowledge_edges(edge_type);

-- Demote duplicate active main parents before adding uniqueness index.
WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY target_node_id
      ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id
    ) AS rn
  FROM public.knowledge_edges
  WHERE edge_type = 'main'
    AND COALESCE((metadata->>'active')::boolean, true) = true
)
UPDATE public.knowledge_edges e
SET metadata = jsonb_strip_nulls(
      COALESCE(e.metadata, '{}'::jsonb)
      || jsonb_build_object(
        'active', false,
        'primary_tree', false,
        'visual_hidden', true,
        'demoted_from', 'migration_041_main_parent_uniqueness'
      )
    ),
    updated_at = now()
FROM ranked r
WHERE e.id = r.id
  AND r.rn > 1;

-- One active main parent per child node.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_main_parent_per_child
  ON public.knowledge_edges(target_node_id)
  WHERE edge_type = 'main'
    AND COALESCE((metadata->>'active')::boolean, true) = true;

-- 2) Validation registry for allowed edges
CREATE TABLE IF NOT EXISTS public.knowledge_allowed_edges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  edge_type TEXT NOT NULL CHECK (edge_type IN ('main','reference')),
  requires_source_status TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  rationale TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_type, target_type, edge_type)
);

INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, rationale)
VALUES
  ('persona', 'brand', 'main', NULL, 'Canonical root edge'),
  ('brand', 'briefing', 'main', NULL, 'Canonical hierarchy'),
  ('briefing', 'campaign', 'main', NULL, 'Canonical hierarchy'),
  ('campaign', 'audience', 'main', NULL, 'Canonical hierarchy'),
  ('audience', 'product_group', 'main', NULL, 'Canonical hierarchy'),
  ('product_group', 'product', 'main', NULL, 'Canonical hierarchy'),
  ('product', 'offer', 'main', NULL, 'Canonical hierarchy'),
  ('offer', 'copy', 'main', NULL, 'Canonical hierarchy'),
  ('copy', 'faq', 'main', NULL, 'Canonical hierarchy'),
  ('faq', 'embed', 'main', 'approved', 'Only approved FAQ can create embed')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  rationale = EXCLUDED.rationale,
  active = true,
  updated_at = now();

-- Reference edges are flexible but cannot target embed except approved FAQ.
INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, rationale)
VALUES
  ('faq', 'embed', 'reference', 'approved', 'Reference publication to embed still requires approved FAQ')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  rationale = EXCLUDED.rationale,
  active = true,
  updated_at = now();

-- 3) Validation events + snapshots
CREATE TABLE IF NOT EXISTS public.graph_validation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id UUID REFERENCES public.personas(id) ON DELETE SET NULL,
  edge_id UUID REFERENCES public.knowledge_edges(id) ON DELETE SET NULL,
  source_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  target_node_id UUID REFERENCES public.knowledge_nodes(id) ON DELETE SET NULL,
  edge_type TEXT,
  relation_type TEXT,
  error_code TEXT NOT NULL,
  message TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_validation_events_persona_created
  ON public.graph_validation_events(persona_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_validation_events_error_code
  ON public.graph_validation_events(error_code, created_at DESC);

CREATE TABLE IF NOT EXISTS public.graph_validation_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  snapshot_type TEXT NOT NULL DEFAULT 'pre_migration'
    CHECK (snapshot_type IN ('pre_migration','post_migration','manual')),
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_validation_snapshots_persona
  ON public.graph_validation_snapshots(persona_id, created_at DESC);

-- 4) Canonicalize embedded -> embed node type alias
INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical)
VALUES
  ('embed', 'Embed', 'Embedding publication node generated from approved FAQ.', 100, 0.40, '#a3a3a3', 'cpu', 100, true)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  canonical = true,
  active = true,
  updated_at = now();

UPDATE public.knowledge_node_type_registry
SET alias_of = 'embed',
    canonical = false,
    deprecated_at = COALESCE(deprecated_at, now()),
    updated_at = now()
WHERE node_type = 'embedded';

UPDATE public.knowledge_nodes
SET node_type = 'embed',
    metadata = COALESCE(metadata, '{}'::jsonb)
      || jsonb_build_object('legacy_node_type', 'embedded', 'canonicalized_at', now()::text),
    updated_at = now()
WHERE node_type = 'embedded';

-- 5) Validation function and trigger
CREATE OR REPLACE FUNCTION public.validate_knowledge_edge_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  src_type TEXT;
  tgt_type TEXT;
  src_status TEXT;
  src_order INT;
  tgt_order INT;
  allowed_row public.knowledge_allowed_edges%ROWTYPE;
  existing_cycle BOOLEAN;
  err_code TEXT;
  err_message TEXT;
  err_details JSONB;
BEGIN
  SELECT n.node_type, n.status INTO src_type, src_status
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.source_node_id;

  SELECT n.node_type INTO tgt_type
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.target_node_id;

  IF src_type IS NULL OR tgt_type IS NULL THEN
    RAISE EXCEPTION 'Graph validation failed: missing source or target node';
  END IF;

  IF NEW.edge_type = 'main' THEN
    SELECT * INTO allowed_row
    FROM public.knowledge_allowed_edges
    WHERE source_type = src_type
      AND target_type = tgt_type
      AND edge_type = 'main'
      AND active = true
    LIMIT 1;

    IF allowed_row.id IS NULL THEN
      err_code := 'INVALID_MAIN_EDGE';
      err_message := format(
        'Invalid edge: %s cannot connect directly to %s. Expected canonical top-down hierarchy.',
        upper(src_type), upper(tgt_type)
      );
      err_details := jsonb_build_object(
        'source_type', src_type,
        'target_type', tgt_type,
        'edge_type', NEW.edge_type
      );
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    -- Main hierarchy direction cannot move backward.
    SELECT sort_order INTO src_order FROM public.knowledge_node_type_registry WHERE node_type = src_type;
    SELECT sort_order INTO tgt_order FROM public.knowledge_node_type_registry WHERE node_type = tgt_type;
    IF src_order IS NOT NULL AND tgt_order IS NOT NULL AND src_order >= tgt_order THEN
      err_code := 'MAIN_EDGE_BACKWARD';
      err_message := format(
        'Invalid main edge direction: %s (%s) cannot point to %s (%s).',
        upper(src_type), src_order, upper(tgt_type), tgt_order
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'source_order', src_order, 'target_order', tgt_order);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    -- Cycle check only for active main edges.
    IF COALESCE((NEW.metadata->>'active')::boolean, true) = true THEN
      WITH RECURSIVE walk AS (
        SELECT e.target_node_id
        FROM public.knowledge_edges e
        WHERE e.source_node_id = NEW.target_node_id
          AND e.edge_type = 'main'
          AND COALESCE((e.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e.id <> NEW.id)
        UNION ALL
        SELECT e2.target_node_id
        FROM public.knowledge_edges e2
        JOIN walk w ON w.target_node_id = e2.source_node_id
        WHERE e2.edge_type = 'main'
          AND COALESCE((e2.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e2.id <> NEW.id)
      )
      SELECT EXISTS (
        SELECT 1 FROM walk WHERE target_node_id = NEW.source_node_id
      ) INTO existing_cycle;

      IF existing_cycle THEN
        err_code := 'MAIN_EDGE_CYCLE';
        err_message := format('Cycle detected: main edge %s -> %s would create a loop.', NEW.source_node_id, NEW.target_node_id);
        err_details := jsonb_build_object('source_node_id', NEW.source_node_id, 'target_node_id', NEW.target_node_id, 'edge_type', NEW.edge_type);
        INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
        VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
        RAISE EXCEPTION '%', err_message;
      END IF;
    END IF;
  END IF;

  -- Embed target guard for both main/reference.
  IF tgt_type = 'embed' THEN
    IF src_type <> 'faq' THEN
      err_code := 'EMBED_SOURCE_NOT_FAQ';
      err_message := format(
        'Invalid edge: %s cannot connect directly to EMBED. Expected path: PRODUCT -> FAQ -> EMBED with FAQ.status = approved.',
        upper(src_type)
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    IF COALESCE(src_status, '') <> 'approved' THEN
      err_code := 'FAQ_NOT_APPROVED_FOR_EMBED';
      err_message := 'Invalid edge: FAQ must be approved before EMBED creation.';
      err_details := jsonb_build_object('source_status', src_status, 'required_status', 'approved');
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_knowledge_edge_contract ON public.knowledge_edges;
CREATE TRIGGER trg_validate_knowledge_edge_contract
BEFORE INSERT OR UPDATE ON public.knowledge_edges
FOR EACH ROW
EXECUTE FUNCTION public.validate_knowledge_edge_contract();

-- 6) Snapshot existing state before runtime starts rejecting new writes.
INSERT INTO public.graph_validation_snapshots(persona_id, snapshot_type, payload)
SELECT
  n.persona_id,
  'pre_migration',
  jsonb_build_object(
    'nodes', count(DISTINCT n.id),
    'edges', count(DISTINCT e.id),
    'main_edges', count(DISTINCT CASE WHEN e.edge_type = 'main' THEN e.id END),
    'captured_at', now()
  )
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_edges e
  ON e.persona_id = n.persona_id
GROUP BY n.persona_id;




-- ---------------------------------------------------------------------
-- File: 042_bra20_graph_validation_hardening_draft.sql
-- ---------------------------------------------------------------------

-- 042_bra20_graph_validation_hardening_draft.sql
-- Draft only: review before apply in QA/PROD.
-- Purpose: harden hierarchical graph validation contracts for BRA-20.

BEGIN;

-- 1) Ensure hierarchy node types include canonical embed.
INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order, canonical, active)
VALUES
  ('embed', 'Embed', 'Embedding publication node generated from approved FAQ.', 100, 0.40, '#a3a3a3', 'cpu', 100, true, true)
ON CONFLICT (node_type) DO UPDATE SET
  canonical = true,
  active = true,
  updated_at = now();

-- 2) Ensure allowed-edge matrix exists for strict hierarchy and FAQ->embed gate.
INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, active, rationale)
VALUES
  ('persona', 'brand', 'main', NULL, true, 'Canonical hierarchy'),
  ('brand', 'briefing', 'main', NULL, true, 'Canonical hierarchy'),
  ('briefing', 'campaign', 'main', NULL, true, 'Canonical hierarchy'),
  ('campaign', 'audience', 'main', NULL, true, 'Canonical hierarchy'),
  ('audience', 'product_group', 'main', NULL, true, 'Canonical hierarchy'),
  ('product_group', 'product', 'main', NULL, true, 'Canonical hierarchy'),
  ('product', 'offer', 'main', NULL, true, 'Canonical hierarchy'),
  ('offer', 'copy', 'main', NULL, true, 'Canonical hierarchy'),
  ('copy', 'faq', 'main', NULL, true, 'Canonical hierarchy'),
  ('faq', 'embed', 'main', 'approved', true, 'Only approved FAQ can publish to embed'),
  ('faq', 'embed', 'reference', 'approved', true, 'Only approved FAQ can reference embed')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  active = true,
  rationale = EXCLUDED.rationale,
  updated_at = now();

-- 3) Preserve state snapshots before strict validation adoption.
INSERT INTO public.graph_validation_snapshots(persona_id, snapshot_type, payload)
SELECT
  n.persona_id,
  'manual',
  jsonb_build_object(
    'reason', 'migration_042_pre_hardening',
    'nodes', count(DISTINCT n.id),
    'edges', count(DISTINCT e.id),
    'captured_at', now()
  )
FROM public.knowledge_nodes n
LEFT JOIN public.knowledge_edges e ON e.persona_id = n.persona_id
GROUP BY n.persona_id;

-- 4) Validation function patch with explicit main-parent uniqueness code.
CREATE OR REPLACE FUNCTION public.validate_knowledge_edge_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  src_type TEXT;
  tgt_type TEXT;
  src_status TEXT;
  src_order INT;
  tgt_order INT;
  existing_parent UUID;
  allowed_row public.knowledge_allowed_edges%ROWTYPE;
  existing_cycle BOOLEAN;
  err_code TEXT;
  err_message TEXT;
  err_details JSONB;
BEGIN
  SELECT n.node_type, n.status INTO src_type, src_status
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.source_node_id;

  SELECT n.node_type INTO tgt_type
  FROM public.knowledge_nodes n
  WHERE n.id = NEW.target_node_id;

  IF src_type IS NULL OR tgt_type IS NULL THEN
    RAISE EXCEPTION 'Graph validation failed: missing source or target node';
  END IF;

  IF NEW.edge_type = 'main' THEN
    SELECT e.id INTO existing_parent
    FROM public.knowledge_edges e
    WHERE e.target_node_id = NEW.target_node_id
      AND e.edge_type = 'main'
      AND COALESCE((e.metadata->>'active')::boolean, true) = true
      AND (TG_OP <> 'UPDATE' OR e.id <> NEW.id)
    LIMIT 1;

    IF existing_parent IS NOT NULL AND COALESCE((NEW.metadata->>'active')::boolean, true) = true THEN
      err_code := 'MULTIPLE_ACTIVE_MAIN_PARENTS';
      err_message := 'Invalid main edge: child node already has an active main parent.';
      err_details := jsonb_build_object(
        'existing_parent_edge_id', existing_parent,
        'target_node_id', NEW.target_node_id
      );
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    SELECT * INTO allowed_row
    FROM public.knowledge_allowed_edges
    WHERE source_type = src_type
      AND target_type = tgt_type
      AND edge_type = 'main'
      AND active = true
    LIMIT 1;

    IF allowed_row.id IS NULL THEN
      err_code := 'INVALID_MAIN_EDGE';
      err_message := format('Invalid edge: %s cannot connect directly to %s.', upper(src_type), upper(tgt_type));
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'edge_type', NEW.edge_type);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    SELECT sort_order INTO src_order FROM public.knowledge_node_type_registry WHERE node_type = src_type;
    SELECT sort_order INTO tgt_order FROM public.knowledge_node_type_registry WHERE node_type = tgt_type;
    IF src_order IS NOT NULL AND tgt_order IS NOT NULL AND src_order >= tgt_order THEN
      err_code := 'MAIN_EDGE_BACKWARD';
      err_message := 'Invalid main edge direction: source must be above target in hierarchy.';
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'source_order', src_order, 'target_order', tgt_order);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    IF COALESCE((NEW.metadata->>'active')::boolean, true) = true THEN
      WITH RECURSIVE walk AS (
        SELECT e.target_node_id
        FROM public.knowledge_edges e
        WHERE e.source_node_id = NEW.target_node_id
          AND e.edge_type = 'main'
          AND COALESCE((e.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e.id <> NEW.id)
        UNION ALL
        SELECT e2.target_node_id
        FROM public.knowledge_edges e2
        JOIN walk w ON w.target_node_id = e2.source_node_id
        WHERE e2.edge_type = 'main'
          AND COALESCE((e2.metadata->>'active')::boolean, true) = true
          AND (TG_OP <> 'UPDATE' OR e2.id <> NEW.id)
      )
      SELECT EXISTS (SELECT 1 FROM walk WHERE target_node_id = NEW.source_node_id)
      INTO existing_cycle;

      IF existing_cycle THEN
        err_code := 'MAIN_EDGE_CYCLE';
        err_message := 'Invalid main edge: cycle detected.';
        err_details := jsonb_build_object('source_node_id', NEW.source_node_id, 'target_node_id', NEW.target_node_id);
        INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
        VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
        RAISE EXCEPTION '%', err_message;
      END IF;
    END IF;
  END IF;

  IF tgt_type = 'embed' THEN
    IF src_type <> 'faq' THEN
      err_code := 'EMBED_SOURCE_NOT_FAQ';
      err_message := format(
        'Invalid edge: %s cannot connect directly to EMBED. Expected path: PRODUCT -> FAQ -> EMBED with FAQ.status = approved.',
        upper(src_type)
      );
      err_details := jsonb_build_object('source_type', src_type, 'target_type', tgt_type, 'edge_type', NEW.edge_type);
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;

    IF COALESCE(src_status, '') <> 'approved' THEN
      err_code := 'FAQ_NOT_APPROVED_FOR_EMBED';
      err_message := 'Invalid edge: FAQ must be approved before EMBED creation.';
      err_details := jsonb_build_object('source_status', src_status, 'required_status', 'approved');
      INSERT INTO public.graph_validation_events(persona_id, edge_id, source_node_id, target_node_id, edge_type, relation_type, error_code, message, details)
      VALUES (NEW.persona_id, NEW.id, NEW.source_node_id, NEW.target_node_id, NEW.edge_type, NEW.relation_type, err_code, err_message, err_details);
      RAISE EXCEPTION '%', err_message;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_knowledge_edge_contract ON public.knowledge_edges;
CREATE TRIGGER trg_validate_knowledge_edge_contract
BEFORE INSERT OR UPDATE ON public.knowledge_edges
FOR EACH ROW
EXECUTE FUNCTION public.validate_knowledge_edge_contract();

COMMIT;

-- Rollback (manual):
-- 1) DROP TRIGGER trg_validate_knowledge_edge_contract ON public.knowledge_edges;
-- 2) Optionally restore prior validate_knowledge_edge_contract() body from migration 041.
-- 3) Keep graph_validation_events/snapshots to preserve audit history.


