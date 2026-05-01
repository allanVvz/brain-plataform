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
