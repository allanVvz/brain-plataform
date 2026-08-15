-- 119_whatsapp_media_ingest.sql
-- Inbound WhatsApp media (image / audio / document) becomes a real asset.
--
-- Until now every imageMessage / audioMessage / documentMessage was dropped at
-- the provider normalizer, so a voice note asking for a price reached the
-- operator as "[mensagem sem texto]" and the agent as an empty string.
--
-- Three things are needed to fix that durably:
--   1. A PRIVATE bucket. assets-raw is public (033_asset_upload_pipeline.sql),
--      which is fine for marketing material but not for a customer's photo or
--      voice note — a public object URL bypasses authentication entirely.
--   2. Room in the assets/asset_readings CHECK constraints for the new
--      upload context, the audio type and the transcription reading.
--   3. Conversation provenance on the asset itself, so a received file can be
--      traced back to the lead, the message and the campaign that started the
--      conversation.

-- ── Private storage bucket ───────────────────────────────────────────────
-- public = false: reachable only through an authenticated, persona-scoped
-- route. ON CONFLICT keeps this idempotent and self-healing on re-apply,
-- matching the pattern in 033.
INSERT INTO storage.buckets (id, name, public)
VALUES ('whatsapp-media', 'whatsapp-media', false)
ON CONFLICT (id) DO UPDATE SET public = EXCLUDED.public;

-- ── public.assets — accept inbound WhatsApp media ────────────────────────
-- upload_context gains 'whatsapp_inbound'
-- (was: sofia_chat | create_sidebar | asset_card | imported).
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_upload_context_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_upload_context_check
  CHECK (upload_context IS NULL OR upload_context IN (
    'sofia_chat','create_sidebar','asset_card','imported','whatsapp_inbound'
  ));

-- type gains 'audio' (was: image|video|pdf|text|copy|campaign|template).
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_type_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_type_check
  CHECK (type IS NULL OR type IN (
    'image','video','audio','pdf','text','copy','campaign','template'
  ));

-- source gains 'whatsapp' so an inbound file is never confused with an
-- operator upload (was: maker|manual|mcp|imported|upload).
ALTER TABLE public.assets
  DROP CONSTRAINT IF EXISTS assets_source_check;
ALTER TABLE public.assets
  ADD CONSTRAINT assets_source_check
  CHECK (source IN ('maker','manual','mcp','imported','upload','whatsapp'));

