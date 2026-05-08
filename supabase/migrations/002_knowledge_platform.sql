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
