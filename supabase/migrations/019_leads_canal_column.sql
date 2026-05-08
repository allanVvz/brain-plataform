-- ============================================================
-- Brain AI Platform - Migration 019
-- Adiciona coluna canal em leads (whatsapp, instagram, bulk_import, ...)
-- Necessario para o pipeline ensure_lead_for_persona escrever a origem
-- do canal atual sem perder o INSERT por coluna desconhecida.
-- ============================================================

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS canal text;

CREATE INDEX IF NOT EXISTS leads_canal_idx ON leads(canal);

-- Forca a invalidacao do schema cache do PostgREST para que o supabase-py
-- enxergue a nova coluna sem precisar reiniciar a instancia.
NOTIFY pgrst, 'reload schema';
