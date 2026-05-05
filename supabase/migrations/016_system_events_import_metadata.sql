-- 016_system_events_import_metadata.sql
-- Keep lead import audit data in existing system_events table.

ALTER TABLE public.system_events
  ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'info',
  ADD COLUMN IF NOT EXISTS source TEXT;

CREATE INDEX IF NOT EXISTS idx_system_events_entity
  ON public.system_events(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_system_events_source
  ON public.system_events(source);
