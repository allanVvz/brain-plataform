-- 013_knowledge_rag_intake.sql
-- Database-first KB intake and RAG-ready knowledge layer.
-- Keeps legacy knowledge_items/kb_entries intact while adding canonical,
-- chunkable entries designed for retrieval and graph promotion.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.knowledge_intake_messages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id    UUID REFERENCES public.personas(id) ON DELETE SET NULL,
  source        TEXT NOT NULL DEFAULT 'manual',
  source_ref    TEXT,
  raw_text      TEXT NOT NULL,
  raw_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
  submitted_by  TEXT,
  status        TEXT NOT NULL DEFAULT 'received'
                CHECK (status IN (
                  'received',
                  'classified',
                  'rag_created',
                  'pending_validation',
                  'validated',
                  'rejected',
                  'duplicate',
                  'error'
                )),
  processed_at  TIMESTAMPTZ,
  error         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_intake_persona
  ON public.knowledge_intake_messages(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_intake_status
  ON public.knowledge_intake_messages(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_intake_created
  ON public.knowledge_intake_messages(created_at DESC);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_entries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  artifact_id     UUID,
  intake_id       UUID REFERENCES public.knowledge_intake_messages(id) ON DELETE SET NULL,

  content_type    TEXT NOT NULL CHECK (content_type IN (
                    'faq',
                    'product',
                    'brand',
                    'campaign',
                    'rule',
                    'tone',
                    'copy',
                    'briefing',
                    'asset',
                    'entity',
                    'general_note'
                  )),
  semantic_level  INT NOT NULL DEFAULT 50,

  title           TEXT NOT NULL,
  question        TEXT,
  answer          TEXT,
  content         TEXT NOT NULL,
  summary         TEXT,

  canonical_key   TEXT NOT NULL,
  slug            TEXT NOT NULL,

  language        TEXT NOT NULL DEFAULT 'pt-BR',
  status          TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN (
                    'draft',
                    'pending_embedding',
                    'pending_validation',
                    'validated',
                    'active',
                    'rejected',
                    'duplicate',
                    'stale'
                  )),

  tags            TEXT[] NOT NULL DEFAULT '{}',
  entities        TEXT[] NOT NULL DEFAULT '{}',
  products        TEXT[] NOT NULL DEFAULT '{}',
  campaigns       TEXT[] NOT NULL DEFAULT '{}',
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

  embedding       vector(1536),
  embedding_model TEXT,
  embedded_at     TIMESTAMPTZ,

  confidence      NUMERIC NOT NULL DEFAULT 0.5,
  importance      NUMERIC NOT NULL DEFAULT 0.5,

  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  validated_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_rag_entries_persona_key
  ON public.knowledge_rag_entries(persona_id, canonical_key);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_persona
  ON public.knowledge_rag_entries(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_type
  ON public.knowledge_rag_entries(content_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_status
  ON public.knowledge_rag_entries(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_slug
  ON public.knowledge_rag_entries(slug);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_tags
  ON public.knowledge_rag_entries USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_products
  ON public.knowledge_rag_entries USING GIN(products);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_entries_campaigns
  ON public.knowledge_rag_entries USING GIN(campaigns);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_chunks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rag_entry_id    UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,

  chunk_index     INT NOT NULL,
  chunk_text      TEXT NOT NULL,
  chunk_summary   TEXT,

  embedding       vector(1536),
  embedding_model TEXT,
  embedded_at     TIMESTAMPTZ,

  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(rag_entry_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_chunks_entry
  ON public.knowledge_rag_chunks(rag_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_chunks_persona
  ON public.knowledge_rag_chunks(persona_id);


CREATE TABLE IF NOT EXISTS public.knowledge_rag_links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id      UUID NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  source_entry_id UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  target_entry_id UUID NOT NULL REFERENCES public.knowledge_rag_entries(id) ON DELETE CASCADE,
  relation_type   TEXT NOT NULL,
  weight          NUMERIC NOT NULL DEFAULT 1,
  confidence      NUMERIC NOT NULL DEFAULT 0.5,
  created_by      TEXT NOT NULL DEFAULT 'system',
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(source_entry_id, target_entry_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_persona
  ON public.knowledge_rag_links(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_source
  ON public.knowledge_rag_links(source_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_target
  ON public.knowledge_rag_links(target_entry_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_rag_links_relation
  ON public.knowledge_rag_links(relation_type);

COMMENT ON TABLE public.knowledge_intake_messages IS
  'Raw inbox for any knowledge submitted to the KB before classification.';
COMMENT ON TABLE public.knowledge_rag_entries IS
  'Canonical RAG-ready knowledge units scoped by persona and content type.';
COMMENT ON TABLE public.knowledge_rag_chunks IS
  'Embedding chunks for RAG entries. Short FAQs usually have one chunk.';
COMMENT ON TABLE public.knowledge_rag_links IS
  'Semantic hierarchy/relationship links between RAG entries.';
