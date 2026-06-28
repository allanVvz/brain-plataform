# BRA-19 Blocker Triage Addendum (Board Comment 2026-05-26)

Date: 2026-05-26
Issue: BRA-19
Owner: QA Lead (81a3ee69-9c95-4f02-9308-4d790cc0ad94)
Reference comment: 11ea9261-a8cc-47c3-a4f3-cceace5da9f4

## Purpose

Formalize the latest board comment as a hard unblock contract for BRA-19 while the parent issue remains dependency-blocked.

## Adopted Unblock Contract

BRA-19 remains blocked until all evidence classes below exist:

1. Positive fixture inserted in AI Brain QA.
2. Negative cases executed.
3. Automated test passing.
4. Visual/API validation at:
   - http://192.168.0.182:3000/knowledge/graph?mode=semantic_tree&all_edges=1

## Mapping to Existing Child Issues

- BRA-20: fixture contract and graph-validation rules package (including required evidence format for node/edge IDs).
- BRA-21: official seed execution in QA with before/after counts and inserted node/edge IDs.
- BRA-22: automated test that proves real graph insertion, with green run output attached.
- BRA-23: visual/API validation on semantic tree route with evidence artifacts.
- BRA-24: regression record for "agents active without verifiable graph delivery" and closure evidence.

## Parent Disposition Rule

- BRA-19 cannot move to `done` without all four evidence classes attached and cross-referenced to child deliverables.
- Child deliverables containing only plan text (without execution evidence) are rejected as incomplete.
- QA Lead can update strategy and gate criteria, but cannot mark release approved; handoff is to PR & Deploy Agent only after all QA gates pass.

## Immediate QA Lead Action in This Heartbeat

- Human board comment triaged and converted into explicit unblock criteria.
- Parent issue status should remain `blocked` with named unblock owners as child issue assignees above.

## Retry Triage (2026-05-26T07:21Z)

Board comment `95b7c3c9-2c13-4b5c-bcbb-fc6f0a2a18f4` (`retry`) processed.

### Retry instructions to blocked child owners

All child issues (`BRA-20`, `BRA-21`, `BRA-22`, `BRA-23`, `BRA-24`) must re-run with execution evidence only.

Minimum evidence package per child retry:
1. Exact command/script executed.
2. Timestamped output excerpt.
3. Artifact path committed in repo (`docs/qa/...` or test logs).
4. Pass/fail conclusion.
5. If fail: named unblock owner + next action.

### Parent issue rule on this retry

- `BRA-19` remains `blocked`.
- No status promotion from retry comment alone.
- Parent can move only after four mandatory evidence classes are attached and cross-referenced:
  - positive QA fixture insertion,
  - negative cases executed,
  - automated test passing,
  - visual/API validation at semantic_tree route.

## Chain Status Triage (2026-05-26T19:36)

Board update `eafbedf8-cbaa-4ff5-856c-9b8e31323658` processed.

### Current dependency interpretation

- `BRA-20`: `in_review` with updated hard invariants and local 9/9 tests.
- `BRA-22`: `blocked` due to graph fetch 404 (`test-artifacts/graph-runs/2026-05-26T19-34-18-340Z.json`).
- `BRA-25` (Backend Engineer): running, now the critical unblock path for semantic tree endpoint and chain generation correctness.

### QA Lead coordination rule (effective immediately)

1. Do not re-dispatch `BRA-22` until `BRA-25` reports completed backend fix with executable evidence.
2. After `BRA-25` success, require immediate `BRA-22` rerun and attach `pass` evidence.
3. Keep `BRA-19` blocked until both are true:
   - `BRA-22` pass confirmed,
   - `BRA-23` visual validation confirms semantic_tree behavior.
4. If `BRA-25` moves to `blocked` due to container/rebuild/deploy dependency, escalate by opening handoff issue for PR & Deploy Agent with explicit unblock owner/action.

### Regression signal acknowledged

Reported visual regression (isolated brand; audience linked with sdr/classifier) is treated as release-blocking symptom under G4 and cannot be waived by partial backend progress.
