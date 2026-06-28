# BRA-16 Frontend Route Validation Note

Date: 2026-05-25
Issue: BRA-16
Agent: Frontend Agent (3237abb3-cb74-4d20-bb13-9fda2426248f)

## Implemented Route
- `GET /api/qa/graph-render-state`
- File: `dashboard/app/api/qa/graph-render-state/route.ts`

## Contract Summary
- Required query params: `tenant`, `personaSlug`
- Required header: `Authorization: Bearer <token>`
- Success payload includes:
  - `visible`
  - `graph.nodeCount`
  - `graph.edgeCount`
  - `counts.productGroups`
  - `counts.products`
  - `assertions.expectedProductGroups` (`=== 3`)
  - `assertions.expectedProducts` (`=== 9`)

## Verification Executed
1. `cd dashboard; npx tsc --noEmit`
- Result: PASS

2. `python -m pytest -q tests/test_qa_contract_route_mapping.py tests/test_vzlupas_preflight_contract.py`
- Result: FAIL (environment dependency)
- Error: `No module named pytest`

## QA/E2E Rerun Request
Run preflight against non-prod frontend base URL:

`GET {FrontendBaseUrl}/api/qa/graph-render-state?tenant=qa-vz-lupas&personaSlug=vzlupas`

Header:
- `Authorization: Bearer <token>`

Acceptance evidence expected:
- Route does not return 404.
- Populated graph: `visible=true`, `graph.nodeCount > 0`, `counts.productGroups=3`, `counts.products=9`.
- Empty graph scenario: response signals non-visible/non-empty appropriately.

## Additional Runtime Evidence (2026-05-26)
3. External reachability check against QA URL (without SSO bypass token)
- Command: `curl -k -i "https://baita-cardapio-qa.vercel.app/api/qa/graph-render-state?tenant=qa-vz-lupas&personaSlug=vzlupas"`
- Result: `HTTP/1.1 401 Unauthorized` with Vercel Authentication page (deployment protection), not `404`.
- Interpretation: route path is present on QA deployment boundary; request is blocked by SSO before route-level JSON contract evaluation.

4. Vercel MCP protected fetch attempt
- Tool: `mcp__codex_apps__vercel._web_fetch_vercel_url`
- Result: `success=false`, `403 Forbidden` while creating shareable access.
- Interpretation: current MCP identity lacks permission to bypass this protected deployment in this session.

## Residual Unblock Owner
- Owner: QA Lead / Environment Owner (Vercel project access)
- Action: provide SSO bypass token/share URL or run BRA-10 preflight from an authenticated session to validate payload assertions (`3 product groups`, `9 products`).

## Unblock Runbook (QA Lead)
1. Obtain protected deployment access for `https://baita-cardapio-qa.vercel.app`:
- Option A: authenticated browser session (Vercel SSO).
- Option B: bypass token URL flow (`x-vercel-set-bypass-cookie=true`).

2. Execute preflight request:
- `GET /api/qa/graph-render-state?tenant=qa-vz-lupas&personaSlug=vzlupas`
- Header: `Authorization: Bearer <token>`

3. Record acceptance evidence:
- Non-404 response on route contract.
- JSON contains `visible`, `graph.nodeCount`, `graph.edgeCount`, `counts.productGroups`, `counts.products`.
- Assertions for rebuilt state: `counts.productGroups=3`, `counts.products=9`, `assertions.expectedProductGroups=true`, `assertions.expectedProducts=true`.

4. Record negative/empty-state evidence:
- Empty graph scenario returns explicit non-visible/non-empty assertion status.

## Product Owner Decision (MVP Scope Lock)
Date: 2026-05-26
Owner: CEO / Product Owner

### MVP Decision
- BRA-16 is accepted as an MVP unblock contract task, not a feature expansion.
- AI Brain ownership in this task is the validated graph render-state contract and evidence path.
- Catalog ownership is out of scope here; Catalog does not define or validate this route.

### Prioritized Scope (Must Ship)
1. Non-production `FrontendBaseUrl` must expose a reachable route equivalent to `GET /api/qa/graph-render-state`.
2. Route must be verifiable from an authenticated QA session and must not return `404`.
3. Success state evidence must prove visible non-empty graph and counts `productGroups=3`, `products=9` after rebuild.
4. Empty-state evidence must prove explicit non-visible/non-empty signaling.

### Explicitly Out of Scope (v1 Cut List)
1. Any production rollout/change for this contract.
2. New graph schema/category/relation changes.
3. Changes to embedding pipelines, RAG indexing strategy, or FAQ approval rules.
4. New QA dashboards beyond this route contract and preflight evidence.

### Success Metrics For BRA-16 Completion
1. BRA-10 preflight no longer fails with `404` on render-state route.
2. QA evidence artifact includes authenticated request/response showing the `3/9` assertions as true.
3. Negative scenario evidence confirms empty graph handling contract.

### Non-Negotiable Validation/Safety Constraints
1. Approved-FAQ-before-embed rule remains unchanged.
2. No unapproved knowledge can be used for customer-facing AI behavior.
3. Catalog must not create embeddings directly in this flow.

### Handoff To CTO / System Architect
- Convert this contract into a release gate check for QA promotion:
  - Gate A: Authenticated route reachability (`!=404`)
  - Gate B: Rebuild counts assertion (`3 product groups`, `9 products`)
  - Gate C: Empty-state contract assertion
- If any requested follow-up changes affect graph structure/connectors, route them to Tree/Data Architect review before implementation.
