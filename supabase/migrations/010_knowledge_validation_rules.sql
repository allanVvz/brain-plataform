-- 010_knowledge_validation_rules.sql
--
-- Camada de regras de validacao de conteudo por tipo de conhecimento.
--
-- Goal:
--   Tornar regras como "todo produto deve ter preco" configuraveis em vez de
--   espalhadas em codigo. Cada regra aponta para um content_type/node_type e
--   um JSON Pointer dentro de metadata. Curator/classifier consulta esta
--   tabela para decidir entre validar artifact ou abrir proposta.
--
-- Safe to run multiple times. Nao toca em dados de cliente.

-- ── 1. Regras configuraveis por tipo ─────────────────────────────

CREATE TABLE IF NOT EXISTS public.knowledge_validation_rules (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key        TEXT NOT NULL UNIQUE,            -- ex: 'product.price.required'
  applies_to      TEXT NOT NULL,                   -- content_type/node_type alvo (ex 'product')
  scope           TEXT NOT NULL DEFAULT 'artifact' -- 'artifact' | 'node' | 'both'
                  CHECK (scope IN ('artifact','node','both')),
  description     TEXT,
  -- ── O que avaliar ──
  -- field_path: caminho dentro do metadata jsonb (notacao 'a.b.c').
  -- O field_path null + check_kind 'custom' permite usar custom_predicate.
  field_path      TEXT,
  check_kind      TEXT NOT NULL DEFAULT 'present_non_null'
                  CHECK (check_kind IN (
                    'present_non_null',     -- campo existe e nao e null/''/[]
                    'numeric_positive',     -- numero > 0
                    'currency_object',      -- {amount, currency, display}
                    'enum',                 -- valor em config.allowed
                    'regex',                -- match config.pattern
                    'custom'                -- avaliado em codigo
                  )),
  -- Config livre por kind (ex: {"allowed":["BRL","USD"]} ou {"pattern":"^https?://"})
  config          JSONB NOT NULL DEFAULT '{}'::jsonb,
  severity        TEXT NOT NULL DEFAULT 'block'    -- block: impede validar; warn: cria proposta mas valida
                  CHECK (severity IN ('block','warn','info')),
  -- O que fazer quando a regra falha
  on_violation    TEXT NOT NULL DEFAULT 'propose_correction'
                  CHECK (on_violation IN (
                    'propose_correction',   -- abre knowledge_curation_proposals
                    'mark_pending',         -- mantem artifact pending
                    'reject',               -- artifact -> 'rejected'
                    'noop'
                  )),
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validation_rules_applies_to
  ON public.knowledge_validation_rules(applies_to)
  WHERE active = TRUE;

-- ── 2. Seed: regras de produto que ja podemos exigir hoje ────────
-- (Idempotente. Operadores podem desativar via UPDATE active=false)

INSERT INTO public.knowledge_validation_rules
  (rule_key, applies_to, scope, description, field_path, check_kind, config, severity, on_violation)
VALUES
  ('product.price.required',
   'product', 'both',
   'Todo produto validado precisa carregar preco estruturado em metadata.price.',
   'price', 'currency_object',
   '{"required_keys":["amount","currency","display"]}'::jsonb,
   'block', 'propose_correction'),

  ('product.price.amount.positive',
   'product', 'both',
   'metadata.price.amount deve ser numero > 0.',
   'price.amount', 'numeric_positive',
   '{}'::jsonb,
   'block', 'propose_correction'),

  ('product.price.currency.iso',
   'product', 'both',
   'metadata.price.currency deve ser ISO de 3 letras.',
   'price.currency', 'regex',
   '{"pattern":"^[A-Z]{3}$"}'::jsonb,
   'warn', 'propose_correction'),

  ('product.colors_count.numeric',
   'product', 'both',
   'metadata.colors_count, quando presente, deve ser numerico positivo.',
   'colors_count', 'numeric_positive',
   '{"allow_null":true}'::jsonb,
   'info', 'noop'),

  ('asset.url_or_file_path.required',
   'asset', 'both',
   'Asset valido precisa ter file_path ou metadata.url.',
   NULL, 'custom',
   '{"any_of":["file_path","url"]}'::jsonb,
   'warn', 'propose_correction')
ON CONFLICT (rule_key) DO UPDATE SET
  applies_to     = EXCLUDED.applies_to,
  scope          = EXCLUDED.scope,
  description    = EXCLUDED.description,
  field_path     = EXCLUDED.field_path,
  check_kind     = EXCLUDED.check_kind,
  config         = EXCLUDED.config,
  severity       = EXCLUDED.severity,
  on_violation   = EXCLUDED.on_violation,
  updated_at     = now();

-- ── 3. View: artifacts com violacao ativa ────────────────────────
-- Heuristica simples para casos sem custom predicate. Curator/teste
-- usam isto como ponto de partida para abrir proposals.

CREATE OR REPLACE VIEW public.v_knowledge_validation_failures AS
WITH rule_targets AS (
  SELECT
    r.id          AS rule_id,
    r.rule_key,
    r.applies_to,
    r.field_path,
    r.check_kind,
    r.config,
    r.severity,
    r.on_violation,
    a.id          AS artifact_id,
    a.persona_id,
    a.title,
    a.content_type,
    a.curation_status,
    a.metadata
  FROM public.knowledge_validation_rules r
  JOIN public.knowledge_artifacts a
    ON a.content_type = r.applies_to
  WHERE r.active = TRUE
    AND r.scope IN ('artifact','both')
    AND r.check_kind <> 'custom'
),
observed AS (
  SELECT
    t.*,
    CASE
      WHEN t.field_path IS NULL THEN NULL
      ELSE t.metadata #> string_to_array(t.field_path, '.')
    END AS observed_value,
    CASE
      WHEN t.field_path IS NULL THEN NULL
      ELSE t.metadata #>> string_to_array(t.field_path, '.')
    END AS observed_text
  FROM rule_targets t
)
SELECT
  rule_id,
  rule_key,
  artifact_id,
  persona_id,
  title,
  content_type,
  curation_status,
  field_path,
  severity,
  on_violation,
  observed_value
FROM observed t
WHERE
  -- present_non_null: campo presente e nao e null/''/[]
  (check_kind = 'present_non_null'
   AND (field_path IS NULL
        OR observed_value IS NULL
        OR observed_value = 'null'::jsonb
        OR observed_text = ''
        OR (jsonb_typeof(observed_value) = 'array' AND jsonb_array_length(observed_value) = 0)))
  OR
  -- numeric_positive: ausente, nao numerico, ou <= 0
  (check_kind = 'numeric_positive'
   AND CASE
         WHEN observed_value IS NULL OR observed_value = 'null'::jsonb
           THEN COALESCE((config->>'allow_null')::boolean, FALSE) = FALSE
         WHEN jsonb_typeof(observed_value) <> 'number'
           THEN TRUE
         ELSE (observed_value::text)::numeric <= 0
       END)
  OR
  -- currency_object: precisa ser jsonb object com amount/currency/display
  (check_kind = 'currency_object'
   AND (jsonb_typeof(observed_value) IS DISTINCT FROM 'object'
        OR observed_value->'amount'   IS NULL
        OR observed_value->'currency' IS NULL
        OR observed_value->'display'  IS NULL
        OR jsonb_typeof(observed_value->'amount') <> 'number'
        OR CASE
             WHEN jsonb_typeof(observed_value->'amount') = 'number'
             THEN (observed_value->>'amount')::numeric <= 0
             ELSE TRUE
           END))
  OR
  -- regex: ausente OU nao casa
  (check_kind = 'regex'
   AND (observed_text IS NULL
        OR observed_text !~ COALESCE(t.config->>'pattern', '^$')));

COMMENT ON VIEW public.v_knowledge_validation_failures IS
  'Artefatos que violam regras ativas de knowledge_validation_rules. Curator deve gerar knowledge_curation_proposals para os com on_violation=propose_correction. Regras com check_kind=custom sao avaliadas no codigo, nao por esta view.';

-- ── 4. View especializada: produtos sem preco valido ─────────────

CREATE OR REPLACE VIEW public.v_knowledge_products_missing_price AS
WITH product_prices AS (
  SELECT
    a.id           AS artifact_id,
    a.persona_id,
    a.title,
    a.curation_status,
    a.metadata,
    a.metadata->'price' AS price
  FROM public.knowledge_artifacts a
  WHERE a.content_type = 'product'
)
SELECT
  artifact_id,
  persona_id,
  title,
  curation_status,
  metadata
FROM product_prices
WHERE
     jsonb_typeof(price) IS DISTINCT FROM 'object'
  OR price->'amount'   IS NULL
  OR price->'currency' IS NULL
  OR price->'display'  IS NULL
  OR jsonb_typeof(price->'amount') <> 'number'
  OR CASE
       WHEN jsonb_typeof(price->'amount') = 'number'
       THEN (price->>'amount')::numeric <= 0
       ELSE TRUE
     END;
