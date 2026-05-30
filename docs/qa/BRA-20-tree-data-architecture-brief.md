# BRA-20 Tree/Data Architecture Brief (QA Graph Insertion)

Date: 2026-05-26
Owner: Tree/Data Architect
Issue: BRA-20

## Scope

Define the official graph shape contract used by QA insertion validation, preserving:

- main hierarchy integrity for `semantic_tree`;
- reference flexibility for `graph`;
- FAQ approval gate before Embed/RAG publication;
- catalog normalization without bypassing AI Brain validation.

This is a specification artifact only. No runtime or migration execution is included.

Companion artifacts:

- Machine-readable contract: [BRA-20-validation-contract.json](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-validation-contract.json)
- Execution evidence pack: [BRA-20-execution-evidence-pack.md](/C:/Users/Alan/Documents/repositorios/ai-brain/docs/qa/BRA-20-execution-evidence-pack.md)

## Official Node Model

Main spine node types:

1. persona
2. brand
3. briefing
4. campaign
5. audience
6. product_group
7. product
8. offer
9. copy
10. faq
11. embed

Support/final-use node types for graph semantics:

- asset
- gallery
- backgrounds
- texturas
- regras
- tom_de_voz
- entidades

Minimum node contract (semantic tree readiness):

- `persona_id` or `persona_slug`
- `node_type`
- `slug`
- `title`
- `status`
- `source`
- `metadata.active=true`

## Official Edge Model

- `edge_type=main`: canonical hierarchy edges used to compose Tree View.
- `edge_type=reference`: semantic/support edges used in Graph View only.

Mandatory edge payload:

- `source_node_id`
- `target_node_id`
- `relation_type`
- `edge_type`
- `confidence`
- `weight`
- `metadata.active=true` for visible edges

Logical uniqueness:

- `source_node_id + target_node_id + relation_type + edge_type` for active edges.

## Allowed Main Edge Matrix

Only the pairs below are valid as `edge_type=main`:

1. persona -> brand
2. brand -> briefing
3. briefing -> campaign
4. campaign -> audience
5. audience -> product_group
6. product_group -> product
7. product -> offer
8. offer -> copy
9. copy -> faq
10. faq -> embed (only `faq.status=approved`)

Main edge invariants:

- Strictly top-down only.
- No cycles.
- At most one active main parent per child.
- Main edges cannot be replaced by reference edges in Tree View.
- `briefing` must never be sibling (same depth from persona) of `campaign`.
- `briefing` must never be sibling (same depth from persona) of `audience`.
- A `briefing` main parent can only be `brand` or `campaign`.

## Fixed vs Optional Layers

Fixed mandatory structures:

1. `persona -> brand`
2. `brand -> briefing`
3. Remaining canonical BRA spine remains required for approved flows.

Optional (user-accepted) layer insertion:

- Recommended path when campaign is created: `campaign -> briefing -> audience`.
- Direct `campaign -> audience` remains valid only when optional briefing insertion was not accepted.
- Sofia must not auto-create `campaign -> briefing` optional layer without explicit user acceptance.
- Sofia must log recommendation intent before action (`metadata.recommendations` or `kg_recommendations`).

Recommendation log required fields:

- `subject_node_id`
- `recommended_edge` (`source_node_id`, `target_node_id`, `edge_type`)
- `reason`
- `created_at`
- `accepted_at|null`
- `dismissed_at|null`

## Reference Edge Guidance

Reference edges are allowed for semantic navigation and supporting evidence, but they cannot redefine hierarchy.

Allowed examples:

- copy -> product (`supports_copy`)
- faq -> product (`answers_question`)
- asset -> gallery (`gallery_asset`)
- faq -> embed (`visible_to_agent` or equivalent), still requiring approved FAQ

Rules:

- Reference edges never change the node depth in semantic tree.
- Reference edges to `embed` still obey source and approval guards.
- Removing an edge must not delete node content by default.

## Tree View vs Graph View

Tree View (`/knowledge/graph?mode=semantic_tree`):

- Uses only active `main` edges.
- Renders one canonical parent path per node.
- Persona is the conceptual root and must not have incoming main edge.
- Every non-persona node must have one active main parent.
- Brand layer must exist (`min_count=1`) and each brand must have at least one briefing child.
- Audience nodes must include `summary_markdown` and a leads-group reference (`leads_group_id` or equivalent metadata key).
- Audience textual content must not include forbidden terms: `sdr`, `classifier`.
- Fail if `briefing` and `campaign` appear at same depth in main-edge traversal.
- Fail if `briefing` and `audience` appear at same depth in main-edge traversal.

Graph View (`/knowledge/graph?all_edges=1`):

- Uses active `main` + `reference` edges.
- Shows cross-links and supporting relations.
- Must preserve blocked edge rules (no forbidden embed source).

## Catalog -> AI Brain Mapping

Catalog input must be normalized before graph insertion and never bypass validation:

1. Catalog brand/tenant context -> `persona` + `brand`
2. Campaign context in catalog metadata -> `campaign`
3. Target segment fields -> `audience`
4. Product family/category -> `product_group`
5. SKU/product card -> `product`
6. Price/condition bundle -> `offer`
7. Promotional text draft -> `copy`
8. Q&A blocks -> `faq` (`pending_validation` by default)
9. Only approved FAQ -> `embed` connection/publication
10. Media URLs/files -> `asset` and optional `gallery` links (never embed target)

Normalization status defaults:

- Missing source -> `source=pending_source`
- Not human-validated -> `status=pending_validation`
- Approved for publish gates -> `status=approved`

## Validation Examples

Valid:

- `copy(approved) -> faq(approved) -> embed`
- `asset -> gallery` as reference, independent of embed flow
- `product -> offer -> copy` in main path

Invalid:

- `product -> embed` (blocked)
- `campaign -> embed` (blocked)
- `copy -> embed` (blocked)
- `asset -> embed` or `gallery -> embed` (blocked)
- `faq(pending_validation) -> embed` (blocked)
- Backward main edge (`product -> audience`) (blocked)
- Main cycle in any chain segment (blocked)

## Migration Requirements for Shape Changes

When changing allowed node/edge shape:

1. Update allowed edge matrix and error code mapping in migration draft.
2. Preserve existing rows through soft demotion (`metadata.active=false`) instead of hard delete.
3. Capture pre/post snapshots and validation events.
4. Keep canonical node type aliases explicit (example: `embedded -> embed`).
5. Run fixture validation against `semantic_tree` endpoint before rollout.

## Handoff Notes

Graph Validator + Migration Agent:

- implement/update DB guardrails from this matrix;
- keep stable error codes for QA assertions;
- keep snapshot + audit event contract.

Backend Engineer:

- enforce same contract in API-level validation messages;
- ensure blocked edges never persist;
- expose clear rejection payload for QA.

Frontend Agent:

- Tree View consumes only `main`;
- Graph View consumes `main + reference`;
- maintain connector semantics (top input / bottom output, Persona root, final nodes behavior).
