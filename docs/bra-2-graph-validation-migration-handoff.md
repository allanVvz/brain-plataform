# BRA-2 Graph Validation + Migration Handoff

## Scope
Issue: BRA-2
Owner lane: Graph Validator + Migration Agent
Primary artifact: `supabase/migrations/041_hierarchical_graph_validation_contract.sql`

## Allowed Edge Matrix (Canonical)
`edge_type = main`

| Source | Target | Allowed | Notes |
|---|---|---|---|
| persona | brand | yes | canonical root |
| brand | briefing | yes | top-down |
| briefing | campaign | yes | top-down |
| campaign | audience | yes | top-down |
| audience | product_group | yes | top-down |
| product_group | product | yes | top-down |
| product | offer | yes | top-down |
| offer | copy | yes | top-down |
| copy | faq | yes | top-down |
| faq | embed | yes (conditional) | source faq must have `status = approved` |

`edge_type = reference`
- Flexible across non-embed nodes.
- For `target = embed`, only `faq -> embed` is allowed and still requires `faq.status = approved`.

## Forbidden Direct-to-Embed Edges
- `product -> embed`
- `campaign -> embed`
- `copy -> embed`
- `asset -> embed`
- `gallery -> embed`
- `faq(status != approved) -> embed`

## Validation Algorithm Contract
1. Resolve source/target node types and source status.
2. If `edge_type = main`:
- Reject if source/target pair not in `knowledge_allowed_edges` for `main`.
- Reject if hierarchy order is backward (`source.sort_order >= target.sort_order`).
- Reject if edge creates a cycle in active main edges (recursive walk).
3. If `target_type = embed`:
- Reject if `source_type != faq`.
- Reject if `faq.status != approved`.
4. On rejection:
- Insert row into `graph_validation_events` with `error_code`, `message`, and `details`.
- Raise exception to block persistence.

## Main Parent Uniqueness
- Exactly one active `main` parent per child (`target_node_id`) via partial unique index:
  `uniq_active_main_parent_per_child`
- Migration pre-step demotes duplicates to inactive, hidden lineage (`metadata.demoted_from`).

## Data Preservation Plan
- Migration is additive (new columns/tables/indexes/trigger).
- Existing rows are preserved; duplicate active main parents are demoted, not deleted.
- Existing `embedded` nodes are canonicalized to `embed` and annotated in metadata (`legacy_node_type`, `canonicalized_at`).
- Persona segmentation is preserved (`persona_id` maintained across all writes).
- Snapshot baseline is stored in `graph_validation_snapshots` (`pre_migration`).

## SQL Draft Summary
Implemented in migration `041_hierarchical_graph_validation_contract.sql`:
- `knowledge_edges.edge_type` with check (`main|reference`) and backfill.
- `knowledge_allowed_edges` rule table + canonical seeds.
- `graph_validation_events` audit table.
- `graph_validation_snapshots` baseline table.
- Canonical `embed` node type and alias handling for legacy `embedded`.
- Trigger function `validate_knowledge_edge_contract()` on `knowledge_edges` insert/update.

## Rollback Plan
1. Disable runtime edge blocking:
- Drop trigger `trg_validate_knowledge_edge_contract`.
2. Optional compatibility rollback:
- Revert `knowledge_nodes.node_type` from `embed` back to `embedded` only if required by runtime.
3. Keep audit data unless explicitly requested:
- `graph_validation_events` and `graph_validation_snapshots` are safe to retain.
4. Remove strict uniqueness if rollback requires legacy multi-parent behavior:
- Drop index `uniq_active_main_parent_per_child`.
5. Re-open write window only after backend confirms fallback guards.

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
    "source_node_id": "<uuid>",
    "target_node_id": "<uuid>",
    "relation_type": "<relation_type>",
    "edge_type": "main"
  }
}
```

## Error Message Contracts
- `INVALID_MAIN_EDGE`
- `MAIN_EDGE_BACKWARD`
- `MAIN_EDGE_CYCLE`
- `EMBED_SOURCE_NOT_FAQ`
- `FAQ_NOT_APPROVED_FOR_EMBED`

## QA Fixture Requirements
1. Valid main chain fixture:
- `persona -> brand -> briefing -> campaign -> audience -> product_group -> product -> offer -> copy -> faq(approved) -> embed`
2. Blocked embed fixtures:
- `product -> embed`
- `campaign -> embed`
- `copy -> embed`
- `asset -> embed`
- `gallery -> embed`
- `faq(pending) -> embed`
3. Main cycle fixture:
- Insert chain then attempt edge that closes loop.
4. Backward main edge fixture:
- Attempt `product -> audience` as `main`.
5. Multi-parent fixture:
- Two active `main` parents to same child must fail (or one is demoted in migration backfill phase).
6. Legacy embed fixture:
- Existing `embedded` node is canonicalized and still queryable via canonical type `embed`.

## Handoff
- Backend Engineer: implement route/service usage of `edge_type` and surface DB error contracts.
- QA/Test Engineer: build tests from fixture list and assert `graph_validation_events` inserts for rejected writes.
