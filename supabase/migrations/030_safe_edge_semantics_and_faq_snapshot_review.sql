-- 030_safe_edge_semantics_and_faq_snapshot_review.sql
-- Safe semantics/rastreability enrichment for CRIAR single_branch.
-- This migration intentionally does not change relation_type or topology.

ALTER TABLE public.approved_knowledge_snapshots
  DROP CONSTRAINT IF EXISTS approved_knowledge_snapshots_status_check;

ALTER TABLE public.approved_knowledge_snapshots
  ADD CONSTRAINT approved_knowledge_snapshots_status_check
  CHECK (status IN ('draft','pending_validation','approved','active','needs_review','rejected','stale'));

WITH session_items AS (
  SELECT
    ki.id,
    ki.persona_id,
    ki.metadata,
    ki.metadata->>'session_id' AS session_id,
    COALESCE(ki.metadata->>'source_ref', ki.metadata->>'session_id') AS source_ref,
    COALESCE(ki.metadata->>'created_via', 'kb_intake_sofia') AS created_via,
    COALESCE(ki.metadata->>'tree_mode', 'single_branch') AS tree_mode,
    COALESCE(ki.metadata->>'branch_policy', 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_items ki
  WHERE ki.metadata->>'session_id' = '2a0015cd-d7f4-41f0-9573-df30229cb739'
)
UPDATE public.knowledge_nodes n
SET metadata =
  COALESCE(n.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'session_id', si.session_id,
    'source_ref', si.source_ref,
    'created_via', si.created_via,
    'tree_mode', si.tree_mode,
    'branch_policy', si.branch_policy
  )
FROM session_items si
WHERE n.source_table = 'knowledge_items'
  AND n.source_id = si.id
  AND n.persona_id = si.persona_id;

WITH session_nodes AS (
  SELECT
    n.id,
    n.node_type,
    n.slug,
    n.metadata->>'session_id' AS session_id,
    COALESCE(n.metadata->>'source_ref', n.metadata->>'session_id') AS source_ref,
    COALESCE(n.metadata->>'created_via', 'kb_intake_sofia') AS created_via,
    COALESCE(n.metadata->>'tree_mode', 'single_branch') AS tree_mode,
    COALESCE(n.metadata->>'branch_policy', 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_nodes n
  WHERE n.metadata->>'session_id' = '2a0015cd-d7f4-41f0-9573-df30229cb739'
),
session_edges AS (
  SELECT
    e.id,
    src.node_type AS source_type,
    tgt.node_type AS target_type,
    COALESCE(tgt.session_id, src.session_id) AS session_id,
    COALESCE(tgt.source_ref, src.source_ref) AS source_ref,
    COALESCE(tgt.created_via, src.created_via) AS created_via,
    COALESCE(tgt.tree_mode, src.tree_mode, 'single_branch') AS tree_mode,
    COALESCE(tgt.branch_policy, src.branch_policy, 'single_branch_by_default') AS branch_policy
  FROM public.knowledge_edges e
  JOIN session_nodes src ON src.id = e.source_node_id
  JOIN session_nodes tgt ON tgt.id = e.target_node_id
  WHERE COALESCE((e.metadata->>'active')::boolean, true) = true
)
UPDATE public.knowledge_edges e
SET metadata =
  COALESCE(e.metadata, '{}'::jsonb)
  || jsonb_build_object(
    'session_id', se.session_id,
    'source_ref', se.source_ref,
    'created_via', se.created_via,
    'tree_mode', se.tree_mode,
    'branch_policy', se.branch_policy,
    'semantic_relation',
      CASE
        WHEN se.source_type = 'persona' AND se.target_type = 'briefing' THEN 'contains_briefing'
        WHEN se.source_type = 'briefing' AND se.target_type = 'audience' THEN 'defines_audience'
        WHEN se.source_type = 'audience' AND se.target_type = 'product' THEN 'offers_product'
        WHEN se.source_type = 'product' AND se.target_type = 'copy' THEN 'supports_copy'
        WHEN se.source_type = 'copy' AND se.target_type = 'faq' THEN 'answers_question'
        WHEN se.source_type = 'faq' AND se.target_type = 'embedded' THEN 'published_to_rag'
        ELSE e.relation_type
      END,
    'semantic_label',
      CASE
        WHEN se.source_type = 'persona' AND se.target_type = 'briefing' THEN 'Persona contem briefing'
        WHEN se.source_type = 'briefing' AND se.target_type = 'audience' THEN 'Briefing define publico'
        WHEN se.source_type = 'audience' AND se.target_type = 'product' THEN 'Publico recebe oferta de produto'
        WHEN se.source_type = 'product' AND se.target_type = 'copy' THEN 'Produto sustenta copy'
        WHEN se.source_type = 'copy' AND se.target_type = 'faq' THEN 'Copy responde pergunta'
        WHEN se.source_type = 'faq' AND se.target_type = 'embedded' THEN 'FAQ publicado no RAG'
        ELSE e.relation_type
      END
  )
  || CASE
    WHEN COALESCE((e.metadata->>'primary_tree')::boolean, false) = true
      THEN jsonb_build_object('tree_role', 'primary_branch')
    ELSE '{}'::jsonb
  END
FROM session_edges se
WHERE e.id = se.id;
