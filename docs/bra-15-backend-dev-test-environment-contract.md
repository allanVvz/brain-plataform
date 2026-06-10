# BRA-15 Backend Dev/Test Environment Contract (VZ Lupas E2E)

Date: 2026-05-25
Owner: Backend Engineer
Architecture Reviewer: CTO / System Architect

## Non-Production Confirmation

- This contract is valid only for non-production environments.
- Runtime guard enforces this: QA contract routes return `403` in production runtime.
- Approved target environments:
1. Local Docker backend: `http://localhost:8080`
2. Temporary QA backend: an approved public HTTPS endpoint that forwards to the Docker backend when Vercel needs external access.

## Base URL and Route Prefix Contract

Both route families are mounted and valid:
1. Canonical: `<BASE_URL>/<route>`
2. Legacy alias: `<BASE_URL>/api/<route>`

Required route mapping:
1. `/qa/reset-destructive` and `/api/qa/reset-destructive`
2. `/catalog/ingest` and `/api/catalog/ingest`
3. `/graph/generate` and `/api/graph/generate`
4. `/graph/validate` and `/api/graph/validate`
5. `/faq/approve` and `/api/faq/approve`
6. `/embeds/generate` and `/api/embeds/generate`
7. `/sdr/ask` and `/api/sdr/ask`

## Auth Contract

- Calls must pass backend auth/session middleware.
- Caller must have persona access to `vzlupas`.
- Unauthorized persona access must return `403` without data leakage.

Operational auth guidance for E2E preflight:
1. Login endpoint: `POST <BASE_URL>/auth/login` (not under `/api` alias).
2. Required login body:
   - `identifier` (email or username)
   - `password`
   - `remember` (optional bool)
3. Successful login sets HTTP-only session cookie `ai_brain_session`.
4. QA route calls must include that cookie (`Cookie: ai_brain_session=...`) or use a session-capable HTTP client.
5. Session validation probe: `GET <BASE_URL>/auth/me` must return `200` before destructive/contract calls.

Example sequence (local Docker):
1. `POST http://localhost:8080/auth/login`
2. `GET http://localhost:8080/auth/me`
3. `POST http://localhost:8080/qa/reset-destructive`

## Persona Scope Contract

- `/qa/reset-destructive` is restricted to `persona_slug="vzlupas"`.
- Any different slug is rejected with `403`.
- Route is destructive only when `confirm=true`; otherwise returns dry-run metadata.

## Validation and Safety Contract

1. Catalog ingest creates drafts only:
- `/catalog/ingest` persists pending knowledge items.
- `content_type="embed"` rows are rejected (`rejected_embed_rows`).
- No embeddings are generated in ingest.

2. FAQ approval gate:
- `/faq/approve` only accepts FAQ knowledge items.
- Non-FAQ approval returns `400`.

3. Embedding gate:
- `/embeds/generate` only accepts FAQ nodes in approved states.
- Unapproved FAQ must return `409` with explicit error.
- Direct Product -> Embed path is blocked by route validation.

## Expected Error Semantics for E2E

1. `403`: production runtime usage, wrong persona slug, or unauthorized persona access
2. `400`: invalid type/contract input (example: non-FAQ in FAQ approve)
3. `409`: semantic state conflict (example: unapproved FAQ to embed)
4. `422`: referenced entity not found/invalid

## Verification Snapshot

- Route mapping verified in-process on 2026-05-25:
  all required endpoints exist in both canonical and `/api` forms.
- Guard behavior and embed gate covered by existing backend tests:
1. `tests/test_qa_contract_route_mapping.py`
2. `tests/test_qa_contract_routes.py`

Recovery verification (2026-05-26):
- Route mapping re-verified by importing `api/main.py` and asserting both canonical and `/api` paths.
- Result: `MISSING []` and `OK True`.
- Note: `pytest` is not installed in this local environment (`python -m pytest` unavailable), so this recovery heartbeat used direct runtime route inspection as minimal proof.

## Architecture Decision Record (ADR-BRA-15)

