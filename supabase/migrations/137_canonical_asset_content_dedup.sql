-- 137_canonical_asset_content_dedup.sql
-- Canonical identity for binary assets.
--
-- The assets row is reserved before Storage is written.  A persona can own at
-- most one asset row for the same bytes, independently of filename or upload
-- retry.  Existing rows stay addressable; only rows whose digest is known take
-- part in the uniqueness contract.

ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS content_sha256 text;

ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_content_sha256_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_content_sha256_check
  CHECK (
    content_sha256 IS NULL
    OR content_sha256 ~ '^[0-9a-f]{64}$'
  );

COMMENT ON COLUMN public.assets.content_sha256 IS
  'Lowercase SHA-256 of the original bytes. Canonical deduplication key inside one persona.';

-- Preserve digests already collected by older importers. If those reveal two
-- rows with the same persona/hash, the unique-index statement below is meant
-- to fail: operators must reconcile their graph references instead of hiding
-- a pre-existing duplicate by leaving one digest NULL.
UPDATE public.assets
SET content_sha256 = lower(COALESCE(metadata->>'content_sha256', metadata->>'sha256'))
WHERE content_sha256 IS NULL
  AND lower(COALESCE(metadata->>'content_sha256', metadata->>'sha256', ''))
      ~ '^[0-9a-f]{64}$';

-- The original default made a newly uploaded, unreviewed file public-ready.
-- Approval is a distinct lifecycle from ingestion status and is authoritative
-- in this top-level column.
ALTER TABLE public.assets
  ALTER COLUMN approval_status SET DEFAULT 'pending';

UPDATE public.assets
SET approval_status = CASE
  WHEN lower(COALESCE(metadata->>'validation_status', '')) IN ('approved', 'validated', 'embedded')
    THEN 'approved'
  WHEN lower(COALESCE(metadata->>'validation_status', '')) = 'rejected'
    THEN 'rejected'
  WHEN lower(COALESCE(metadata->>'validation_status', '')) IN ('pending', 'pending_validation')
    THEN 'pending'
  ELSE COALESCE(approval_status, 'pending')
END
WHERE metadata ? 'validation_status' OR approval_status IS NULL;

-- Remove the former competing approval value.  Graph and knowledge metadata
-- may project approval_status, but public.assets.approval_status owns it.
UPDATE public.assets
SET metadata = COALESCE(metadata, '{}'::jsonb) - 'validation_status'
WHERE COALESCE(metadata, '{}'::jsonb) ? 'validation_status';

CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_persona_content_sha256
  ON public.assets(persona_id, content_sha256)
  WHERE persona_id IS NOT NULL AND content_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assets_content_sha256
  ON public.assets(content_sha256)
  WHERE content_sha256 IS NOT NULL;
