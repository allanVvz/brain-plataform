# BRA-21 CTO Unblock Contract (2026-05-26)

Date: 2026-05-26  
Issue: BRA-21  
Role: CTO / System Architect

## Acknowledged Blocker

Current QA contract is restricted to `persona_slug="vzlupas"` while QA data and access are operating on `vz-lupas`.  
Result: official seed path cannot be executed end-to-end in QA with the available authorized token.

## Technical Architecture Decision

1. Preserve stack and ownership:
- Keep FastAPI + Supabase + Cloud Run + Next.js/Vercel as-is.
- AI Brain remains the owner of validated knowledge and embedding publication.
- Catalog remains draft/intake source only.

2. Contract decision:
- Replace strict single-literal persona gate with canonical persona resolution.
- Accept `persona_ref` in QA contract input, where `persona_ref` may be slug, normalized slug, or persona UUID.
- Resolve server-side to one canonical `persona_id` before any graph/approval/embed action.

3. Safety invariants stay mandatory:
- No Product -> Embed direct flow.
- No unapproved FAQ -> Embed.
- Graph validation before persistence/publication transitions.
- Audit events required for every promotion/publication step.

## Service Boundary Map

- `api/routes/qa_contract.py`: orchestration-only; no hardcoded business data assumptions beyond non-prod scope.
- `api/services/supabase_client.py`: canonical persona lookup/resolution.
- `api/services/knowledge_lifecycle.py`: draft -> approved transitions.
- `api/services/approved_knowledge_snapshots.py`: FAQ-approved-only embed publication.
- `api/services/knowledge_graph.py`: graph rebuild and evidence counts.

## API Contract Draft (v2)

`POST /api/seed/official-real`

Request:
```json
{
  "persona_ref": "vz-lupas",
  "source_ref": "qa_official_seed_v1",
  "run_id": "paperclip-qa-graph-2026-05-26-<unique>",
  "limit_products": 9
}
```

Response (minimum evidence):
```json
{
  "ok": true,
  "persona_id": "<uuid>",
  "persona_slug": "vz-lupas",
  "run_id": "...",
  "draft_items_created": 18,
  "faqs_approved": 9,
  "embeds_generated": 9,
  "graph_counts_before_embed": {"nodes": 0, "edges": 0},
  "graph_counts_after_embed": {"nodes": 0, "edges": 0},
  "node_ids": [],
  "edge_ids": [],
  "events": []
}
```

Negative contracts:
- Product -> Embed returns `409` with explicit guard reason.
- FAQ unapproved -> Embed returns `409` with explicit guard reason.

## Implementation Sequence (Delegated)

1. Backend Engineer:
- Implement persona resolver in QA contract path (`persona_ref` -> canonical persona).
- Remove strict literal `vzlupas` gate; keep non-prod and auth scope gate.
- Ensure runId is accepted/persisted in event payloads and response.

2. Tree/Data Architect:
- Confirm canonical slug policy (`vz-lupas` as stored slug) and normalization behavior for backward compatibility.

3. Graph Validator + Migration Agent:
- Validate no schema break; if alias support is needed, prefer metadata/lookup strategy before new tables.
- Verify graph/edge evidence completeness in API response.

4. Backend Engineer (execution pass):
- Execute official positive flow and both negative flows in QA.
- Persist evidence artifact with IDs, counts, statuses, endpoints used.

5. QA Lead:
- Gate check on evidence completeness before release progression.

## Risk List

1. Hidden slug drift across environments can re-break QA contracts.
2. Token persona scope mismatch may still block execution even after route fix.
3. Incomplete evidence fields can fail acceptance even with successful seed.
4. Over-hardcoded QA fixtures can create false positives for graph integrity.

## Validation Plan

1. Preflight:
- Resolve `persona_ref` and echo canonical `persona_id/persona_slug`.
- Reject unauthorized persona with `403` and no leakage.

2. Positive:
- Full seed path executes with unique `run_id` prefix `paperclip-qa-graph-2026-05-26`.
- FAQ approval recorded before embed publication.
- Node/edge IDs and before/after counts returned and stored.

3. Negative:
- Product -> Embed blocked with expected error.
- Unapproved FAQ -> Embed blocked with expected error.

4. Audit:
- Events include runId and actor metadata for replayability.

## Final Disposition For This Heartbeat

`blocked` remains correct for BRA-21 until Backend Engineer applies the contract fix and re-runs the official flow.

Named unblock owner and action:
- Owner: Backend Engineer (issue assignee)
- Action: implement `persona_ref` canonical resolution and execute BRA-21 evidence run using official API path.