-- ── Conversation provenance ──────────────────────────────────────────────
-- All nullable: an asset_card upload has no conversation, and an inbound file
-- from a lead outside any campaign has no campaign. ON DELETE SET NULL keeps
-- the asset (and its storage object) alive when a campaign is removed.
--
-- Note on campaign attribution: messages.campaign_id cannot carry this for
-- inbound, because messages_campaign_scope_check (087) requires
-- direction='outbound'. The campaign is resolved through
-- campaign_recipients and denormalized here so the Assets view can filter by
-- campaign without walking the recipient table.
ALTER TABLE public.assets
  ADD COLUMN IF NOT EXISTS lead_id               bigint REFERENCES public.leads(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS message_id            bigint REFERENCES public.messages(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS campaign_id           uuid   REFERENCES public.campaigns(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS campaign_recipient_id uuid   REFERENCES public.campaign_recipients(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.assets.lead_id IS
  'Lead that sent this file over WhatsApp. NULL for operator/Sofia uploads.';
COMMENT ON COLUMN public.assets.campaign_id IS
  'Campaign that originated the conversation, resolved via campaign_recipients at ingest.';

-- Drives the media rail in Mensagens (all files for one lead, newest first).
CREATE INDEX IF NOT EXISTS idx_assets_persona_lead
  ON public.assets(persona_id, lead_id, created_at DESC)
  WHERE lead_id IS NOT NULL;

-- Drives the "WhatsApp" tab in Assets and the campaign filter.
CREATE INDEX IF NOT EXISTS idx_assets_campaign
  ON public.assets(campaign_id, created_at DESC)
  WHERE campaign_id IS NOT NULL;

-- One asset per inbound message: the media ingest worker is at-least-once, so
-- a retry must land on the same row instead of duplicating the file.
CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_inbound_message
  ON public.assets(message_id)
  WHERE message_id IS NOT NULL AND upload_context = 'whatsapp_inbound';

-- ── public.asset_readings — transcription output ─────────────────────────
-- reading_type gains 'transcription' for faster-whisper output
-- (was: classification|ocr|ai_fallback|pdf_text|video_mock|rename).
ALTER TABLE public.asset_readings
  DROP CONSTRAINT IF EXISTS asset_readings_reading_type_check;
ALTER TABLE public.asset_readings
  ADD CONSTRAINT asset_readings_reading_type_check
  CHECK (reading_type IN (
    'classification','ocr','ai_fallback','pdf_text','video_mock','rename','transcription'
  ));

-- ── resolve_media_buffer ─────────────────────────────────────────────────
-- Called by the media ingest worker once the file has been read, to swap the
-- placeholder text for the real descriptor and release the dispatch hold.
--
-- This must be one statement, not a read-modify-write from Python: the quiet
-- burst supersession in 113 aggregates sibling rows with
-- string_agg(payload->>'text'), so a racing merge could read the placeholder
-- and permanently lose the transcription.
--
-- Idempotent by design: the worker is at-least-once, and a second call with
-- the same text is a no-op that still reports success.
CREATE OR REPLACE FUNCTION public.resolve_media_buffer(
  p_buffer_id uuid,
  p_text text,
  p_reading_status text DEFAULT 'completed',
  p_debounce_seconds integer DEFAULT 3
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_buffer public.lead_buffer%ROWTYPE;
  v_text text := COALESCE(NULLIF(btrim(p_text), ''), '[midia recebida]');
BEGIN
  IF p_reading_status NOT IN ('completed', 'partial', 'failed') THEN
    RAISE EXCEPTION 'unsupported media reading status: %', p_reading_status;
  END IF;

  SELECT * INTO v_buffer
    FROM public.lead_buffer
   WHERE id = p_buffer_id
   FOR UPDATE;

  IF v_buffer.id IS NULL THEN
    RETURN jsonb_build_object('resolved', false, 'reason', 'buffer_not_found');
  END IF;

  -- Already dispatched (the hold expired and it went out with the fallback):
  -- still record the reading on the message so the operator sees the real
  -- transcription, but never rewind the buffer.
  IF v_buffer.status <> 'buffered' THEN
    UPDATE public.messages
       SET content = v_text,
           metadata = COALESCE(metadata, '{}'::jsonb)
                      || jsonb_build_object('media_reading_status', p_reading_status,
                                            'media_resolved_late', true)
     WHERE channel_binding_id = v_buffer.channel_binding_id
       AND direction = v_buffer.direction
       AND external_message_id = v_buffer.external_message_id;
    RETURN jsonb_build_object('resolved', false, 'reason', 'already_dispatched',
                              'status', v_buffer.status);
  END IF;

  UPDATE public.lead_buffer
     SET payload = jsonb_set(
                     jsonb_set(COALESCE(payload, '{}'::jsonb), '{text}', to_jsonb(v_text), true),
                     '{media,reading_status}', to_jsonb(p_reading_status), true
                   ),
         available_at = now() + make_interval(secs => GREATEST(p_debounce_seconds, 0))
   WHERE id = p_buffer_id;

  -- Keep the projected message in step, so the CRM thread and the agent read
  -- the same string.
  UPDATE public.messages
     SET content = v_text,
         metadata = COALESCE(metadata, '{}'::jsonb)
                    || jsonb_build_object('media_reading_status', p_reading_status)
   WHERE channel_binding_id = v_buffer.channel_binding_id
     AND direction = v_buffer.direction
     AND external_message_id = v_buffer.external_message_id;

  RETURN jsonb_build_object('resolved', true, 'buffer_id', p_buffer_id,
                            'reading_status', p_reading_status);
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_media_buffer(uuid, text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.resolve_media_buffer(uuid, text, text, integer) TO service_role;
