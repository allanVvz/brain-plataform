-- AVISO: este script NAO apaga leads nem nodes conversation do grafo.
-- Para o reset global solicitado, use purge_all_leads_and_conversations.sql.
-- ========================================================================
-- SCRIPT A: Cleanup todas as conversas (global, produção)
-- ========================================================================
--
-- ORDEM: Rodar ESTE script SEGUNDO (depois de reset_leads_data.sql).
--
-- Objetivo:
-- - Apagar TODO o histórico de conversa e estado de runtime do agente v3.
-- - Limpar: messages, chat_history, lead_buffer, conversation_ledgers, conversation_facts,
--   conversation_turn_proofs, conversation_ledger_branches, conversation_journeys.
--
-- Escopo: GLOBAL (todas as personas/canais).
--
-- Comportamento:
-- 1. Guard: verifica se sales_conversions está vazio (se não, erro).
-- 2. Contagem: RAISE NOTICE mostra quantas linhas serão deletadas em cada tabela.
-- 3. DELETE: ordem que respeita FK constraints (baseado no padrão de cleanup_wa_validator_artifacts).
--
-- Transação: este script é um único BEGIN/COMMIT.
-- - Usuário deve olhar o log do SQL editor, revisar os números, e confirmar
--   o COMMIT final (ou mudar para ROLLBACK se algo parecer errado).
--
-- ========================================================================

BEGIN;

-- Guard: ensure sales_conversions is empty before proceeding.
-- If it's not empty, the FK constraint will block deletion of conversation_journeys.
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count FROM public.sales_conversions;
  IF v_count > 0 THEN
    RAISE EXCEPTION 'cleanup_conversations: ABORT. sales_conversions still has % rows. Run reset_leads_data.sql first.', v_count;
  END IF;
  RAISE NOTICE '[cleanup_conversations] Guard passed: sales_conversions is empty';
END $$;

-- Count phase: how many rows in each conversation table will be deleted.
DO $$
DECLARE
  v_messages_count integer;
  v_turn_proofs_count integer;
  v_facts_count integer;
  v_branches_count integer;
  v_ledgers_count integer;
  v_journeys_count integer;
  v_buffer_count integer;
  v_chat_history_count integer;
BEGIN
  SELECT count(*) INTO v_messages_count FROM public.messages;
  SELECT count(*) INTO v_turn_proofs_count FROM public.conversation_turn_proofs;
  SELECT count(*) INTO v_facts_count FROM public.conversation_facts;
  SELECT count(*) INTO v_branches_count FROM public.conversation_ledger_branches;
  SELECT count(*) INTO v_ledgers_count FROM public.conversation_ledgers;
  SELECT count(*) INTO v_journeys_count FROM public.conversation_journeys;
  SELECT count(*) INTO v_buffer_count FROM public.lead_buffer;
  SELECT count(*) INTO v_chat_history_count FROM public.chat_history;

  RAISE NOTICE '[cleanup_conversations] About to delete:';
  RAISE NOTICE '  - conversation_turn_proofs: %', v_turn_proofs_count;
  RAISE NOTICE '  - conversation_facts: %', v_facts_count;
  RAISE NOTICE '  - conversation_ledger_branches: %', v_branches_count;
  RAISE NOTICE '  - conversation_ledgers: %', v_ledgers_count;
  RAISE NOTICE '  - conversation_journeys: %', v_journeys_count;
  RAISE NOTICE '  - chat_history: %', v_chat_history_count;
  RAISE NOTICE '  - lead_buffer: %', v_buffer_count;
  RAISE NOTICE '  - messages: %', v_messages_count;
END $$;

-- Delete phase, in FK dependency order (reversed from insert order).
-- Pattern based on cleanup_wa_validator_artifacts (migration 117).

DELETE FROM public.conversation_turn_proofs;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted conversation_turn_proofs';
END $$;

DELETE FROM public.conversation_facts;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted conversation_facts';
END $$;

DELETE FROM public.conversation_ledger_branches;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted conversation_ledger_branches';
END $$;

DELETE FROM public.conversation_ledgers;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted conversation_ledgers';
END $$;

DELETE FROM public.conversation_journeys;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted conversation_journeys';
END $$;

-- chat_history: no explicit FK to leads declared, but it's runtime chat data.
-- Safe to delete globally.
DELETE FROM public.chat_history;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted chat_history';
END $$;

-- lead_buffer: runtime queue for WhatsApp inbound/outbound.
-- Has FK lead_ref -> leads(id) ON DELETE SET NULL, so safe to delete.
DELETE FROM public.lead_buffer;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted lead_buffer';
END $$;

-- messages: the raw chat log.
-- Has FK lead_id -> leads(id) ON DELETE CASCADE.
DELETE FROM public.messages;
DO $$
BEGIN
  RAISE NOTICE '[cleanup_conversations] Deleted messages';
END $$;

-- Optional: audit log cleanup.
-- Uncomment the next block if you also want to clear system_events.
-- Otherwise, system_events (audit trail) is preserved.
--
-- DO $$
-- BEGIN
--   DELETE FROM public.system_events;
--   RAISE NOTICE '[cleanup_conversations] Deleted system_events (audit trail)';
-- END $$;

-- Summary before commit.
DO $$
DECLARE
  v_messages_count integer;
  v_ledgers_count integer;
  v_journeys_count integer;
BEGIN
  SELECT count(*) INTO v_messages_count FROM public.messages;
  SELECT count(*) INTO v_ledgers_count FROM public.conversation_ledgers;
  SELECT count(*) INTO v_journeys_count FROM public.conversation_journeys;

  RAISE NOTICE '[cleanup_conversations] POST-CLEANUP:';
  RAISE NOTICE '  - messages remaining: %', v_messages_count;
  RAISE NOTICE '  - conversation_ledgers remaining: %', v_ledgers_count;
  RAISE NOTICE '  - conversation_journeys remaining: %', v_journeys_count;
  RAISE NOTICE '[cleanup_conversations] Review the counts above. If correct, the COMMIT at the end will finalize.';
  RAISE NOTICE '[cleanup_conversations] If you want to ROLLBACK instead, cancel the transaction now.';
END $$;

COMMIT;
