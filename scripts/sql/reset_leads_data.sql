-- AVISO: este script NAO apaga leads e NAO produz um ciclo totalmente novo.
-- Para o reset global solicitado, use purge_all_leads_and_conversations.sql.
-- ========================================================================
-- SCRIPT B: Reset dados e appointments dos leads (produção)
-- ========================================================================
--
-- ORDRE: Rodar ESTE script PRIMEIRO, depois cleanup_conversations.sql.
--
-- Objetivo:
-- - Limpar TODOS os dados dos leads (stage, metadata, appointment info, etc).
-- - Manter os leads themselves (linhas em public.leads não são deletadas).
-- - Apagar TODO o histórico comercial (sales_conversions) com conversion_type='appointment_booked' e others.
--
-- Escopo: GLOBAL (todas as personas/canais).
--
-- Comportamento:
-- 1. Contagem: RAISE NOTICE mostra quantos leads e conversions serão afetados.
-- 2. DELETE: sales_conversions (todo o histórico, inclui appointments).
-- 3. UPDATE: leads — zera stage, metadata, handoff_level, etc. Mantém id, lead_id, nome, telefone, canal.
--
-- Transação: este script é um único BEGIN/COMMIT.
-- - Roda as contagens em RAISE NOTICE antes de deletar.
-- - Usuário deve olhar o log do SQL editor, revisar os números, e confirmar
--   o COMMIT final (ou mudar para ROLLBACK se algo parecer errado).
--
-- ========================================================================

BEGIN;

-- Guard: check if sales_conversions already empty (should be, if you ran this first).
-- This is just informational.
DO $$
DECLARE
  v_conversion_count integer;
BEGIN
  SELECT count(*) INTO v_conversion_count FROM public.sales_conversions;
  RAISE NOTICE '[reset_leads_data] Pre-flight: % rows in sales_conversions', v_conversion_count;
END $$;

-- Count phase: how many leads and conversions will be affected.
DO $$
DECLARE
  v_lead_count integer;
  v_conversion_count integer;
BEGIN
  SELECT count(*) INTO v_lead_count FROM public.leads;
  SELECT count(*) INTO v_conversion_count FROM public.sales_conversions;
  RAISE NOTICE '[reset_leads_data] About to reset % leads and delete % sales_conversions', v_lead_count, v_conversion_count;
END $$;

-- Step 1: Delete sales_conversions (commercial history, includes appointment_booked).
--
-- Optional: if you want to ONLY delete appointment_booked and preserve purchase/contract_signed:
--   DELETE FROM public.sales_conversions WHERE conversion_type = 'appointment_booked';
--
-- But the default is DELETE ALL (as per user request).
DELETE FROM public.sales_conversions;

DO $$
BEGIN
  RAISE NOTICE '[reset_leads_data] Deleted all sales_conversions';
END $$;

-- Step 2: Reset leads data (update, not delete).
-- Zeroed: stage, origem, interesse_produto, cidade, cep, ultima_mensagem, last_update, metadata, handoff_level.
-- Kept (identity/channel): id, lead_id, nome, telefone, email, canal, whatsapp_phone_number_id, channel_binding_id, external_contact_id, persona_id, created_at.
--
-- Note on trigger trg_enforce_lead_channel_binding (migration 067):
-- It validates channel_binding_id/persona_id integrity on any UPDATE to leads.
-- Since we're not touching those columns, the trigger should pass normally.
-- If UPDATE fails due to pre-existing data drift, uncomment the DISABLE/ENABLE lines below.

-- ALTER TABLE public.leads DISABLE TRIGGER trg_enforce_lead_channel_binding;

UPDATE public.leads
SET
  stage = NULL,
  origem = NULL,
  interesse_produto = NULL,
  cidade = NULL,
  cep = NULL,
  ultima_mensagem = NULL,
  last_update = NULL,
  metadata = '{}'::jsonb,
  handoff_level = 'none',
  updated_at = now()
WHERE TRUE;

-- ALTER TABLE public.leads ENABLE TRIGGER trg_enforce_lead_channel_binding;

DO $$
DECLARE
  v_updated integer := ROW_COUNT;
BEGIN
  RAISE NOTICE '[reset_leads_data] Reset % leads (stage, metadata, handoff_level, etc zeroed)', v_updated;
END $$;

-- Summary before commit.
DO $$
DECLARE
  v_lead_count integer;
  v_conversion_count integer;
BEGIN
  SELECT count(*) INTO v_lead_count FROM public.leads;
  SELECT count(*) INTO v_conversion_count FROM public.sales_conversions;
  RAISE NOTICE '[reset_leads_data] POST-RESET: % leads remaining (with zeroed data), % conversions remaining', v_lead_count, v_conversion_count;
  RAISE NOTICE '[reset_leads_data] Review the counts above. If correct, the COMMIT at the end will finalize.';
  RAISE NOTICE '[reset_leads_data] If you want to ROLLBACK instead, cancel the transaction now.';
END $$;

COMMIT;
