-- 033_asset_upload_pipeline.sql
-- File upload pipeline for Sofia/CRIAR (immediate context) and ASSET card (validatable).
-- Adds storage buckets, extends public.assets, creates public.asset_readings.

-- ── Storage buckets ──────────────────────────────────────────────────────
-- Public buckets: the cardapio menu (/api/menu, /cardapio) is auth-exempt and
-- emits /object/public/ asset URLs, so the buckets must be public for images
-- to resolve. ON CONFLICT keeps this idempotent and self-healing on re-apply.
INSERT INTO storage.buckets (id, name, public)
VALUES
  ('assets-raw',     'assets-raw',     true),
  ('assets-derived', 'assets-derived', true)
ON CONFLICT (id) DO UPDATE SET public = EXCLUDED.public;

-- ── public.assets — expand columns ───────────────────────────────────────
ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS storage_bucket     text,
  ADD COLUMN IF NOT EXISTS storage_path       text,
  ADD COLUMN IF NOT EXISTS mime_type          text,
  ADD COLUMN IF NOT EXISTS file_size          bigint,
  ADD COLUMN IF NOT EXISTS original_filename  text,
  ADD COLUMN IF NOT EXISTS status             text DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS upload_context     text,
  ADD COLUMN IF NOT EXISTS updated_at         timestamptz DEFAULT now();

-- Status enum for assets — pending | reading | ready | failed | archived
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_status_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_status_check
  CHECK (status IS NULL OR status IN ('pending','reading','ready','failed','archived'));

-- upload_context enum — sofia_chat | create_sidebar | asset_card | imported
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_upload_context_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_upload_context_check
  CHECK (upload_context IS NULL OR upload_context IN ('sofia_chat','create_sidebar','asset_card','imported'));

-- Extend type CHECK to include real file kinds (was image|copy|campaign|template).
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_type_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_type_check
  CHECK (type IS NULL OR type IN ('image','video','pdf','text','copy','campaign','template'));

-- Extend source CHECK to include direct uploads.
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_source_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_source_check
  CHECK (source IN ('maker','manual','mcp','imported','upload'));

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.assets_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_assets_updated_at ON public.assets;
CREATE TRIGGER trg_assets_updated_at
  BEFORE UPDATE ON public.assets
  FOR EACH ROW EXECUTE FUNCTION public.assets_set_updated_at();

-- Indexes for the new flows
CREATE INDEX IF NOT EXISTS idx_assets_persona_id      ON public.assets(persona_id);
CREATE INDEX IF NOT EXISTS idx_assets_status          ON public.assets(status);
CREATE INDEX IF NOT EXISTS idx_assets_source          ON public.assets(source);
CREATE INDEX IF NOT EXISTS idx_assets_upload_context  ON public.assets(upload_context);
CREATE INDEX IF NOT EXISTS idx_assets_created_at_desc ON public.assets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_session_id      ON public.assets((metadata->>'session_id'));
CREATE INDEX IF NOT EXISTS idx_assets_storage_path    ON public.assets(storage_bucket, storage_path);

-- ── public.asset_readings — pipeline output history ──────────────────────
CREATE TABLE IF NOT EXISTS public.asset_readings (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id        uuid NOT NULL REFERENCES public.assets(id) ON DELETE CASCADE,
  persona_id      uuid,
  reading_type    text NOT NULL CHECK (reading_type IN (
    'classification','ocr','ai_fallback','pdf_text','video_mock','rename'
  )),
  title           text,
  summary         text,
  extracted_text  text,
  visual_summary  text,
  markdown        text,
  classification  jsonb DEFAULT '{}'::jsonb,
  confidence      numeric DEFAULT 0.5,
  model_used      text,
  status          text DEFAULT 'completed' CHECK (status IN ('pending','completed','partial','mocked','failed')),
  metadata        jsonb DEFAULT '{}'::jsonb,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_readings_asset      ON public.asset_readings(asset_id, reading_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_asset_readings_persona    ON public.asset_readings(persona_id);
CREATE INDEX IF NOT EXISTS idx_asset_readings_status     ON public.asset_readings(status);

CREATE OR REPLACE FUNCTION public.asset_readings_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_asset_readings_updated_at ON public.asset_readings;
CREATE TRIGGER trg_asset_readings_updated_at
  BEFORE UPDATE ON public.asset_readings
  FOR EACH ROW EXECUTE FUNCTION public.asset_readings_set_updated_at();

-- ── RLS placeholder ──────────────────────────────────────────────────────
-- The existing assets table is accessed via service role only; mirror that for asset_readings.
ALTER TABLE public.asset_readings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS asset_readings_service_role ON public.asset_readings;
CREATE POLICY asset_readings_service_role ON public.asset_readings
  FOR ALL TO service_role USING (true) WITH CHECK (true);
