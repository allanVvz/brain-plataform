# BRA-21 Official Real Knowledge Seed Path (QA)

Date: 2026-05-26

## Objective

Provide one backend-owned, non-production-only path that seeds real QA knowledge for `persona_slug=vzlupas` while preserving graph and embed guards:

- catalog ingest creates drafts only;
- FAQ approval is explicit;
- embed generation only runs from approved FAQ nodes;
- every sensitive step writes audit events.

## Contract Status

- This document describes the initial QA route contract (`v1`) constrained to `persona_slug=vzlupas`.
- Current architecture decision for unblock is documented in:
  - `docs/qa/BRA-21-cto-unblock-contract-2026-05-26.md`
- `v2` must resolve canonical persona from `persona_ref` (slug/normalized slug/id) to avoid environment slug drift.

## Route

- `POST /seed/official-real`
- Also available as legacy-prefixed route: `POST /api/seed/official-real`

## Request Body

```json
{
  "persona_slug": "vzlupas",
  "source_ref": "qa_official_seed_v1",
  "limit_products": 9
}
```

## Execution Flow

1. Loads fixture `tests/fixtures/vzlupas-products-9.json`.
2. Creates draft `knowledge_items` (product + faq pairs).
3. Approves only FAQ entries (`promote_knowledge_item(..., promote_to_kb=false)`).
4. Rebuilds graph for persona.
5. Publishes approved FAQ nodes through `publish_approved_node(require_rag_for_faq=true)`.
6. Rebuilds graph again and returns counts/evidence.
7. Writes audit events:
   - `faq_approved_for_embed`
   - `embed_generated_from_approved_faq`
   - `qa_official_real_seed_executed`

## Safety Gates Enforced

- Disabled in production runtime.
- Restricted to `persona_slug=vzlupas`.
- No direct Product -> Embed publication path.
- No unapproved FAQ -> Embed publication.

## Example (local Docker QA)

```bash
curl -X POST "http://localhost:8080/api/seed/official-real" \
  -H "Content-Type: application/json" \
  -H "X-AI-BRAIN-ADMIN-TOKEN: $AI_BRAIN_ADMIN_TEST_TOKEN" \
  -d '{"persona_slug":"vzlupas","source_ref":"qa_official_seed_v1","limit_products":9}'
```
