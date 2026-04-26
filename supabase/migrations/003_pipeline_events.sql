-- ============================================================
-- AI Brain Platform — Migration 003
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
