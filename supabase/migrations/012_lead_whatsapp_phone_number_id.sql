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
