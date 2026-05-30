# BRA-20 - Graph Validation + Migration Package (QA Insertion Gate)

## Scope
- Issue: `BRA-20`
- Goal: enforce insertion-time graph validation in QA so invalid edges never reach persistence/embedding workflows.
- This package does not change backend runtime code; it defines DB-side contracts, fixtures, rollback, and preservation strategy.
- Complementary architecture brief: [BRA-20-tree-data-architecture-brief.md](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-tree-data-architecture-brief.md)
- Execution evidence pack: [BRA-20-execution-evidence-pack.md](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-execution-evidence-pack.md)

## Canonical Main Hierarchy
`persona -> brand -> briefing -> campaign -> audience -> product_group -> product -> offer -> copy -> faq -> embed`

Rules:
- Main hierarchy is strictly top-down.
- Main edges cannot go backward.
- Main edges cannot create cycles.
- Each child node has at most one active main parent.
- Only `faq(status=approved)` can connect to `embed`.

## Allowed Edge Matrix

| Source | Target | edge_type=main | edge_type=reference | Conditions |
|---|---|---|---|---|
| persona | brand | allow | allow | none |
| brand | briefing | allow | allow | none |
| briefing | campaign | allow | allow | none |
| campaign | audience | allow | allow | none |
| audience | product_group | allow | allow | none |
| product_group | product | allow | allow | none |
| product | offer | allow | allow | none |
| offer | copy | allow | allow | none |
| copy | faq | allow | allow | none |
| faq | embed | allow | allow | `faq.status='approved'` |

### Explicitly Blocked to Embed
- `product -> embed`
- `campaign -> embed`
- `copy -> embed`
- `asset -> embed`
- `gallery -> embed`
- `faq(status != approved) -> embed`

## Validation Algorithm Contract
1. Resolve `source_type`, `target_type`, `source_status`, `edge_type`.
2. Validate pair against `knowledge_allowed_edges` for the given `edge_type`.
3. If `edge_type='main'`:
- enforce strict top-down order (`source.sort_order < target.sort_order`);
- reject cycles considering only active main edges;
- enforce single active main parent per child.
4. If `target_type='embed'`:
- enforce `source_type='faq'`;
- enforce `source_status='approved'`.
5. On any rejection:
- insert record in `graph_validation_events`;
- raise exception, block write.

## Error Contract (Stable)
- `INVALID_MAIN_EDGE`
- `MAIN_EDGE_BACKWARD`
- `MAIN_EDGE_CYCLE`
- `MULTIPLE_ACTIVE_MAIN_PARENTS`
- `EMBED_SOURCE_NOT_FAQ`
- `FAQ_NOT_APPROVED_FOR_EMBED`

## Invalid Edge Report Format
```json
{
  "error_code": "EMBED_SOURCE_NOT_FAQ",
  "message": "Invalid edge: PRODUCT cannot connect directly to EMBED. Expected path: PRODUCT -> FAQ -> EMBED with FAQ.status = approved.",
  "details": {
    "source_type": "product",
    "target_type": "embed",
    "edge_type": "main"
  },
  "edge": {
    "source_node_id": "uuid",
    "target_node_id": "uuid",
    "relation_type": "product_has_embed",
    "edge_type": "main"
  }
}
```

## SQL Migration Draft
Reference draft: [042_bra20_graph_validation_hardening_draft.sql](/C:/Users/Alan/Documents/repositorios/ai-brain/supabase/migrations/042_bra20_graph_validation_hardening_draft.sql)

Highlights:
- additive tables/indexes/constraints;
- no hard delete;
- dedupe via edge demotion (`metadata.active=false`, lineage metadata);
- trigger-based enforcement for insert/update.

## Data Preservation Plan
1. Create pre-migration snapshot in `graph_validation_snapshots`.
2. Canonicalize legacy node types (`embedded -> embed`) with lineage in metadata.
3. For duplicated active main parents, demote all but newest edge; preserve row and reason.
4. Keep `relation_type`, `weight`, `confidence`, `metadata` unchanged unless required by edge demotion.
5. Keep persona isolation (`persona_id`) in all migration writes.

## Rollback Plan
1. Drop validation trigger to reopen legacy write behavior.
2. Drop strict unique index for active main parent (if compatibility requires).
3. Keep audit/snapshot tables by default (`graph_validation_events`, `graph_validation_snapshots`).
4. Revert `embed` canonicalization only if backend fallback requires legacy `embedded`.
5. Record rollback run in `graph_validation_snapshots` as `manual`.

## QA Fixture Requirements
Fixture source: [bra20_graph_validation_cases.json](/C:/Users/Alan/Documents/repositorios/ai-brain/tests/fixtures/bra20_graph_validation_cases.json)

Must cover:
- full valid main chain ending in `faq(approved) -> embed`;
- direct-to-embed blocks (`product/campaign/copy/asset/gallery -> embed`);
- unapproved FAQ to embed block;
- backward main edge block;
- main cycle block;
- multiple active main parent block;
- legacy embedded canonicalization behavior.

## Minimal Node Properties (semantic_tree readiness)
For every inserted node in this contract:
- `persona_id` or `persona_slug` (scope)
- `node_type` (canonical taxonomy)
- `slug` (stable reference)
- `title` (render label)
- `status` (validation lifecycle)
- `source` (`pending_source` when unknown)
- `metadata.active=true` (default visibility)

Recommended for deterministic QA rendering:
- `summary` or `content`
- `tags` (array)
- `metadata.level_hint` (int aligned with hierarchy level)

## Exact Acceptance Criteria for "Knowledge Inserted"
Use `GET /knowledge/graph?mode=semantic_tree&all_edges=1` after each fixture execution.

Knowledge is considered inserted only if all are true:
1. Node persistence:
- Each expected node slug from fixture resolves to a persisted node id.
2. Edge persistence:
- Each expected allowed edge resolves to a persisted edge id with `metadata.active=true`.
3. Endpoint visibility:
- The persisted node ids and edge ids are present in semantic_tree payload.
4. Negative guarantees:
- Rejected edges are absent from persistence and absent from semantic_tree payload.
5. Audit guarantees:
- Each rejected write produces one `graph_validation_events` row with expected `error_code`.

## Handoff
- Backend Engineer:
  - review/adjust SQL draft for release window;
  - map SQL exception/error_code to API response contract.
- QA/Test Engineer:
  - implement integration tests from fixture cases;
  - assert blocked writes do not persist edges;
  - assert `graph_validation_events` row exists for each rejected write.
