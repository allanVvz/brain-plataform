-- Canonical conversation state (cart and confirmed-pending-human marker)
-- belongs to the lead, as defined by the deterministic conversation contract.

BEGIN;

ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
