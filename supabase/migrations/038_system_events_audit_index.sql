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
