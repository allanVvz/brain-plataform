-- ============================================================
-- AI Brain Platform — Migration 001
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
