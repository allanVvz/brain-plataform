# BRA-17 Backend Dev/Test Route Contract (VZ Lupas E2E)

Date: 2026-05-25

## Environment Scope

- Non-production only.
- Guard: `is_production_runtime()` blocks these routes with `403`.
- Persona destructive scope: `persona_slug` must be `vzlupas` for reset flow.

## Base URL (dev/test)

- Local/dev default: `http://localhost:8000`
- Legacy E2E compatibility prefix is also mounted: `http://localhost:8000/api`

Both route sets are active:
- `/qa/reset-destructive` and `/api/qa/reset-destructive`
- `/catalog/ingest` and `/api/catalog/ingest`
- `/graph/generate` and `/api/graph/generate`
- `/graph/validate` and `/api/graph/validate`
- `/faq/approve` and `/api/faq/approve`
- `/embeds/generate` and `/api/embeds/generate`
- `/sdr/ask` and `/api/sdr/ask`

## Auth Guidance

- Uses existing backend auth middleware.
- Use an admin/operator token with persona access to `vzlupas`.
- In local dev, session-authenticated dashboard calls are accepted via existing middleware path.

## Route Contract Mapping

1. `POST /qa/reset-destructive`
- Body: `{ "persona_slug": "vzlupas", "confirm": false }`
- Expected:
  - `200` dry-run when `confirm=false`
  - `200` executes dev/test destructive reset when `confirm=true`
  - `403` outside non-production or wrong persona

2. `POST /catalog/ingest`
- Body: `{ "persona_slug": "vzlupas", "entries": [...] }`
- Expected:
  - `200` with draft creation summary
  - `400` if `entries` missing
- Boundary:
  - `embed` rows are rejected (`rejected_embed_rows`)
  - returns `catalog_boundary` confirming ingest creates drafts only

3. `POST /graph/generate`
- Body: `{ "persona_slug": "vzlupas" }`
- Expected:
  - `200` with `counts` from graph rebuild

4. `POST /graph/validate`
- Body: `{ "graph": {...}, "tree_edge_ids": [...] }` (optional payload; defaults available)
- Expected:
  - `200` with `{ ok, checks, errors }` validation payload
  - No 404 for preflight

5. `POST /faq/approve`
- Body: `{ "persona_slug": "vzlupas", "knowledge_item_id": "..." }`
- Expected:
  - `200` with approval evidence
  - `400` if content is not FAQ
  - `422` if `knowledge_item_id` missing in DB

6. `POST /embeds/generate`
- Body: `{ "persona_slug": "vzlupas", "faq_node_id": "..." }`
- Expected:
  - `200` with publication evidence
  - `409` when FAQ is not approved
  - `400` when node is not FAQ
  - `422` when faq node does not exist
- Safety:
  - explicit guard: `Unapproved FAQ -> Embed is impossible`

7. `POST /sdr/ask`
- Body: LeadEvent-like payload with `mensagem` and `persona_slug=vzlupas`
- Expected:
  - `200` with process result wrapper

## Explicit Safety Confirmations

- FAQ -> Embed gate: enforced (`/embeds/generate` rejects unapproved FAQ with `409`).
- Direct Product -> Embed is impossible under this contract route surface.
- Catalog boundary: ingest creates pending drafts and never creates Embed directly.

## Audit Events

Contract flow writes audit events in `system_events`, including:
- `qa_reset_destructive_executed`
- `faq_approved_for_embed`
- `embed_generated_from_approved_faq`
