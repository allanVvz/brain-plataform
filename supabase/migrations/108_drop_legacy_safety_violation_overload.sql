-- Migration 103 (lead_handoff_level) added a 5-parameter overload of
-- record_whatsapp_safety_violation (p_level text DEFAULT 'full') via
-- CREATE OR REPLACE, which only replaces a function with an identical
-- signature. The pre-existing 4-parameter version was never dropped, so
-- both overloads coexisted: a 4-arg call (what api/services/supabase_client.py
-- has always sent) became ambiguous between the old exact-4-arg function and
-- the new 5-arg function used with its trailing default -- Postgres error
-- 42725 "is not unique" on every call.
--
-- This broke WhatsAppDispatchWorker on every cycle in production (confirmed
-- 2026-08-10: worker crash-looping, no outbound WhatsApp message delivered
-- platform-wide since migration 103 was applied). The 5-arg version is the
-- intended one (it has the handoff-level validation added by 103); drop the
-- superseded 4-arg overload.

DROP FUNCTION IF EXISTS public.record_whatsapp_safety_violation(uuid, bigint, text, text);
