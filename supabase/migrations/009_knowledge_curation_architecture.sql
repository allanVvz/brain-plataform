-- 009_knowledge_curation_architecture.sql
-- Canonical knowledge curation layer.
--
-- Goal:
--   Connect Git/vault files, intake queue rows, KB rows and semantic graph nodes
--   through one stable artifact identity. This prevents duplicate knowledge from
--   becoming separate "truths" and gives the KB Classifier/Curator a place to
--   propose merges, node hierarchy, importance and graph relations before apply.
--
-- Safe to run multiple times. Existing tables remain the source of operational
-- compatibility; this migration adds lineage and curation structure around them.

-- ── 1. Configurable ontology ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_node_type_registry (
  node_type           TEXT PRIMARY KEY,
  label               TEXT NOT NULL,
  description         TEXT,
  default_level       INT NOT NULL DEFAULT 50,
  default_importance  NUMERIC NOT NULL DEFAULT 0.50 CHECK (default_importance >= 0 AND default_importance <= 1),
  color               TEXT,
  icon                TEXT,
  config              JSONB NOT NULL DEFAULT '{}'::jsonb,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order          INT NOT NULL DEFAULT 100,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('entity',    'Entidade',  'Cliente, organização, pessoa, lugar ou conceito nomeado.', 10, 0.95, '#7c6fff', 'network',       10),
  ('brand',     'Brand',     'Identidade, posicionamento e atributos de marca.',         20, 0.90, '#a78bfa', 'badge',         20),
  ('campaign',  'Campanha',  'Ação comercial ou comunicação com objetivo próprio.',      30, 0.80, '#fb923c', 'megaphone',     30),
  ('product',   'Produto',   'Produto, categoria, coleção ou oferta.',                   40, 0.85, '#60a5fa', 'box',           40),
  ('briefing',  'Briefing',  'Contexto, estratégia, requisitos e instruções.',           50, 0.75, '#c084fc', 'file-text',      50),
  ('tone',      'Tom',       'Voz, estilo, vocabulário e restrições de linguagem.',       60, 0.70, '#22d3ee', 'palette',       60),
  ('copy',      'Copy',      'Texto reutilizável para mensagens, posts ou anúncios.',     70, 0.65, '#64748b', 'text',          70),
  ('faq',       'FAQ',       'Pergunta e resposta operacional.',                          75, 0.65, '#4ade80', 'circle-help',   75),
  ('asset',     'Asset',     'Arquivo visual, vídeo, logo, template ou material maker.',  80, 0.55, '#f59e0b', 'image',         80),
  ('rule',      'Regra',     'Política ou regra executável por agente.',                  65, 0.80, '#f87171', 'scale',         65),
  ('audience',  'Audiência', 'Público-alvo, persona compradora ou segmento.',             55, 0.70, '#f472b6', 'users',         55),
  ('persona',   'Persona',   'Raiz de escopo do cliente/persona no sistema.',              0, 1.00, '#7c6fff', 'user',           0),
  ('tag',       'Tag',       'Marcador auxiliar, não deve ser fonte primária de verdade.', 90, 0.30, '#94a3b8', 'tag',           90),
  ('knowledge_item', 'Fila', 'Espelho técnico de knowledge_items.',                       95, 0.40, '#94a3b8', 'inbox',         95),
  ('kb_entry',  'KB Entry',  'Espelho técnico de kb_entries.',                            95, 0.50, '#94a3b8', 'database',      96)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();

CREATE TABLE IF NOT EXISTS public.knowledge_relation_type_registry (
  relation_type       TEXT PRIMARY KEY,
  label               TEXT NOT NULL,
  inverse_label       TEXT,
  source_node_types   TEXT[] NOT NULL DEFAULT '{}',
  target_node_types   TEXT[] NOT NULL DEFAULT '{}',
  default_weight      NUMERIC NOT NULL DEFAULT 1 CHECK (default_weight >= 0),
  directional         BOOLEAN NOT NULL DEFAULT TRUE,
  config              JSONB NOT NULL DEFAULT '{}'::jsonb,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order          INT NOT NULL DEFAULT 100,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order)
VALUES
  ('belongs_to_persona', 'pertence à persona', 'possui', '{}', '{"persona"}', 1.00, TRUE, 10),
  ('defines_brand',      'define brand',       'é definido por', '{"briefing","rule","tone"}', '{"brand"}', 0.90, TRUE, 20),
  ('has_tone',           'usa tom',            'tom de', '{"brand","campaign","product","copy"}', '{"tone"}', 0.80, TRUE, 30),
  ('about_product',      'sobre produto',      'tem conhecimento', '{}', '{"product"}', 0.85, TRUE, 40),
  ('part_of_campaign',   'parte da campanha',  'contém', '{"product","copy","asset","faq","briefing"}', '{"campaign"}', 0.75, TRUE, 50),
  ('answers_question',   'responde pergunta',  'é respondido por', '{"faq","kb_entry"}', '{"product","campaign","brand","entity"}', 0.80, TRUE, 60),
  ('supports_copy',      'suporta copy',       'é suportado por', '{"copy"}', '{"product","campaign","brand"}', 0.70, TRUE, 70),
  ('uses_asset',         'usa asset',          'é usado por', '{"product","campaign","copy","brand"}', '{"asset"}', 0.65, TRUE, 80),
  ('briefed_by',         'briefado por',       'briefa', '{"product","campaign","copy","asset"}', '{"briefing"}', 0.70, TRUE, 90),
  ('same_topic_as',      'mesmo tópico',       'mesmo tópico', '{}', '{}', 0.45, FALSE, 100),
  ('duplicate_of',       'duplicado de',       'tem duplicado', '{}', '{}', 1.00, TRUE, 110),
  ('derived_from',       'derivado de',        'origina', '{}', '{}', 0.90, TRUE, 120),
  ('contains',           'contém',             'contido em', '{}', '{}', 0.75, TRUE, 130)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();

-- ── 2. Canonical artifact layer ───────────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_artifacts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id            UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  canonical_key         TEXT NOT NULL,
  canonical_hash        TEXT NOT NULL,
  title                 TEXT NOT NULL,
  content_type          TEXT NOT NULL,
  summary               TEXT,
  curation_status       TEXT NOT NULL DEFAULT 'pending'
                        CHECK (curation_status IN ('pending','proposed','validated','rejected','stale','duplicate')),
  importance            NUMERIC NOT NULL DEFAULT 0.50 CHECK (importance >= 0 AND importance <= 1),
  level                 INT NOT NULL DEFAULT 50,
  confidence            NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  duplicate_of          UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  current_knowledge_item_id UUID REFERENCES public.knowledge_items(id) ON DELETE SET NULL,
  current_kb_entry_id       UUID REFERENCES public.kb_entries(id) ON DELETE SET NULL,
  vault_file_path       TEXT,
  source_uri            TEXT,
  git_remote_url        TEXT,
  git_branch            TEXT,
  git_commit_sha        TEXT,
  content_hash          TEXT,
  classifier_agent_id   UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_artifacts_persona_hash
  ON public.knowledge_artifacts (COALESCE(persona_id::text, ''), canonical_hash);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_persona ON public.knowledge_artifacts(persona_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_type ON public.knowledge_artifacts(content_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_status ON public.knowledge_artifacts(curation_status);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_importance ON public.knowledge_artifacts(importance DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_duplicate_of ON public.knowledge_artifacts(duplicate_of);

CREATE TABLE IF NOT EXISTS public.knowledge_artifact_versions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id       UUID NOT NULL REFERENCES public.knowledge_artifacts(id) ON DELETE CASCADE,
  version_no        INT NOT NULL,
  source_table      TEXT NOT NULL CHECK (source_table IN ('knowledge_items','kb_entries','manual','vault','classifier')),
  source_id         UUID,
  title             TEXT,
  content_type      TEXT,
  content_hash      TEXT,
  raw_content       TEXT,
  classification    JSONB NOT NULL DEFAULT '{}'::jsonb,
  vault_file_path   TEXT,
  git_commit_sha    TEXT,
  created_by_agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, version_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_artifact_versions_source
  ON public.knowledge_artifact_versions (source_table, source_id)
  WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_artifact_versions_artifact ON public.knowledge_artifact_versions(artifact_id);

-- ── 3. Classifier/curator prompts, skills and proposals ───────────

CREATE TABLE IF NOT EXISTS public.agent_prompt_profiles (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_role     TEXT NOT NULL,
  name           TEXT NOT NULL,
  version        TEXT NOT NULL DEFAULT 'v1',
  system_prompt  TEXT NOT NULL,
  tools          TEXT[] NOT NULL DEFAULT '{}',
  skills         TEXT[] NOT NULL DEFAULT '{}',
  config         JSONB NOT NULL DEFAULT '{}'::jsonb,
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (agent_role, name, version)
);

INSERT INTO public.agent_prompt_profiles
  (agent_role, name, version, system_prompt, tools, skills, config)
VALUES
  (
    'classifier',
    'kb-classifier-curator',
    'v1',
    'Voce e o KB Classifier/Curator. Classifique conhecimento, detecte duplicatas, proponha artifact canonical_key, node_type, relacoes, importancia, nivel, confianca e acao de curadoria. Nunca aplique mutacoes destrutivas sem proposta auditavel.',
    '{"vault_write","git_add_commit_push","vault_sync","graph_bootstrap","duplicate_lookup"}',
    '{"classification","curation","deduplication","graph_modeling"}',
    '{"max_questions":2,"proposal_required":true,"duplicate_policy":"propose_merge"}'::jsonb
  )
ON CONFLICT (agent_role, name, version) DO UPDATE SET
  system_prompt = EXCLUDED.system_prompt,
  tools = EXCLUDED.tools,
  skills = EXCLUDED.skills,
  config = EXCLUDED.config,
  updated_at = now();

CREATE TABLE IF NOT EXISTS public.knowledge_curation_runs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id       UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  agent_id         UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  prompt_profile_id UUID REFERENCES public.agent_prompt_profiles(id) ON DELETE SET NULL,
  mode             TEXT NOT NULL DEFAULT 'dry_run'
                   CHECK (mode IN ('dry_run','apply','intake','reprocess')),
  status           TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','completed','failed','cancelled')),
  input_scope      JSONB NOT NULL DEFAULT '{}'::jsonb,
  stats            JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message    TEXT,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_curation_runs_persona ON public.knowledge_curation_runs(persona_id);
CREATE INDEX IF NOT EXISTS idx_curation_runs_status ON public.knowledge_curation_runs(status);

CREATE TABLE IF NOT EXISTS public.knowledge_curation_proposals (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            UUID REFERENCES public.knowledge_curation_runs(id) ON DELETE SET NULL,
  persona_id        UUID REFERENCES public.personas(id) ON DELETE CASCADE,
  artifact_id       UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  proposal_type     TEXT NOT NULL CHECK (proposal_type IN (
                       'create_artifact','update_artifact','create_node','update_node',
                       'create_edge','update_edge','merge_duplicate','reclassify',
                       'validate','reject','stale'
                     )),
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','applied','rejected','superseded','failed')),
  target_table      TEXT,
  target_id         UUID,
  duplicate_of_artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  confidence        NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  priority          INT NOT NULL DEFAULT 50,
  rationale         TEXT,
  source_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
  proposed_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
  applied_at        TIMESTAMPTZ,
  created_by_agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
  reviewed_by       TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_curation_proposals_status ON public.knowledge_curation_proposals(status);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_artifact ON public.knowledge_curation_proposals(artifact_id);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_persona ON public.knowledge_curation_proposals(persona_id);
CREATE INDEX IF NOT EXISTS idx_curation_proposals_type ON public.knowledge_curation_proposals(proposal_type);

-- ── 4. Attach existing operational tables to artifacts ────────────

ALTER TABLE public.knowledge_items
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS canonical_hash TEXT,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS git_commit_sha TEXT,
  ADD COLUMN IF NOT EXISTS curation_status TEXT DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

ALTER TABLE public.kb_entries
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS canonical_hash TEXT,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS curation_status TEXT DEFAULT 'validated',
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

ALTER TABLE public.knowledge_nodes
  ADD COLUMN IF NOT EXISTS artifact_id UUID REFERENCES public.knowledge_artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS importance NUMERIC CHECK (importance IS NULL OR (importance >= 0 AND importance <= 1)),
  ADD COLUMN IF NOT EXISTS level INT,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD COLUMN IF NOT EXISTS curation_proposal_id UUID REFERENCES public.knowledge_curation_proposals(id) ON DELETE SET NULL;

ALTER TABLE public.knowledge_edges
  ADD COLUMN IF NOT EXISTS confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD COLUMN IF NOT EXISTS curation_proposal_id UUID REFERENCES public.knowledge_curation_proposals(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_items_artifact ON public.knowledge_items(artifact_id);
CREATE INDEX IF NOT EXISTS idx_kb_entries_artifact ON public.kb_entries(artifact_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_artifact ON public.knowledge_nodes(artifact_id);

-- ── 5. Backfill canonical artifact records ────────────────────────
-- Canonical hash intentionally ignores content so repeated saves of the same
-- concept converge into one artifact. content_hash tracks version changes.

WITH ki_src AS (
  SELECT DISTINCT ON (
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    ki.*,
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash,
    concat_ws(':', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))) AS computed_canonical_key
  FROM public.knowledge_items ki
  ORDER BY
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE ki.status WHEN 'embedded' THEN 1 WHEN 'approved' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
    ki.updated_at DESC NULLS LAST,
    ki.created_at DESC NULLS LAST
)
INSERT INTO public.knowledge_artifacts (
  persona_id, canonical_key, canonical_hash, title, content_type, summary,
  curation_status, importance, level, confidence,
  current_knowledge_item_id, vault_file_path, content_hash, metadata,
  created_at, updated_at
)
SELECT
  ki.persona_id,
  ki.computed_canonical_key,
  ki.computed_canonical_hash,
  ki.title,
  ki.content_type,
  left(ki.content, 500),
  CASE
    WHEN ki.status IN ('approved','embedded') THEN 'validated'
    WHEN ki.status = 'rejected' THEN 'rejected'
    ELSE 'pending'
  END,
  COALESCE((ki.metadata->>'importance')::numeric, tr.default_importance, 0.50),
  COALESCE((ki.metadata->>'level')::int, tr.default_level, 50),
  NULL,
  ki.id,
  ki.file_path,
  md5(COALESCE(ki.content, '')),
  jsonb_build_object('backfilled_from', 'knowledge_items', 'source_id', ki.source_id),
  ki.created_at,
  ki.updated_at
FROM ki_src ki
LEFT JOIN public.knowledge_node_type_registry tr ON tr.node_type = ki.content_type
ON CONFLICT DO NOTHING;

WITH ki_current AS (
  SELECT DISTINCT ON (
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    ki.*,
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash
  FROM public.knowledge_items ki
  ORDER BY
    COALESCE(ki.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE ki.status WHEN 'embedded' THEN 1 WHEN 'approved' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
    ki.updated_at DESC NULLS LAST,
    ki.created_at DESC NULLS LAST
)
UPDATE public.knowledge_artifacts a
SET
  current_knowledge_item_id = COALESCE(a.current_knowledge_item_id, ki.id),
  vault_file_path = COALESCE(a.vault_file_path, ki.file_path),
  content_hash = COALESCE(a.content_hash, md5(COALESCE(ki.content, ''))),
  updated_at = now()
FROM ki_current ki
WHERE a.canonical_hash = ki.computed_canonical_hash
  AND COALESCE(a.persona_id::text, '') = COALESCE(ki.persona_id::text, '')
  AND (
    a.current_knowledge_item_id IS NULL
    OR a.vault_file_path IS NULL
    OR a.content_hash IS NULL
  );

UPDATE public.knowledge_items ki
SET
  canonical_key = a.canonical_key,
  canonical_hash = a.canonical_hash,
  content_hash = md5(COALESCE(ki.content, '')),
  artifact_id = a.id,
  importance = COALESCE(ki.importance, a.importance),
  level = COALESCE(ki.level, a.level),
  curation_status = CASE
    WHEN ki.status IN ('approved','embedded') THEN 'validated'
    WHEN ki.status = 'rejected' THEN 'rejected'
    ELSE COALESCE(ki.curation_status, 'pending')
  END
FROM public.knowledge_artifacts a
WHERE a.canonical_hash = md5(concat_ws('|', COALESCE(ki.persona_id::text, 'global'), ki.content_type, lower(regexp_replace(ki.title, '[^a-zA-Z0-9]+', '-', 'g'))))
  AND COALESCE(a.persona_id::text, '') = COALESCE(ki.persona_id::text, '');

INSERT INTO public.knowledge_artifact_versions (
  artifact_id, version_no, source_table, source_id, title, content_type,
  content_hash, raw_content, classification, vault_file_path, git_commit_sha, created_at
)
SELECT
  ki.artifact_id,
  row_number() OVER (PARTITION BY ki.artifact_id ORDER BY ki.created_at, ki.id)::int,
  'knowledge_items',
  ki.id,
  ki.title,
  ki.content_type,
  ki.content_hash,
  ki.content,
  COALESCE(ki.metadata, '{}'::jsonb),
  ki.file_path,
  ki.git_commit_sha,
  ki.created_at
FROM public.knowledge_items ki
WHERE ki.artifact_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- Backfill KB entries as artifact links. Tipo is normalized only enough for
-- curation; the old tipo/categoria fields remain untouched.
WITH kb_norm AS (
  SELECT
    kb.*,
    CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
      WHEN 'produto' THEN 'product'
      WHEN 'campanha' THEN 'campaign'
      WHEN 'tom' THEN 'tone'
      WHEN 'regra' THEN 'rule'
      WHEN 'maker' THEN 'maker_material'
      WHEN 'geral' THEN 'other'
      ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
    END AS normalized_type
  FROM public.kb_entries kb
),
kb_src AS (
  SELECT DISTINCT ON (
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    kb.*,
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash,
    concat_ws(':', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))) AS computed_canonical_key
  FROM kb_norm kb
  ORDER BY
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE kb.status WHEN 'ATIVO' THEN 1 WHEN 'active' THEN 1 WHEN 'validated' THEN 1 ELSE 2 END,
    kb.updated_at DESC NULLS LAST,
    kb.created_at DESC NULLS LAST
)
INSERT INTO public.knowledge_artifacts (
  persona_id, canonical_key, canonical_hash, title, content_type, summary,
  curation_status, importance, level, confidence,
  current_kb_entry_id, source_uri, content_hash, metadata,
  created_at, updated_at
)
SELECT
  kb.persona_id,
  kb.computed_canonical_key,
  kb.computed_canonical_hash,
  kb.titulo,
  kb.normalized_type,
  left(kb.conteudo, 500),
  CASE WHEN kb.status IN ('ATIVO','active','validated') THEN 'validated' ELSE 'pending' END,
  COALESCE(kb.prioridade, 99)::numeric / 100.0,
  COALESCE(tr.default_level, 50),
  NULL,
  kb.id,
  kb.link,
  md5(COALESCE(kb.conteudo, '')),
  jsonb_build_object('backfilled_from', 'kb_entries', 'kb_id', kb.kb_id, 'tipo', kb.tipo, 'categoria', kb.categoria),
  kb.created_at,
  kb.updated_at
FROM kb_src kb
LEFT JOIN public.knowledge_node_type_registry tr ON tr.node_type = kb.normalized_type
ON CONFLICT DO NOTHING;

WITH kb_current AS (
  SELECT DISTINCT ON (
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
  )
    kb.*,
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))) AS computed_canonical_hash
  FROM (
    SELECT
      kb.*,
      CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
        WHEN 'produto' THEN 'product'
        WHEN 'campanha' THEN 'campaign'
        WHEN 'tom' THEN 'tone'
        WHEN 'regra' THEN 'rule'
        WHEN 'maker' THEN 'maker_material'
        WHEN 'geral' THEN 'other'
        ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
      END AS normalized_type
    FROM public.kb_entries kb
  ) kb
  ORDER BY
    COALESCE(kb.persona_id::text, ''),
    md5(concat_ws('|', COALESCE(kb.persona_id::text, 'global'), kb.normalized_type, lower(regexp_replace(kb.titulo, '[^a-zA-Z0-9]+', '-', 'g')))),
    CASE kb.status WHEN 'ATIVO' THEN 1 WHEN 'active' THEN 1 WHEN 'validated' THEN 1 ELSE 2 END,
    kb.updated_at DESC NULLS LAST,
    kb.created_at DESC NULLS LAST
)
UPDATE public.knowledge_artifacts a
SET
  current_kb_entry_id = COALESCE(a.current_kb_entry_id, kb.id),
  source_uri = COALESCE(a.source_uri, kb.link),
  content_hash = COALESCE(a.content_hash, md5(COALESCE(kb.conteudo, ''))),
  updated_at = now()
FROM kb_current kb
WHERE a.canonical_hash = kb.computed_canonical_hash
  AND COALESCE(a.persona_id::text, '') = COALESCE(kb.persona_id::text, '')
  AND (
    a.current_kb_entry_id IS NULL
    OR a.source_uri IS NULL
    OR a.content_hash IS NULL
  );

WITH kb_norm AS (
  SELECT
    kb.*,
    CASE lower(COALESCE(kb.tipo, kb.categoria, 'geral'))
      WHEN 'produto' THEN 'product'
      WHEN 'campanha' THEN 'campaign'
      WHEN 'tom' THEN 'tone'
      WHEN 'regra' THEN 'rule'
      WHEN 'maker' THEN 'maker_material'
      WHEN 'geral' THEN 'other'
      ELSE lower(COALESCE(kb.tipo, kb.categoria, 'other'))
    END AS normalized_type
  FROM public.kb_entries kb
)
UPDATE public.kb_entries kb
SET
  canonical_key = a.canonical_key,
  canonical_hash = a.canonical_hash,
  content_hash = md5(COALESCE(kb.conteudo, '')),
  artifact_id = a.id,
  importance = COALESCE(kb.importance, a.importance),
  level = COALESCE(kb.level, a.level),
  curation_status = CASE WHEN kb.status IN ('ATIVO','active','validated') THEN 'validated' ELSE COALESCE(kb.curation_status, 'pending') END
FROM kb_norm n
JOIN public.knowledge_artifacts a
  ON a.canonical_hash = md5(concat_ws('|', COALESCE(n.persona_id::text, 'global'), n.normalized_type, lower(regexp_replace(n.titulo, '[^a-zA-Z0-9]+', '-', 'g'))))
 AND COALESCE(a.persona_id::text, '') = COALESCE(n.persona_id::text, '')
WHERE kb.id = n.id;

INSERT INTO public.knowledge_artifact_versions (
  artifact_id, version_no, source_table, source_id, title, content_type,
  content_hash, raw_content, classification, vault_file_path, created_at
)
SELECT
  kb.artifact_id,
  COALESCE(existing.max_version_no, 0)
    + row_number() OVER (PARTITION BY kb.artifact_id ORDER BY kb.created_at, kb.id)::int,
  'kb_entries',
  kb.id,
  kb.titulo,
  COALESCE(kb.categoria, kb.tipo, 'other'),
  kb.content_hash,
  kb.conteudo,
  jsonb_build_object('kb_id', kb.kb_id, 'tipo', kb.tipo, 'categoria', kb.categoria, 'produto', kb.produto, 'tags', kb.tags),
  kb.link,
  kb.created_at
FROM public.kb_entries kb
LEFT JOIN (
  SELECT artifact_id, max(version_no) AS max_version_no
  FROM public.knowledge_artifact_versions
  GROUP BY artifact_id
) existing ON existing.artifact_id = kb.artifact_id
WHERE kb.artifact_id IS NOT NULL
ON CONFLICT DO NOTHING;

UPDATE public.knowledge_nodes n
SET
  artifact_id = ki.artifact_id,
  canonical_key = COALESCE(ki.canonical_key, n.canonical_key),
  importance = COALESCE(
    n.importance,
    ki.importance,
    (SELECT tr.default_importance FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    0.50
  ),
  level = COALESCE(
    n.level,
    ki.level,
    (SELECT tr.default_level FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    50
  )
FROM public.knowledge_items ki
WHERE n.source_table = 'knowledge_items'
  AND n.source_id = ki.id;

UPDATE public.knowledge_nodes n
SET
  artifact_id = kb.artifact_id,
  canonical_key = COALESCE(kb.canonical_key, n.canonical_key),
  importance = COALESCE(
    n.importance,
    kb.importance,
    (SELECT tr.default_importance FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    0.50
  ),
  level = COALESCE(
    n.level,
    kb.level,
    (SELECT tr.default_level FROM public.knowledge_node_type_registry tr WHERE tr.node_type = n.node_type),
    50
  )
FROM public.kb_entries kb
WHERE n.source_table = 'kb_entries'
  AND n.source_id = kb.id;

UPDATE public.knowledge_nodes n
SET
  importance = COALESCE(n.importance, tr.default_importance),
  level = COALESCE(n.level, tr.default_level)
FROM public.knowledge_node_type_registry tr
WHERE tr.node_type = n.node_type;

-- ── 6. Operational audit views ────────────────────────────────────

CREATE OR REPLACE VIEW public.v_knowledge_lineage AS
SELECT
  a.id AS artifact_id,
  a.persona_id,
  p.slug AS persona_slug,
  a.title,
  a.content_type,
  a.curation_status,
  a.importance,
  a.level,
  a.confidence,
  a.vault_file_path,
  a.git_commit_sha,
  a.current_knowledge_item_id,
  a.current_kb_entry_id,
  count(DISTINCT n.id) AS graph_nodes,
  count(DISTINCT v.id) AS versions
FROM public.knowledge_artifacts a
LEFT JOIN public.personas p ON p.id = a.persona_id
LEFT JOIN public.knowledge_nodes n ON n.artifact_id = a.id
LEFT JOIN public.knowledge_artifact_versions v ON v.artifact_id = a.id
GROUP BY a.id, p.slug;

CREATE OR REPLACE VIEW public.v_knowledge_curation_backlog AS
SELECT
  a.id AS artifact_id,
  a.persona_id,
  p.slug AS persona_slug,
  a.title,
  a.content_type,
  a.curation_status,
  a.importance,
  a.level,
  a.confidence,
  a.duplicate_of,
  a.canonical_key,
  a.canonical_hash,
  a.current_knowledge_item_id,
  a.current_kb_entry_id,
  a.created_at,
  a.updated_at,
  CASE
    WHEN a.duplicate_of IS NOT NULL THEN 'duplicate'
    WHEN a.curation_status IN ('pending','proposed') THEN 'needs_review'
    WHEN NOT EXISTS (SELECT 1 FROM public.knowledge_nodes n WHERE n.artifact_id = a.id) THEN 'missing_graph'
    ELSE 'ok'
  END AS backlog_reason
FROM public.knowledge_artifacts a
LEFT JOIN public.personas p ON p.id = a.persona_id
WHERE a.curation_status IN ('pending','proposed','duplicate')
   OR a.duplicate_of IS NOT NULL
   OR NOT EXISTS (SELECT 1 FROM public.knowledge_nodes n WHERE n.artifact_id = a.id);
