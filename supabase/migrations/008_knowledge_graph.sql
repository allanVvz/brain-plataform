-- 008_knowledge_graph.sql
-- Semantic knowledge graph: nodes (entities) + edges (relations).
-- Aditive: nada existente é alterado. Tabelas atuais
--   (knowledge_items, kb_entries, knowledge_sources, sync_runs, sync_logs)
--   continuam intactas. Caso essas tabelas estejam vazias o sistema antigo
--   funciona normalmente.
-- Safe to run multiple times.

-- pg_trgm é usado para o índice de busca por similaridade no título.
-- Se a extensão não estiver disponível, o CREATE EXTENSION falha silenciosamente
-- via DO block; o índice trgm é depois tornado opcional.
DO $$
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
  EXCEPTION WHEN OTHERS THEN
    -- ignorar; busca cai pra ILIKE simples
    NULL;
  END;
END$$;

-- ── 1. knowledge_nodes ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.knowledge_nodes (
  id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id    UUID                  REFERENCES public.personas(id) ON DELETE CASCADE,
  source_table  TEXT,                                       -- 'knowledge_items' | 'kb_entries' | NULL
  source_id     UUID,                                       -- linha original (quando aplicável)
  node_type     TEXT         NOT NULL,                      -- persona | product | campaign | faq | copy | asset | rule | tone | audience | tag | kb_entry | knowledge_item
  slug          TEXT         NOT NULL,
  title         TEXT         NOT NULL,
  summary       TEXT,
  tags          TEXT[]       NOT NULL DEFAULT '{}',
  metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- asset_type, asset_function, file_path, etc.
  status        TEXT         NOT NULL DEFAULT 'active',
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Unique por (persona_id, node_type, slug). NULL persona_id é permitido como "global".
-- Usamos COALESCE para tratar NULL corretamente no UNIQUE INDEX.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_nodes_persona_type_slug
  ON public.knowledge_nodes (COALESCE(persona_id::text, ''), node_type, slug);

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_persona  ON public.knowledge_nodes (persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_type     ON public.knowledge_nodes (node_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_status   ON public.knowledge_nodes (status);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_tags     ON public.knowledge_nodes USING GIN (tags);

-- Trgm é ótimo, mas opcional — só cria se a extensão existir.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_title_trgm
             ON public.knowledge_nodes USING GIN (title gin_trgm_ops)';
  END IF;
END$$;

-- ── 2. knowledge_edges ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.knowledge_edges (
  id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID                  REFERENCES public.personas(id) ON DELETE CASCADE,
  source_node_id  UUID         NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,
  target_node_id  UUID         NOT NULL REFERENCES public.knowledge_nodes(id) ON DELETE CASCADE,
  relation_type   TEXT         NOT NULL, -- belongs_to_persona | about_product | part_of_campaign | supports_campaign | uses_asset | answers_question | supports_copy | has_tag | same_topic_as | visible_to_agent | mentions
  weight          NUMERIC      NOT NULL DEFAULT 1,
  metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_edges_triple
  ON public.knowledge_edges (source_node_id, target_node_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source   ON public.knowledge_edges (source_node_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_target   ON public.knowledge_edges (target_node_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_relation ON public.knowledge_edges (relation_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_persona  ON public.knowledge_edges (persona_id);