1. AI Brain backend remains the validation and embedding owner.
2. Catalog ingest remains a source of commercial data only (draft intake), not an embedding owner.
3. Graph validation is a hard gate before FAQ approval and embed generation in this contract flow.
4. This contract is approved for BRA-8/BRA-10 E2E against non-production only.

## Final Disposition

- Issue BRA-15 final status: `done` (CTO/System Architect handoff complete).
- Acceptance intent met: agreed backend preflight contract no longer resolves as route `404` for required endpoints under canonical and `/api` prefixes.

## Status Reconciliation (Paperclip Board)

Date: 2026-05-26
Owner: CEO / Product Owner

- If board state still shows `blocked`, treat it as stale status drift.
- Unblock owner/action: Issue owner updates tracker state to `done` using this document as closure evidence.
- No open technical blocker remains inside BRA-15 scope.

## CEO / Product Owner Addendum (MVP Release Intent)

Date: 2026-05-26
Owner: CEO / Product Owner
Applies to: BRA-8, BRA-10, BRA-15 E2E scope for VZ Lupas

### MVP Decision

- AI Brain owns validation, graph traceability, FAQ approval, and embed generation gates.
- Catalog remains an upstream commercial data source only and does not directly create embeddings.
- The VZ Lupas destructive E2E contract is a release blocker for MVP confidence and must remain non-production scoped.

### Prioritized Scope (P0 -> P2)

1. P0: Stable non-prod backend contract with no route `404` on required flow endpoints.
2. P0: FAQ approval gate before `/embeds/generate`, enforced at API level.
3. P0: Persona-scoped destructive reset limited to `persona_slug="vzlupas"`.
4. P1: Consistent error semantics (`400/403/409/422`) for SDR/Closer and QA automation reliability.
5. P1: Route compatibility for canonical and `/api` prefixes during transition.
6. P2: Additional observability and richer preflight diagnostics beyond current acceptance.

### Explicit Out-of-Scope for v1

- Any production runtime destructive reset capability.
- Direct Catalog -> Embed generation path.
- New graph schema/table expansion for this issue.
- Multi-persona destructive reset in a single run.
- Customer-facing AI behavior using unapproved knowledge.

### Success Metrics

1. Preflight route availability: 100% required route resolution on agreed contract paths in QA/local.
2. Validation safety: 0 successful embed generations from non-approved FAQ content.
3. Scope safety: 0 successful destructive reset calls outside `persona_slug="vzlupas"`.
4. E2E reliability: BRA-8/BRA-10 preflight does not fail due to missing route mapping.

### Acceptance Criteria for Downstream Agents

1. Backend contract doc stays aligned with actual mounted routes (canonical + `/api`).
2. `/faq/approve` rejects non-FAQ payloads with contract-compliant error.
3. `/embeds/generate` rejects unapproved FAQ with `409`.
4. `/qa/reset-destructive` rejects non-`vzlupas` persona with `403`.
5. Any contract drift must be updated in this document before closing dependent issues.

### Handoff Notes to CTO / System Architect

- Preserve the hard rule: only approved FAQ nodes can generate embeddings.
- Keep AI Brain/Catalog ownership boundary explicit in route-level and workflow-level decisions.
- If any future request changes graph structure, route the change to Tree/Data Architect review before implementation.


## CTO Architecture Package (BRA-15)

### Stack Decision Record (SDR-BRA-15)

- Preserve stack: Next.js (Vercel) + FastAPI (`/api`) + local Postgres/pgvector data plane + n8n orchestration.
- No migration approved in BRA-15 scope because route-availability and safety gates are solvable in current architecture.
- Rollback strategy remains route-level: keep canonical and `/api` aliases active during transition.

### Service Boundary Map

1. Dashboard (Next.js/Vercel)
- Owns UI orchestration and authenticated operator actions.
- Must not bypass backend gates for FAQ approval or Embed generation.

2. AI Brain API (FastAPI/Docker)
- Owns contract enforcement, persona authorization, graph validation gates, FAQ approval, and embed publishing.
- Owns destructive QA reset guard and non-production enforcement.

