# BRA-22 QA Lead Release Gate

## Scope
Issue: BRA-22 - Adicionar teste automatizado que prova insercao real no grafo QA.

Changed artifact under evaluation:
- tests/test_qa_real_graph_insertion.py

## QA Strategy
- Enforce real API integration path (no mocks) as mandatory evidence for graph invariants.
- Treat graph mirroring and edge policy as hard blockers.
- Validate semantic tree exposure because dashboard behavior depends on this data contract.
- Require negative-path assertions for invalid knowledge promotion (Product->Embed and unapproved FAQ->Embed).
- Keep release handoff separated: QA qualifies branch, Release Manager approves release.

## Required Test List (Must Pass)
1. Real ingest creates 3 items with unique run token.
2. Graph rebuild mirrors all 3 items into graph nodes (source_table=knowledge_items + source_id).
3. Product->Embed direct edge creation fails (HTTP 400/409).
4. Unapproved FAQ->Embed edge creation fails (HTTP 400/409).
5. FAQ approval succeeds via /api/faq/approve.
6. Embed generation succeeds only for approved FAQ and returns embedded_edge_id.
7. semantic_tree mode exposes all run-token nodes.

## Coverage Checklist
- Graph validation automated coverage: PASS (implemented in BRA-22 test flow).
- FAQ-to-Embed rule automated coverage: PASS (negative + positive path).
- Catalog ingest invalid-case coverage: PARTIAL (this test validates happy ingest; invalid payload cases remain separate required coverage).
- Tree View and Graph View behavior coverage: PARTIAL (API contract covered via semantic_tree/graph data; UI behavior still requires E2E).
- SDR/Closer grounding scenario coverage: MISSING for BRA-22 scope.
- Explicit release blockers: PASS (defined below).

## Manual QA Checklist
- Confirm dashboard semantic tree renders new run-token nodes after graph rebuild.
- Confirm edge delete action removes edge only, not node, in graph UI.
- Confirm Persona/Embedded/Gallery protected node behavior is unchanged.

## Automated QA Checklist
- Run `python -m py_compile tests/test_qa_real_graph_insertion.py`.
- Run `python -m pytest -q tests/test_qa_real_graph_insertion.py` with:
  - QA_REAL_GRAPH_INSERTION_TEST=1
  - AI_BRAIN_ADMIN_TEST_TOKEN set
  - API_BASE pointing to local API target (default http://localhost:8000)
- Capture raw stdout/stderr and attach to issue evidence.

## Blocking Criteria (Release Gate)
- Block if any required test above fails.
- Block if test is skipped due to missing runtime prerequisites in CI/QA lane.
- Block if semantic_tree no longer exposes the run-token nodes.
- Block if Product->Embed or unapproved FAQ->Embed is accepted.
- Block if approved FAQ fails to produce embedded_edge_id.
- Block if rollback path for deployed backend revision is not documented before promotion.

## QA Agent Assignments
- QA/Test Engineer:
  - Owns automated integration execution for BRA-22 and maintenance of test fixture stability.
  - Adds/updates invalid ingest-case automated tests (payload/schema/required fields).
- QA/E2E Validator:
  - Owns dashboard validation for Tree View/Graph View behavior tied to semantic_tree contract.
  - Verifies edge delete UX preserves nodes and protected node constraints.
- QA Regression Guardian:
  - Adds BRA-22 scenario to regression suite and monitors historical failures around graph mirror and embed policy.
  - Maintains risk registry linkage for future incidents.

## Risk-Based Validation Matrix
- High risk: Graph mirror drift after ingest/generate.
  - Control: required automated assertions on node presence by source_id.
- High risk: Unauthorized knowledge promotion to Embed.
  - Control: negative automated assertions for Product and unapproved FAQ.
- High risk: Contract drift between API and semantic tree consumers.
  - Control: semantic_tree node presence assertion + E2E rendering checks.
- Medium risk: Environment drift hides failures (missing pytest/env/token).
  - Control: explicit prereq checks in QA lane and fail-fast setup.

## Execution Evidence (Current Heartbeat)
- Command: `python -m py_compile tests/test_qa_real_graph_insertion.py`
  - Result: success (no output, exit 0).
- Command: `python -m pytest -q tests/test_qa_real_graph_insertion.py`
  - Result: executed, skipped.
  - Output: `1 skipped in 0.12s`.
- Command: `python -m pytest -q -rs tests/test_qa_real_graph_insertion.py`
  - Result: executed, skipped with explicit reason.
  - Output: `SKIPPED [1] ... Set QA_REAL_GRAPH_INSERTION_TEST=1 to run QA live insertion test.`
- Command: `QA_REAL_GRAPH_INSERTION_TEST=1 python -m pytest -q -rs tests/test_qa_real_graph_insertion.py`
  - Result: executed, skipped with next explicit prerequisite.
  - Output: `SKIPPED [1] ... Set AI_BRAIN_ADMIN_TEST_TOKEN to run QA live insertion test.`

## Blocked State and Unblock Owner
- Current disposition recommendation: BLOCKED (operational).
- Blocker: admin token prerequisite for live API path was not provided in this run, so mandatory real-flow assertions did not execute.
- Unblock owner: QA/Test Engineer.
- Unblock action:
  - export `QA_REAL_GRAPH_INSERTION_TEST=1`
  - export `AI_BRAIN_ADMIN_TEST_TOKEN=<admin token>`
  - ensure local API is up (`API_BASE`, default `http://localhost:8000`)
  - rerun `python -m pytest -q -rs tests/test_qa_real_graph_insertion.py` and attach non-skipped output.

## Handoff
After QA branch passes all blockers above, hand off to PR & Deploy Agent for merge/deploy flow with rollback awareness.
