# BRA-19 QA Strategy - Entrega Real no QA Local (Conhecimento -> Grafo)

Date: 2026-05-26  
Issue: BRA-19  
Owner: QA Lead (81a3ee69-9c95-4f02-9308-4d790cc0ad94)  
Priority: Critical

## 1) Scope and Quality Objective

Objective for BRA-19:
- Prove with release-gated evidence that any approved knowledge inserted in QA appears in the graph for the same persona, with canonical node/edge persistence and UI visibility.

Hard invariants in scope:
- Knowledge accepted into KB/RAG must exist as `knowledge_nodes`.
- Semantic relation must exist as `knowledge_edges`.
- `Embed` is final KB destination; connected content is queryable in persona-scoped Knowledge Base.
- `Gallery` is final Assets destination; connected content is queryable in persona-scoped Assets.
- Edge delete must not delete node; protected nodes (`Persona`, `Embedded`, `Gallery`) must not be deleted.

Out of scope:
- Product scope changes.
- New DB tables/migrations.
- Runtime feature changes not explicitly requested.

## 2) Required Inputs Consumed

- Architecture and invariants: `AGENTS.md`.
- Existing QA contract artifacts: `docs/qa/BRA-16-frontend-graph-render-state-contract.md`, `docs/qa/BRA-16-frontend-route-validation-note.md`.
- Test inventory from `tests/` and `tests/e2e/` covering graph, FAQ, intake, catalog, and UI behavior.

## 3) Release Gates (Mandatory)

Gate G1 - Graph Persistence Contract (Automated)
- For a QA persona, validated knowledge insertion must create/update `knowledge_nodes` and `knowledge_edges`.
- Fail if knowledge is in KB/RAG but absent in graph.

Gate G2 - FAQ to Embed Contract (Automated)
- Approved FAQ path must create/query expected graph links and KB representation.
- Unapproved/pending FAQ must not bypass approval semantics.

Gate G3 - Catalog Invalid-Case Coverage (Automated)
- Catalog ingest paths must reject/flag invalid source payloads without producing invalid graph state.

Gate G4 - Tree View / Graph View Behavior (Automated + Manual)
- Persona appears as top/root in tree semantics.
- Entry connectors render on top and output connectors on bottom.
- Final nodes (`Gallery`, `Embed`) accept inbound links per contract.
- Edge delete removes edge only, not node.

Gate G5 - SDR/Closer Grounding Scenarios (Automated)
- Agent context retrieval remains grounded in canonical knowledge path with persona scoping.

Gate G6 - Auditability / Rollback Awareness (Manual)
- QA evidence includes run IDs/timestamps, test command list, failures, and explicit rollback owner/action.

No gate is optional for BRA-19 because priority is critical and the issue validates production safety invariants.

## 4) Required Test List

Automated - must pass:
1. `python -m pytest -q tests/smoke_knowledge_graph.py`
2. `python -m pytest -q tests/smoke_rag_faq_only_gate.py`
3. `python -m pytest -q tests/integration_knowledge_rag_intake.py`
4. `python -m pytest -q tests/integration_knowledge_ui_hierarchy.py`
5. `python -m pytest -q tests/integration_faq_edge_direction_contract.py`
6. `python -m pytest -q tests/integration_chat_context.py`
7. `python -m pytest -q tests/integration_gallery_assets_resolution.py`
8. `python -m pytest -q tests/e2e/test_vzlupas_catalog_to_hierarchical_graph_e2e.py`

Manual - must pass with evidence:
1. Insert one approved knowledge item in QA persona and verify node + edge appear in Graph View.
2. Connect content to `Embed` and confirm persona-filtered KB visibility.
3. Connect visual content to `Gallery` and confirm persona-filtered Assets visibility.
4. Delete an edge in UI and verify node remains intact.
5. Validate tree rendering semantics for persona root and connector orientation.
6. Validate unauthorized persona request returns `403` and does not leak other persona names/data.

## 5) Blocking Criteria (Stop PR/Deploy)

Block immediately if any condition below is true:
- Any G1-G6 gate fails.
- Any failed test is omitted or hidden in report.
- “Tested manually” is used as substitute for required graph automation.
- Knowledge appears in KB/RAG but not in graph node/edge persistence.
- FAQ approval boundary is bypassed.
- Tree/Graph behavior violates protected-node or connector-direction contracts.
- Persona authorization leaks data or returns non-403 for unauthorized scope.
- No rollback owner/action is documented.

## 6) QA Agent Assignments

QA/Test Engineer (Automation owner):
- Execute and maintain G1, G2, G3, and G5 automated suites.
- Produce machine-readable run output with exact command list and failure traces.
- Ensure regressions include minimal reproducer and failing assertion path.

QA/E2E Validator (User-flow owner):
- Execute G4 and G6 manual validations in QA UI.
- Capture screenshots and response payload evidence for Graph View, Tree View, Embed, Gallery, and edge deletion behavior.
- Validate persona auth scoping behavior with authorized and unauthorized personas.

QA Regression Guardian (History/risk owner):
- Build focused rerun set from historical failures around graph hierarchy, FAQ-edge direction, catalog ingestion, and chat grounding.
- Confirm prior fragile paths still pass after current delivery.
- Attach regression delta: newly covered risks, still-open risks, and watchlist for next release.

## 7) Risk-Based Validation Matrix

| Risk | Impact | Probability | Detection | Gate | Owner |
|---|---|---|---|---|---|
| KB/RAG accepted without graph node/edge | Critical | Medium | `smoke_knowledge_graph`, `integration_knowledge_rag_intake` | G1 | QA/Test Engineer |
| FAQ approved-state bypass into Embed | Critical | Medium | `smoke_rag_faq_only_gate`, `integration_faq_edge_direction_contract` | G2 | QA/Test Engineer |
| Invalid catalog payload corrupts graph | High | Medium | catalog e2e + invalid-case assertions | G3 | QA/Test Engineer |
| Tree/Graph UI semantics regress | High | Medium | `integration_knowledge_ui_hierarchy` + manual QA | G4 | QA/E2E Validator |
| SDR/Closer consumes ungrounded context | High | Low-Med | `integration_chat_context` scenarios | G5 | QA/Test Engineer |
| No rollback readiness on failure | High | Medium | release checklist review | G6 | QA/E2E Validator |

## 8) Coverage Checklist

- [ ] Graph validation has automated coverage (G1).
- [ ] FAQ-to-Embed rule has automated coverage (G2).
- [ ] Catalog ingest has invalid-case coverage (G3).
- [ ] Tree View and Graph View have behavior coverage (G4).
- [ ] SDR/Closer grounding has scenario coverage (G5).
- [ ] Release blockers are explicit and enforced (G6 + section 5).

## 9) Release Gate Summary (for handoff)

Status model:
- PASS: all G1-G6 gates green with attached evidence.
- FAIL: any gate red -> issue remains blocked for PR/deploy.
- CONDITIONAL: not allowed for BRA-19 due to critical priority.

Handoff rule:
- After QA branch passes all gates, hand off to PR & Deploy Agent.
- QA Lead does not approve release directly; only provides gate decision and risk escalation package.

## 10) Execution Notes for This Heartbeat

- This heartbeat delivers the QA strategy and gate contract for BRA-19.
- Next execution heartbeat should attach real test run outputs and mark final disposition based on gate outcomes.