3. Local Postgres data plane (Supabase-compatible services + pgvector)
- Owns persistence and retrieval of knowledge/graph state.
- Must reflect approved knowledge in graph nodes/edges before embed generation.

4. Catalog ingest source
- Owns upstream commercial source payload only.
- Must not own embeddings, approval, or validated intelligence lifecycle.

### Data Ownership Map

- Validated intelligence owner: AI Brain (`knowledge_*`, `knowledge_nodes`, `knowledge_edges`, embed publication path).
- Source commercial data owner: Catalog ingest payload (`/catalog/ingest` intake only).
- Authorization owner: backend session/auth middleware + persona access filter.
- QA destructive lifecycle owner: backend QA contract route with `persona_slug="vzlupas"` restriction.

### Endpoint Contract Outline (v1)

1. `POST /qa/reset-destructive`
- Purpose: Reset QA persona-scoped test state for destructive E2E.
- Hard gates: non-production runtime, `persona_slug="vzlupas"`, explicit `confirm=true`.

2. `POST /catalog/ingest`
- Purpose: intake drafts from catalog source.
- Hard gates: reject direct embed content path.

3. `POST /graph/generate`
- Purpose: materialize/refresh graph representation from knowledge state.

4. `POST /graph/validate`
- Purpose: validate graph/tree constraints before downstream approval/embed steps.

5. `POST /faq/approve`
- Purpose: approve FAQ knowledge for publication eligibility.
- Hard gates: FAQ-only input.

6. `POST /embeds/generate`
- Purpose: publish embedding artifacts from approved FAQ.
- Hard gates: approved FAQ required; block all other node types/approval states.

7. `POST /sdr/ask`
- Purpose: execute SDR/closer conversational flow using approved/authorized context.

### Sequenced Implementation Breakdown

1. Stabilize contract surface
- Keep both canonical and `/api` route families mounted.
- Add/maintain route-mapping test coverage.

2. Enforce safety gates
- Validate persona scope on destructive reset.
- Enforce FAQ-only approve and approved-FAQ-only embed constraints.

3. Lock data-flow boundaries
- Keep Catalog as draft intake only.
- Require graph validation before publish path.

4. Verify QA E2E readiness
- Preflight must prove all required routes resolve without `404`.
- Confirm contract error semantics for `400/403/409/422`.

5. Transition management
- Preserve legacy alias compatibility until dependent clients remove `/api` dependency.

### Risk List and Validation Plan

1. Risk: contract drift between docs and mounted routes.
- Validation: route table introspection + `tests/test_qa_contract_route_mapping.py`.

2. Risk: accidental production destructive execution.
- Validation: runtime production guard returning `403`.

3. Risk: unauthorized persona data exposure.
- Validation: backend auth + persona scope checks returning `403` without data leakage.

4. Risk: bypass of FAQ approval prior to embed.
- Validation: `/embeds/generate` approval-state gate (`409` on unapproved FAQ).

5. Risk: catalog source becoming implicit embedding owner.
- Validation: `/catalog/ingest` rejects embed rows and emits boundary evidence.

### Specialist Handoff Instructions

1. Tree/Data Architect
- Review any future graph-structure or relation-type changes before implementation.

2. Graph Validator + Migration Agent
- Own validation logic hardening and any migration work needed for constraint enforcement.
- No new table creation without explicit approval and reuse-first review.

3. Backend Agent
- Implement/maintain route contracts and runtime gates.
- Keep canonical + `/api` compatibility until formal deprecation decision.

4. Frontend Agent
- Consume backend contract via `dashboard/lib/api.ts` only.
- Never implement frontend-only approval/embed safety checks as substitutes for backend enforcement.

5. AI/Catalog Agents
- Keep FAQ approval and embed generation inside AI Brain authority.
- Keep catalog actions limited to source intake and structured draft creation.

6. QA Lead
- Gate PR/deploy on route preflight, contract error semantics, and persona-scoped destructive reset checks.
