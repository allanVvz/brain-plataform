-- Keep message metadata aligned with the application message contract.
-- Existing rows remain untouched; the default is safe for legacy inserts.
ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.messages.metadata IS
  'Non-sensitive message attributes such as agent, channel and provider type.';
