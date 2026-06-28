# BRA-16 Frontend Graph Render-State QA Route Contract (VZ Lupas)

Date: 2026-05-26  
Issue: BRA-16  
Owner: CTO / System Architect
Product Sign-off: CEO / Product Owner

## 1) Technical Architecture Decision

- Keep current stack and boundaries:
  - Frontend QA route in Next.js: `dashboard/app/api/qa/graph-render-state/route.ts`
  - Graph source in AI Brain backend (FastAPI + Supabase graph tables), fetched via `/knowledge/graph-data`
  - No schema migration, no new table, no Catalog-owned embedding path.
- AI Brain remains source of validated intelligence.
- Catalog remains source of commercial input only; it does not own embedding generation.

## 2) FrontendBaseUrl + Route Contract

- Non-production FrontendBaseUrl (QA): `https://baita-cardapio-qa.vercel.app`
- Route path: `GET /api/qa/graph-render-state`
- Full validation URL:
  - `https://baita-cardapio-qa.vercel.app/api/qa/graph-render-state?tenant=qa-vz-lupas&personaSlug=vzlupas`

## 3) Auth and Request Requirements

- Required query params:
  - `tenant` (string)
  - `personaSlug` (string, expected `vzlupas` for BRA-10 validation flow)
- Required header:
  - `Authorization: Bearer <token>`
- Deployment protection requirement:
  - QA frontend is Vercel SSO-protected; request must come from authenticated browser session or valid bypass/share access before route JSON can be evaluated.

## 4) Response Contract (Route-Level)

Success (`200`) shape must include:

- `ok: true`
- `visible: boolean`
- `graph.nodeCount: number`
- `graph.edgeCount: number`
- `counts.productGroups: number`
- `counts.products: number`
- `assertions.nonEmpty: boolean`
- `assertions.expectedProductGroups: boolean` (`counts.productGroups === 3`)
- `assertions.expectedProducts: boolean` (`counts.products === 9`)

Error envelopes:

- `400` when query params are missing (`missing_required_query`)
- `401` when `Authorization` header is missing (`missing_authorization`)
- `502` when backend cannot be reached (`backend_unreachable`)
- Upstream passthrough status for backend response failures (`backend_error`)

## 5) Data Ownership and Service Contract Outline

- Frontend route ownership:
  - Responsibility: contract normalization and QA assertion surface.
  - No graph truth authored in frontend.
- Backend ownership:
  - `/knowledge/graph-data` is canonical graph read contract used by route.
  - Graph truth comes from `knowledge_nodes` and `knowledge_edges`.
- Graph/business rule ownership:
  - Tree layout and protected-node semantics remain governed by existing graph rules in `AGENTS.md`.
  - No BRA-16 permission to alter graph category/relation semantics.

## 6) Implementation Sequence (Applied for BRA-16)

1. Confirm route implementation in `dashboard/app/api/qa/graph-render-state/route.ts`.
2. Confirm backend QA contract routes are mounted (`/qa/*` and `/api/qa/*`) via mapping tests.
3. Execute non-prod reachability test (`!=404`) against QA frontend route.
4. Run authenticated BRA-10 preflight and capture `3/9` and empty-state evidence.
5. Promote BRA-16 to completion once QA Lead attaches evidence.

## 7) QA Release Gates (Must Pass Before QA Promotion)

- Gate A (Reachability): route responds and is not `404`.
- Gate B (Rebuild counts): `counts.productGroups=3`, `counts.products=9`, both expected assertions true.
- Gate C (Empty-state): explicit non-visible/non-empty signaling in empty graph scenario.

## 8) Risks and Validation Plan

Risks:

- Vercel SSO protection can mask route-level status (401/403 before app logic).
- Missing runtime auth token can fail before backend graph fetch.
- Environment drift in QA data can break `3/9` assertions.

Validation plan:

- Use authenticated QA session (or approved bypass/share access).
- Invoke contract URL with bearer auth.
- Store request/response evidence for:
  - populated graph scenario
  - empty graph scenario

## 9) Specialist Handoff Instructions

- Tree/Data Architect:
  - Review only if follow-up requests require graph node/edge category or hierarchy changes.
- Graph Validator + Migration Agent:
  - Validate any future contract-impacting graph persistence changes before deploy.
- Backend Agent:
  - Own `/knowledge/graph-data` contract stability and persona-scoped auth behavior.
- Frontend Agent:
  - Maintain route response envelope and assertion fields used by BRA-10.
- QA Lead / Environment Owner:
  - Execute authenticated runbook and attach non-404 + `3/9` + empty-state evidence.

## 10) Current Heartbeat Verification Notes

- Route file exists and matches expected contract:
  - `dashboard/app/api/qa/graph-render-state/route.ts`
- Backend QA contract router exists:
  - `api/routes/qa_contract.py`
- Local test execution blocker on this machine:
  - `python -m pytest ...` failed with `No module named pytest`
  - This is an environment dependency blocker for local test execution, not a route contract design blocker.

## 11) QA Evidence Template (Attach to BRA-16 / BRA-10)

Use this exact template in the issue comment when running authenticated QA validation.

```text
Environment:
- Date/Time (UTC):
- FrontendBaseUrl: https://baita-cardapio-qa.vercel.app
- Persona: vzlupas
- Auth mode: (SSO session | bypass/share URL) + Bearer token present

Gate A - Reachability (!=404):
- Request: GET /api/qa/graph-render-state?tenant=qa-vz-lupas&personaSlug=vzlupas
- Status code:
- Result: PASS/FAIL

Gate B - Rebuild Counts (3/9):
- visible:
- graph.nodeCount:
- graph.edgeCount:
- counts.productGroups:
- counts.products:
- assertions.expectedProductGroups:
- assertions.expectedProducts:
- Result: PASS/FAIL

Gate C - Empty-State Contract:
- Scenario setup:
- visible:
- assertions.nonEmpty:
- Result: PASS/FAIL

Final:
- BRA-10 preflight 404 resolved: YES/NO
- Close recommendation for BRA-16: DONE / NEEDS-FIX
```
## 12) Product Acceptance Criteria (MVP Close Gate)

BRA-16 is product-complete only when all criteria below are true:

1. AI Brain ownership is preserved:
- Contract validates AI Brain graph render-state behavior.
- No Catalog-owned embedding or validation path is introduced.

2. FAQ approval safety boundary is preserved:
- No change is made to the rule that only approved FAQ nodes can generate embeddings.

3. QA functional proof is attached in issue evidence:
- Gate A PASS: route reachable and not `404`.
- Gate B PASS: rebuilt graph assertions pass (`3 product groups`, `9 products`).
- Gate C PASS: empty-state behavior is explicit and contract-compliant.

4. Release intent for BRA-10 dependency is satisfied:
- BRA-10 preflight no longer fails on frontend route mapping for render-state validation.

## 13) Release Intent Summary

- Intent: unblock VZ Lupas E2E validation path in non-production with a stable, auditable frontend contract.
- Non-goal: production release changes, graph model redesign, or embedding pipeline redesign.
- Closure decision rule:
  - Mark BRA-16 `done` when QA evidence template is completed with PASS on Gate A/B/C.
  - Keep BRA-16 `in_review` when awaiting QA evidence collection.

