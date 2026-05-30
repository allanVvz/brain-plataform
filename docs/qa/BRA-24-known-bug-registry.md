# BRA-24 Known Bug Registry (QA Regression Guardian)

Last updated: 2026-05-26
Scope: graph semantics, embed gate, tree/graph rendering, catalog boundary, migration safety.

## Open Critical Recurrences

1. ID: `KG-001`
- Title: Product connected directly to Embed
- Recurrence: repeated
- Severity: critical
- Rule: `product -> embed` is forbidden
- Detection: `tests/helpers/graphHierarchyAssertions.py::validateNoForbiddenEdges`
- Blocking condition: any active `product -> embed` edge

2. ID: `KG-002`
- Title: Unapproved FAQ published to Embed
- Recurrence: repeated
- Severity: critical
- Rule: only approved FAQ can connect to Embed
- Detection: `validateFAQApprovalBeforeEmbed` and `validateNoForbiddenEdges`
- Blocking condition: any `faq(approved=false) -> embed`

3. ID: `KG-003`
- Title: Tree View leaks reference edges
- Recurrence: repeated
- Severity: high
- Rule: tree must include only `edge_type=main`
- Detection: `validateTreeViewUsesOnlyMainEdges`
- Blocking condition: tree payload includes any non-main edge id

4. ID: `KG-004`
- Title: Frontend masking invalid graph as valid
- Recurrence: repeated
- Severity: high
- Rule: UI cannot suppress critical edge errors
- Detection: preflight + render-state contract checks
- Blocking condition: preflight invalid while UI reports healthy

5. ID: `KG-005`
- Title: Catalog bypasses validation and creates embed-ready knowledge
- Recurrence: repeated
- Severity: critical
- Rule: Catalog ingest is draft-only, no direct embed ownership
- Detection: `tests/test_qa_contract_routes.py`
- Blocking condition: ingest accepts embed rows or bypasses FAQ approval flow

6. ID: `KG-007`
- Title: Agent run marked done without verifiable graph work product
- Recurrence: repeated
- Severity: critical
- Rule: for graph/knowledge tasks, `done` requires local QA graph evidence; otherwise run must be `blocked` with explicit cause
- Detection: `tests/smoke_bra24_regression_guardian.py::test_agent_run_requires_graph_evidence_or_explicit_blocker`
- Blocking condition: graph/knowledge run ends `done` with zero graph evidence

## Open Medium Risks

7. ID: `KG-006`
- Title: Migration without rollback visibility
- Recurrence: occasional
- Severity: medium
- Rule: migration change must expose rollback strategy
- Detection: migration review checklist
- Blocking condition: irreversible graph contract mutation without rollback notes

## Status Policy

- Do not relabel recurrent IDs as new isolated bugs.
- Any `KG-001`, `KG-002`, `KG-005`, or `KG-007` hit blocks release.
