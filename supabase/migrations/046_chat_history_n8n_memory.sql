-- 046_chat_history_n8n_memory.sql
-- Local Docker: tabela de memoria conversacional usada pelo no "Postgres Chat
-- Memory" do n8n (fluxo "Tock Vitoria Crm Low" / agente Vitoria, tableName=chat_history).
-- Schema = LangChain PostgresChatMessageHistory (session_id + message jsonb).
-- Sem esta tabela o no de memoria do agente SDR falha na execucao.

CREATE TABLE IF NOT EXISTS public.chat_history (
  id         SERIAL PRIMARY KEY,
  session_id TEXT  NOT NULL,
  message    JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_history_session_id
  ON public.chat_history (session_id);
