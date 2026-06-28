# BRA-16 Architecture Contract - Frontend Graph Render-State QA Route

Date: 2026-05-25  
Owner: CTO / System Architect  
Issue: BRA-16 (dependency for BRA-10 E2E preflight)

## Decision
Preserve current stack and expose QA graph render-state validation through Next.js route handler:

- Frontend contract route: `GET /api/qa/graph-render-state`
- Runtime owner: `dashboard` (Next.js on Vercel)
- Data source owner: `api` (`/knowledge/graph-data` in FastAPI/Docker)
- Intelligence authority: AI Brain graph (`knowledge_nodes` + `knowledge_edges`), not Catalog

This keeps frontend preflight stable while backend remains source of validated graph truth.

## Environment Boundary
- Non-prod `FrontendBaseUrl` for BRA-10: `https://baita-cardapio-qa.vercel.app`
- QA deployment is Vercel SSO-protected; preflight runner must use authenticated access (Vercel bypass/share token path where needed).
- Backend target for QA must resolve through `API_INTERNAL_BASE_URL` to an approved backend URL.

## Contract (Request/Response)
Request:
- Method: `GET`
- Path: `/api/qa/graph-render-state`
- Query required: `tenant`, `personaSlug`
- Header required: `Authorization: Bearer <token>`

Response `200` fields required by BRA-10:
- `visible`
- `graph.nodeCount`
- `graph.edgeCount`
- `counts.productGroups`
- `counts.products`
- `assertions.expectedProductGroups` (must be `true` for VZ Lupas rebuilt state = 3)
- `assertions.expectedProducts` (must be `true` for VZ Lupas rebuilt state = 9)

Error handling:
- `400` missing query contract
- `401` missing auth header
- `502` backend unreachable
- passthrough upstream non-2xx as backend error

## Data Ownership Map
- Catalog: source of commercial candidates only; no embedding ownership.
- AI Brain backend: validates and serves graph truth.
- Frontend QA route: read-only adapter for E2E contract checks; no persistence.

## Risks and Validation Plan
Risks:
- QA SSO can be mistaken for route regression (false 401/403/404 signals).
- Wrong backend env mapping (`API_INTERNAL_BASE_URL`) can point to the wrong backend or local fallback.
- Persona mismatch can produce empty graph and fail 3/9 assertions.

Validation:
1. Confirm route reachable on QA base URL (non-404).
2. Confirm auth path accepted (Bearer token present).
3. Confirm populated state for `personaSlug=vzlupas`: `visible=true`, `productGroups=3`, `products=9`.
4. Confirm empty-state behavior remains explicit (`visible=false` / non-empty assertion false) when graph has no nodes.

## Specialist Handoff
- Tree/Data Architect: no schema change requested; confirm node type normalization coverage for `product_group`.
- Graph Validator + Migration Agent: validate rebuilt VZ Lupas graph cardinality upstream (3 groups / 9 products).
- Backend Agent: keep `/knowledge/graph-data` contract stable for layered mode.
- Frontend Agent: keep route contract backward-compatible for BRA-10 preflight.
- QA Lead: execute BRA-10 preflight against QA URL with SSO-aware access and attach evidence.
