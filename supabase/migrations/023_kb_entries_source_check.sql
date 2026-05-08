-- ============================================================
-- Brain AI Platform — Migration 023
-- Expand kb_entries.source CHECK to allow graph_embed.
--
-- Why: services/supabase_client.py::sync_embedded_kb_node mirrors
-- knowledge nodes promoted via the graph (FAQ/Copy/Tom/Regra/Entidade →
-- Embedded edge) into kb_entries with source='graph_embed'. The original
-- constraint only allowed ('sheets','manual'), causing a 23514 violation
-- and a 502 from POST /knowledge/graph-edges every time the operator
-- linked any approved knowledge to the Embedded node.
--
-- Business rule (CLAUDE.md §10, Embedded ↔ KB): every knowledge node
-- connected to Embedded must mirror to kb_entries so the persona's KB
-- list reflects what the agents actually retrieve.
-- ============================================================

ALTER TABLE kb_entries DROP CONSTRAINT IF EXISTS kb_entries_source_check;

ALTER TABLE kb_entries
  ADD CONSTRAINT kb_entries_source_check
  CHECK (source IN ('sheets', 'manual', 'graph_embed'));
