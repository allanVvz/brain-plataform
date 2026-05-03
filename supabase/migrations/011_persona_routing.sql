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
  'internal = AI Brain classifies + replies + sends. n8n = AI Brain only persists; n8n owns the reply.';
COMMENT ON COLUMN personas.outbound_webhook_url IS
  'Webhook used by /messages/send to deliver human/operator replies to WhatsApp via n8n. Used in BOTH process_modes.';
COMMENT ON COLUMN personas.inbound_webhook_token IS
  'Shared secret expected in X-Webhook-Token header when n8n calls POST /process for this persona.';
