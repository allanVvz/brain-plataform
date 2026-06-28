# BRA-24 Regression Risk Report

Date: 2026-05-26
Issue: BRA-24
Owner role: QA Regression Guardian
Disposition: `blocked` if critical recurrence reappears in release candidate.

## Scope Verified This Heartbeat

- Known bug registry formalized for recurrent graph/embed/catalog failures.
- Regression fixture added for valid/invalid graph semantics.
- Smoke checks added for:
  - Product cannot connect to Embed.
  - Unapproved FAQ cannot connect to Embed.
  - Tree View cannot include reference edges.
  - Graph/knowledge run cannot be marked `done` without verifiable graph work product (or explicit `blocked` cause).
- Smoke execution evidence:
  - `python tests/smoke_bra24_regression_guardian.py` -> `OK BRA-24 guardian smoke passed`.

## Smoke Checklist (Release Gate)

1. Run `pytest tests/smoke_bra24_regression_guardian.py -q`
2. Run `pytest tests/test_qa_contract_routes.py -q`
3. Run `pytest tests/test_vzlupas_preflight_contract.py -q`
4. Confirm no route or frontend change reports valid graph when preflight fails.
5. Confirm migration PR includes rollback section for graph contract changes.
6. Confirm graph/knowledge agent runs marked `done` include graph evidence (`graph_node`, `graph_edge`, `graph_snapshot`, or `qa_graph_assertion`), otherwise force `blocked` with explicit owner/action.

## Blocking Warnings

1. Release is blocked if any `product -> embed` edge is possible (`KG-001`).
2. Release is blocked if unapproved FAQ reaches Embed (`KG-002`).
3. Release is blocked if Catalog creates embed-ready knowledge directly (`KG-005`).
4. Release is blocked if Tree View includes non-main/reference edge (`KG-003`).
5. Release is blocked if graph/knowledge run is marked `done` sem entrega verificável no grafo (`KG-007`).

## Recommended New Regression Fixtures

1. Fixture for `graph view shows refs but tree hides refs` split rendering contract.
2. Fixture for frontend mismatch: preflight invalid + UI healthy badge.
3. Fixture for migration rollback dry-run with edge taxonomy reversal.

## Handoff Notes

- QA Lead: use `docs/qa/BRA-24-known-bug-registry.md` as canonical recurrence IDs.
- QA Lead: release gate authority and assignment matrix are defined in `docs/qa/BRA-24-qa-lead-release-gate.md`.
- PR & Deploy Agent: execute smoke checklist before merge/deploy.
- Release Manager: treat `KG-001`, `KG-002`, `KG-005` as hard blockers, not soft risks.
- Environment note: `pytest` is unavailable in this host Python (`No module named pytest`), so automated verification in this heartbeat used direct smoke script execution.
