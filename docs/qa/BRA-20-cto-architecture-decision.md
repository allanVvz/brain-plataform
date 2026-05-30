# BRA-20 CTO Architecture Decision and Execution Sequence

Date: 2026-05-26
Owner: CTO / System Architect
Issue: BRA-20

## 1) Technical Architecture Decision

Decision: keep the current stack and enforce the BRA-20 graph insertion contract as a backend-validated, QA-verifiable fixture package.

- Backend API (FastAPI on Cloud Run) remains the single write authority for node/edge persistence.
- Supabase Postgres remains persistence source; no schema expansion in this step.
- Graph rendering contract remains split by mode:
  - `semantic_tree` consumes only active `main` edges.
  - `all_edges=1` consumes active `main` + `reference` edges.
- Embed publication remains gated by FAQ approval (`faq.status=approved`) and must never accept direct Product-to-Embed flow.
- Catalog remains data source only; AI Brain remains validated intelligence owner.

Rationale:
- Satisfies project constraints without migration risk.
- Preserves governance rule: validation before persistence/embedding generation.
- Keeps QA objective executable with deterministic outcomes.

## 2) Stack Decision Record

- Preserve: Next.js + Vercel frontend, FastAPI + Cloud Run backend, Supabase Postgres/pgvector, n8n support flows.
- Reject for BRA-20 scope:
  - frontend-only validation;
  - direct DB writes for fixture acceptance;
  - new tables unless Graph Validator requests and board approves.

## 3) Data Ownership Map

- Catalog ingest ownership:
  - Produces candidate content and metadata with source trace.
  - Cannot persist approved embed/KB state directly.
- AI Brain backend ownership:
  - Validates node payload shape.
  - Validates allowed edge matrix and embed guards.
  - Persists accepted nodes/edges and emits validation/audit evidence.
- QA ownership:
  - Executes fixture/negative cases through API.
  - Asserts persistence + endpoint visibility criteria.

## 4) API and Service Contract Outline

Authoritative contract inputs are:
- `docs/qa/BRA-20-validation-contract.json`
- `docs/qa/BRA-20-tree-data-architecture-brief.md`

Backend service obligations for BRA-20:
- Reject invalid main edges with stable error codes:
  - `EMBED_SOURCE_NOT_FAQ`
  - `FAQ_NOT_APPROVED_FOR_EMBED`
  - plus structural invariants already listed in contract.
- Guarantee rejection means no edge persistence.
- Guarantee accepted writes return persisted IDs.
- Guarantee `/knowledge/graph?mode=semantic_tree&all_edges=1&persona_slug=vz-lupas` reflects accepted fixture path.

## 5) Implementation Sequence (Specialist Handoff Order)

1. Tree/Data Architect (completed for BRA-20)
- Freeze fixture hierarchy, edge matrix, and negative cases.

2. Graph Validator + Migration Agent
- Map contract invariants to guardrails.
- Confirm no destructive migration and no new-table requirement.
- Keep soft-disable policy for edge removals (`metadata.active=false`) when applicable.

3. Backend Engineer
- Enforce contract at API layer with stable rejection payloads.
- Ensure write path is transactional for node/edge persistence + validation events.

4. QA Test Engineer / Graph Test Driver
- Execute positive fixture and both negative cases.
- Validate insertion criteria: persisted node IDs, persisted edge IDs, endpoint visibility, and rejected-edge non-persistence.

5. QA Lead
- Apply release gate using BRA-20 evidence pack before PR/deploy progression.

## 6) Risk List and Validation Plan

Risks:
- R1: Drift between documented edge matrix and runtime validator.
- R2: Error-code instability breaks automated QA assertions.
- R3: Semantic tree computed with reference edges, violating tree invariants.
- R4: FAQ status gate bypass enables invalid Embed publication.

Controls:
- C1: Contract-first tests tied to exact error codes.
- C2: Endpoint-level assertion on `semantic_tree` for canonical depth/parent rules.
- C3: Negative-case checks confirm blocked edges are absent from persistence.
- C4: QA gate must fail if any BRA-20 contract assertion fails.

## 7) Acceptance Gate for This Issue

BRA-20 is architecturally complete when all are true:
- Fixture + invariants are documented in machine-readable and human-readable contract artifacts.
- Ownership and service boundaries are explicitly assigned.
- Execution order and QA gate are explicitly assigned to specialist agents.
- No forbidden direct Product->Embed path is allowed in any contract section.

## 8) Specialist Agent Handoff Instructions

- Tree/Data Architect:
  - Keep node/edge taxonomy canonical and aligned with AGENTS.md business rules.
- Graph Validator + Migration Agent:
  - Implement guardrails without schema growth unless explicitly approved.
- Backend Engineer:
  - Implement validation enforcement and stable API error contract.
- Frontend Agent:
  - Consume backend validation responses; do not replace backend checks with UI rules.
- QA Lead:
  - Block promotion if fixture acceptance criteria are unmet in QA evidence.

