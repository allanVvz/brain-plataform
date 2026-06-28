# BRA-20 Execution Evidence Pack (Graph Validator + Migration Agent)

Date: 2026-05-26
Issue: BRA-20
Owner role: Graph Validator + Migration Agent

## 1) Allowed Edge Matrix (Main Hierarchy)

Canonical `edge_type=main` only:

1. persona -> brand
2. brand -> briefing
3. briefing -> campaign
4. campaign -> audience
5. audience -> product_group
6. product_group -> product
7. product -> offer
8. offer -> copy
9. copy -> faq
10. faq -> embed (`faq.status='approved'`)

Blocked direct-to-embed:
- product -> embed
- campaign -> embed
- copy -> embed
- asset -> embed
- gallery -> embed
- faq(status != approved) -> embed

Reference:
- [BRA-20-graph-validation-migration-package.md](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-graph-validation-migration-package.md)

## 2) Validation Algorithm Contract

1. Resolve source/target node type and source status.
2. Validate pair in `knowledge_allowed_edges` for requested `edge_type`.
3. For `edge_type='main'`: enforce top-down ordering, single active parent, and cycle prevention.
4. For `target_type='embed'`: enforce source type `faq` and `faq.status='approved'`.
5. On reject: persist audit row in `graph_validation_events` and abort edge write.

Stable errors:
- `INVALID_MAIN_EDGE`
- `MAIN_EDGE_BACKWARD`
- `MAIN_EDGE_CYCLE`
- `MULTIPLE_ACTIVE_MAIN_PARENTS`
- `EMBED_SOURCE_NOT_FAQ`
- `FAQ_NOT_APPROVED_FOR_EMBED`

## 3) SQL Migration Draft + Review Notes

Draft file:
- [042_bra20_graph_validation_hardening_draft.sql](/C:/Users/Alan/Documents/repositorios/ai-brain/supabase/migrations/042_bra20_graph_validation_hardening_draft.sql)

Review notes:
- Additive migration only (registry/allowed-edge upsert, snapshot insert, trigger function patch).
- No hard-delete; contract prefers `metadata.active=false` demotion.
- Trigger rejects invalid writes before persistence.
- Includes explicit FAQ approval gate for embed target.

## 4) Rollback Checklist

1. Drop `trg_validate_knowledge_edge_contract` on `knowledge_edges`.
2. Restore previous `validate_knowledge_edge_contract()` body.
3. Keep `graph_validation_events` and `graph_validation_snapshots` for audit continuity.
4. Re-enable strict rules only after SQL review + QA fixture pass.

## 5) Data Preservation Plan

1. Snapshot node/edge counts per persona before guardrail activation.
2. Canonicalize aliases (`embedded` -> `embed`) with lineage metadata.
3. Preserve legacy edges by soft-demotion; do not delete rows.
4. Preserve `relation_type`, `confidence`, `weight`, `metadata` unless demotion metadata is required.

## 6) QA Fixture (Execution Input)

Fixture file:
- [bra20_graph_validation_cases.json](/C:/Users/Alan/Documents/repositorios/ai-brain/tests/fixtures/bra20_graph_validation_cases.json)
- Machine-readable contract:
- [BRA-20-validation-contract.json](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-validation-contract.json)

Covers:
- Positive full chain: Persona -> Brand -> Briefing -> Campaign -> Audience -> Product Group -> Product -> Offer -> Copy -> FAQ(approved) -> Embed.
- Negative 1: `product -> embed` rejected.
- Negative 2: `faq(pending_validation) -> embed` rejected.
- Additional: backward main edge, cycle, duplicate main parent, and asset/gallery to embed block.
- Semantic tree expectations:
  - every non-persona node has one active main parent;
  - at least one brand exists and has a briefing child;
  - briefing never appears as sibling layer of campaign;
  - briefing never appears as sibling layer of audience;
  - briefing main parent type must be `brand` or `campaign`;
  - audience nodes must include `summary_markdown`;
  - audience content must not contain forbidden terms (`sdr`, `classifier`);
  - audience nodes must include a leads-group reference (`leads_group_id` or equivalent metadata key).
  - Sofia must log recommendation artifacts for optional layer insertion (`campaign -> briefing -> audience`) before any accepted action.

## 7) API/DB Evidence Contract (Before/After)

Run in QA against persona fixture slug (`vz-lupas`) and store outputs in issue evidence:

```sql
-- before
select count(*) as nodes_before
from knowledge_nodes
where persona_slug = 'vz-lupas';

select count(*) as edges_before
from knowledge_edges e
join knowledge_nodes n on n.id = e.source_node_id
where n.persona_slug = 'vz-lupas'
  and coalesce((e.metadata->>'active')::boolean, true) = true;
```

```sql
-- after positive fixture
select id, slug, node_type, status
from knowledge_nodes
where persona_slug = 'vz-lupas'
order by node_type, slug;

select id, source_node_id, target_node_id, edge_type, relation_type
from knowledge_edges
where coalesce((metadata->>'active')::boolean, true) = true
  and source_node_id in (
    select id from knowledge_nodes where persona_slug = 'vz-lupas'
  );
```

```bash
curl "${API_URL}/knowledge/graph?mode=semantic_tree&all_edges=1&persona_slug=vz-lupas"
```

Acceptance for "knowledge inserted":
- All expected slugs have persisted node IDs.
- All expected allowed edges have persisted edge IDs.
- Same IDs are visible in semantic_tree payload.
- Rejected edges are absent in DB and API payload.
- One `graph_validation_events` row exists per reject with expected `error_code`.
- Brand and audience semantic expectations pass from contract (`BRA-20-validation-contract.json`).
- Layer-depth assertions pass: no `briefing/campaign` or `briefing/audience` sibling-depth collision in main traversal.

## 9) Recommendation Log Probe (Optional Layer Governance)

When campaign has no optional briefing inserted, runner/QA must verify recommendation evidence exists with required fields:

- `subject_node_id`
- `recommended_edge.source_node_id`
- `recommended_edge.target_node_id`
- `recommended_edge.edge_type`
- `reason`
- `created_at`
- `accepted_at|null`
- `dismissed_at|null`

Accepted storage locations:

- `knowledge_nodes.metadata.recommendations` (structured array/object), or
- `kg_recommendations` table when available in backend scope.

If backend recommendation log is unavailable in the target environment, mark run as `blocked` with owner `Backend Engineer (BRA-25)` and action `expose recommendation log contract for Sofia optional layers`.

## 8) Automated Fixture Check Executed In This Heartbeat

Command run:
- `python` JSON sanity check over fixture schema/case coverage.

Observed result:
- fixture: `tests/fixtures/bra20_graph_validation_cases.json`
- nodes: `14`
- cases: `11`
- required cases missing: `[]`
- acceptance contract flags present: `True`

This is static fixture validation evidence (no DB mutation).
