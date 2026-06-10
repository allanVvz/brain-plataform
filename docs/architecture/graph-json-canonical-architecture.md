# Graph JSON V2 — Canonical Architecture Spec (2026-05-29)

Architecture decision for a JSON-canonical knowledge graph that replaces the current sprawl of `knowledge_nodes`, `knowledge_edges`, `knowledge_rag_*`, `kb_entries` etc. as the source of truth.

Status: **SPEC only. No destructive migration. No removal of existing tables. v1 and v2 run in parallel.**

Cross-ref: `paperclip/agents/CANONICAL_CHAIN.md` (graph law), `paperclip/agents/OPERATING_RULES.md` §9 (memory.md mandate), `paperclip/docs/qa/sofia-tool-use-contract.md` (Sofia tool surface). Tracked by **BRA-umbrella** (this round) with up to 5 subtasks.

---

## 1. Problem statement

Current state, observed across BRA-31 / BRA-43 / BRA-57..71 cycles:

- The knowledge graph is split across `knowledge_nodes`, `knowledge_edges`, `knowledge_rag_entries`, `knowledge_rag_chunks`, `kb_entries`, plus per-table metadata. Sofia, the validator, the frontend, and the catalog ingest each maintain a different mental model.
- The visual graph is wrong because edge parents are inserted in the wrong tables / orders.
- Sofia replies but does not persist cleanly because there are 4 levels of indirection between her patch and the canonical chain.
- Rollback and audit are hard: no single document represents "the graph at version N".
- Frontend, backend and Supabase drift.

## 2. Decision

Move the source of truth to a JSON document **per persona (or per persona+brand pair)** versioned in Supabase. Existing relational tables remain as **derived indices** for query speed and FAQ-to-Embed enforcement.

```
[graph_documents.graph_json]  <— source of truth (versioned)
       │
       ├── derived: graph_node_index
       ├── derived: graph_edge_index
       ├── derived: knowledge_faq_index    ← only approved FAQ
       │       │
       │       └── knowledge_embeddings    ← only from approved FAQ
       │
       └── event log: graph_events  +  graph_versions
```

`v1` (current `knowledge_nodes`/`knowledge_edges`/`knowledge_rag_*`) is preserved and continues to serve existing endpoints. `v2` is added in parallel. Migration is non-destructive and validated against `AllanVvz → VZ Lupas` before any other persona is migrated.

## 3. New Supabase project (optional but recommended)

The user authorized creating a new Supabase project for v2/QA if it reduces risk. Recommended decision: **yes, new project**, because:

- Schema-level isolation prevents accidental writes to the current QA `svkogegypdqquzlfzaor`.
- Allows v2 RLS, roles, and migrations to be designed clean.
- Reverting v2 in QA is a project drop, not a multi-table delete.

Naming convention: v1 QA remains a historical reference. New targets must be documented through `.env.compose.example` or explicit Docker/Vercel environment variables, not through legacy YAML env files.

PROD `slyxppvghniknqofhqzt` is **untouched**.

## 4. Table model

### 4.1 `graph_documents` (source of truth, current published)

| column | type | notes |
|---|---|---|
| `id` | uuid | PK |
| `tenant_id` | text | qa/prod scope |
| `persona_slug` | text | `allanvvz`, `tock-fatal`, etc. |
| `brand_slug` | text NULL | only when document is brand-scoped |
| `graph_type` | text | `semantic_tree` default; reserved for `gallery`, `audit` |
| `status` | text | `draft`, `published`, `archived` |
| `version` | int | monotonic |
| `graph_json` | jsonb | the document (see §5) |
| `checksum` | text | sha256 of canonical-encoded `graph_json` |
| `created_at` / `updated_at` / `published_at` | timestamptz | |
| `created_by` / `updated_by` | text | actor (agent_id or user email) |

Unique constraint: `(tenant_id, persona_slug, brand_slug, graph_type, status='published')` — at most one published document per scope at a time.

### 4.2 `graph_versions` (full history)

| column | type |
|---|---|
| `id` | uuid PK |
| `graph_document_id` | uuid FK → graph_documents.id |
| `version` | int |
| `graph_json` | jsonb |
| `change_summary` | text |
| `created_by` | text |
| `created_at` | timestamptz |

Every publish appends here; rollback is a publish-of-an-old-version.

### 4.3 `graph_events` (patches and audit)

| column | type |
|---|---|
| `id` | uuid PK |
| `graph_document_id` | uuid FK |
| `operation` | text — `reparent_brand`, `create_default_audience`, etc., from the canonical operations enum |
| `patch_json` | jsonb |
| `before_checksum` / `after_checksum` | text |
| `actor` | text |
| `created_at` | timestamptz |

### 4.4 `graph_node_index` (derived from `graph_json.nodes`)

| column | type |
|---|---|
| `id` | uuid PK |
| `graph_document_id` | uuid FK |
| `node_id` | text — internal id from graph_json |
| `node_type` | text — `persona`, `brand`, `briefing`, `campaign`, `audience`, `product_group`, `product`, `faq`, `embedded`, `gallery`, `asset` |
| `slug` | text |
| `label` | text |
| `parent_id` | text NULL |
| `path` | text — materialized path for fast subtree query |
| `data` | jsonb — full node payload |
| `updated_at` | timestamptz |

Index on `(graph_document_id, node_type, slug)` for resolve-node lookups.

### 4.5 `graph_edge_index` (derived)

| column | type |
|---|---|
| `id` | uuid PK |
| `graph_document_id` | uuid FK |
| `edge_id` | text |
| `source` | text — node_id |
| `target` | text — node_id |
| `relation` | text — `persona_has_brand`, `brand_has_briefing`, etc. |
| `updated_at` | timestamptz |

### 4.6 `knowledge_faq_index` (derived, approved only)

| column | type |
|---|---|
| `id` | uuid PK |
| `graph_document_id` | uuid FK |
| `faq_node_id` | text |
| `question` | text |
| `answer` | text |
| `status` | text — must be `approved` to populate this table |
| `approved_at` | timestamptz |

Insertion rule: a row only lands here when the source FAQ in `graph_json` has `status: approved`. FAQ-before-Embed is enforced at this layer.

### 4.7 `knowledge_embeddings` (derived from approved FAQ only)

| column | type |
|---|---|
| `id` | uuid PK |
| `faq_id` | uuid FK → knowledge_faq_index.id |
| `chunk` | text |
| `embedding` | vector(1536) — pgvector |
| `metadata` | jsonb |
| `created_at` | timestamptz |

Insertion rule: a row only lands here when the source FAQ row in `knowledge_faq_index` exists. The chain `FAQ approved → faq_index → embedding` is monotonic and one-way.

### 4.8 `agent_sessions` (Sofia short-term memory)

| column | type |
|---|---|
| `id` | uuid PK |
| `persona_slug` | text |
| `brand_slug` | text NULL |
| `active_node_id` | text NULL |
| `context_json` | jsonb |
| `created_at` / `updated_at` | timestamptz |

TTL 30 min via a periodic delete or an `expires_at` field.

### 4.9 `agent_messages` (conversation history)

| column | type |
|---|---|
| `id` | uuid PK |
| `session_id` | uuid FK |
| `role` | text — `user`, `assistant`, `tool` |
| `content` | text |
| `tool_calls` | jsonb |
| `created_at` | timestamptz |

## 5. `graph_json` schema

```json
{
  "schema_version": "1.0",
  "graph_id": "allanvvz-main",
  "tenant": "qa",
  "persona_slug": "allanvvz",
  "status": "published",
  "nodes": [
    {
      "id": "node:persona:allanvvz",
      "node_type": "persona",
      "slug": "allanvvz",
      "label": "AllanVvz",
      "data": { "...": "..." }
    },
    {
      "id": "node:brand:vz-lupas",
      "node_type": "brand",
      "slug": "vz-lupas",
      "label": "VZ Lupas",
      "parent_id": "node:persona:allanvvz",
      "data": { "...": "..." }
    }
  ],
  "edges": [
    {
      "id": "edge:1",
      "source": "node:persona:allanvvz",
      "target": "node:brand:vz-lupas",
      "relation": "persona_has_brand",
      "primary_tree": true
    }
  ],
  "layout": {
    "engine": "top-down-canonical",
    "positions": { "node:persona:allanvvz": [0, 0], "node:brand:vz-lupas": [0, -120] }
  },
  "validation": {
    "is_valid": true,
    "errors": []
  }
}
```

Pydantic + TypeScript versions of this schema land at `ai-brain/api/schemas/graph_json_v2.py` and `dashboard/lib/graph-json-v2.ts` respectively. Both are generated from a JSON Schema source (`ai-brain/docs/architecture/graph-json-v2.schema.json`) to prevent drift.

## 6. Canonical validation rules

The validator `validate_graph_json` enforces:

- **Chain integrity:** `Persona → Brand → Briefing → Campaign → Audience → Product Group → Product → FAQ → Embedded`. No skips. No reversals.
- **Persona children:** persona accepts only `brand` (+ protected `gallery`, `embedded`) as direct children.
- **Brand children:** only `briefing` and optionally `audience` per the brand's pattern.
- **Briefing → Campaign → Audience → Product Group → Product → FAQ:** strict adjacency in this order.
- **Embedded:** only under FAQ with `status: approved`.
- **No orphan node:** every non-persona node has a parent reachable in `edges`.
- **No cycle:** DAG enforced via topological walk.
- **No duplicate slug within scope:** `(node_type, slug)` is unique per persona.
- **Gallery branch:** Gallery is a separate visual branch under persona; it does not break the main chain. Assets attached to Gallery via `gallery_asset` do not appear in the canonical chain validator.

Validation runs **before publish**. A `graph_json` with `validation.is_valid: false` cannot be published; only saved as `draft`.

## 7. Endpoints v2 (added in parallel; v1 keeps working)

| route | method | purpose |
|---|---|---|
| `/graph-documents/current` | GET | return current published `graph_json` for `(persona_slug[, brand_slug])` |
| `/graph-documents/apply-patch` | POST | accept a `patch_json`, apply against current draft, validate, return draft `graph_json` + diff |
| `/graph-documents/publish` | POST | publish current draft as new version (writes `graph_versions`, increments `version`, reindexes) |
| `/graph-documents/rollback` | POST | take an old `graph_versions` row and re-publish it as a new version |
| `/graph-documents/reindex` | POST | force-refresh derived indices from a `graph_document_id` |
| `/graph-documents/versions` | GET | list versions for an `(persona_slug, brand_slug)` |
| `/graph-documents/events` | GET | list events for a document |

Auth contract is the same as the rest of `/sofia/*` and `/qa/*` routes: `X-AI-BRAIN-ADMIN-TOKEN` or `Authorization: Bearer` per `sofia-tool-use-contract.md` §4.5.

## 8. Read flow (frontend Graph)

1. `GET /graph-documents/current?persona_slug=allanvvz` (with auth header).
2. Receive `graph_json` (nodes + edges + layout).
3. Render React Flow from `nodes` and `edges`; use `layout.positions` if present, otherwise call the canonical top-down layout engine.

No new graph-shape inference on the frontend — the canonical shape is in the JSON.

## 9. Edit flow (Sofia)

1. Receive natural-language command from `SofiaChatPanel`.
2. Call `resolve-persona`, `resolve-node`, `resolve-operation` (existing tools — see `sofia-tool-use-contract.md`).
3. Call `GET /graph-documents/current` to fetch the current published `graph_json`.
4. Generate `patch_json` (RFC 6902-style add/replace/remove or a domain-specific shape — CTO to decide between the two in the decision file).
5. `POST /graph-documents/apply-patch` to compose the draft.
6. Validate via `validate_graph_json`.
7. On user confirm, `POST /graph-documents/publish` → triggers reindex of derived tables.
8. Return diff + updated `graph_json` to the frontend; frontend calls `refetch_graph` and reconciles React Flow.

## 10. Embedding rule (FAQ-before-Embed)

Embeddings are generated **only** from FAQs whose `status: approved` inside `graph_json`. The pipeline is:

```
graph_json.nodes[type=faq, status=approved]
  → reindex hook
    → INSERT INTO knowledge_faq_index
      → embedding worker reads new rows
        → INSERT INTO knowledge_embeddings
```

Catalog products, copy nodes, asset nodes, briefing text — **none** of these generate embeddings directly. Any code path that tries to embed from outside `knowledge_faq_index` is rejected at the backend layer.

## 11. Migration phases (non-destructive)

| phase | action | reversibility |
|---|---|---|
| 1 | Create `graph_documents`, `graph_versions`, `graph_events` (new project or existing) | drop tables |
| 2 | Implement `GET /graph-documents/current` (returns empty if no document exists yet) | remove route |
| 3 | Implement `POST /graph-documents/apply-patch` against in-memory document | remove route |
| 4 | Sofia learns to edit `graph_json` via the new endpoints (BRA-71 chain integration) | revert Sofia to v1 path |
| 5 | Frontend Graph reads `graph_json` when present, falls back to v1 `/knowledge/graph-data` | switch flag |
| 6 | Create derived indices and reindex hook; v1 tables become read-only mirrors | switch flag |
| 7 | Embeddings pipeline reads from `knowledge_faq_index` instead of v1 RAG tables | switch flag |
| 8 | Approve cutover; v1 endpoints documented as legacy | rollback to phase 5 if needed |

Phase 1 + 2 + 3 land first. Phases 4–7 are sequential. Phase 8 is the only hard cutover and requires a separate decision file.

## 12. Validation proof — `AllanVvz → VZ Lupas` first

Migration is validated against a single persona+brand pair before any expansion:

- Convert the current `knowledge_nodes`/`knowledge_edges` subtree of `persona_slug=allanvvz` into a `graph_json`.
- Publish as version 1.
- Run `validate_graph_json` — must pass with the canonical chain rules.
- Run a Sofia patch (e.g. `reencaixe o brand vz lupas abaixo de allanvvz`) — must produce a patch, apply, validate, publish v2.
- Run a frontend read — React Flow must render the same shape that the current dashboard shows.
- Run the FAQ approval pipeline for one product's FAQ — must land in `knowledge_faq_index` and produce one embedding row.
- Capture all of the above as an artifact in `paperclip/test-artifacts/architecture/graph-json-v2-allanvvz-validation-<UTC>.json`.

Only after that artifact is `pass` does any other persona / brand migrate.

## 13. Acceptance criteria (binary; any `no` = reject)

- [ ] This document published in path `ai-brain/docs/architecture/graph-json-canonical-architecture.md` (the file you're reading).
- [ ] Migration SQL written: `ai-brain/supabase/migrations/<timestamp>_graph_json_v2.sql` (new tables; non-destructive).
- [ ] Pydantic schema in `ai-brain/api/schemas/graph_json_v2.py`.
- [ ] TypeScript schema in `dashboard/lib/graph-json-v2.ts`.
- [ ] JSON Schema source in `ai-brain/docs/architecture/graph-json-v2.schema.json`.
- [ ] Validator implemented in `ai-brain/api/services/graph_json_validator.py` with tests.
- [ ] 7 endpoints from §7 registered in `ai-brain/api/routes/graph_documents.py`.
- [ ] Reindex script in `ai-brain/api/scripts/reindex_graph_json.py`.
- [ ] AllanVvz → VZ Lupas conversion script in `ai-brain/api/scripts/import_v1_to_v2_allanvvz.py`.
- [ ] Tests covering: create json, apply patch, validate chain, publish, rollback, reindex, FAQ-before-embed.
- [ ] Artifact at `paperclip/test-artifacts/architecture/graph-json-v2-allanvvz-validation-<UTC>.json` with disposition `pass`.
- [ ] `ai-brain/memory.md` and `paperclip/memory.md` updated.

## 14. Rejection criteria (auto-reject)

- Document without migration SQL.
- Schema without `validate_graph_json` implementation.
- Migration that drops or alters existing v1 tables.
- Migration without `graph_versions` (no rollback path).
- Endpoints removed instead of added in parallel.
- Embedding from anything other than `knowledge_faq_index`.
- AllanVvz/VZ Lupas validation skipped or partial.
- Artifact in `.paperclip/instances/...` or workspace stub.
- Done without `memory.md` update (per `OPERATING_RULES.md §9` hard mandate, 2026-05-29 reinforcement).

## 15. Subtask plan (max 5 under the umbrella)

| BRA | Owner | Scope |
|---|---|---|
| umbrella | CTO / System Architect | Architecture decisions, optional new Supabase project, validate this document |
| sub-1 | Backend Engineer | Migration SQL + endpoints + validator + reindex script |
| sub-2 | Frontend Agent | `graph_json` read path + React Flow render from `nodes`/`edges`/`layout` |
| sub-3 | AI Agent Engineer | Sofia edits `graph_json` via patch endpoints; keeps tool-use loop |
| sub-4 | Graph Validator + Migration Agent / QA | Import `AllanVvz → VZ Lupas`, run end-to-end validation, produce artifact |

Umbrella starts `blocked`; CTO sub-decision lands first (Supabase project yes/no, patch shape RFC 6902 vs domain). When CTO publishes the decision file under `paperclip/docs/architecture/`, sub-1 unblocks, then sub-2/3 in parallel, then sub-4.

## 16. Notes for the validator

The validator (`claude/local-board`) treats this spec as **architecture-only** until phase 7 lands. Until then, no `done` on the umbrella issue is accepted. The umbrella closes when phase 7 artifacts exist in the published path AND the AllanVvz/VZ Lupas validation artifact is `pass` AND `memory.md` is updated in both repos AND the cutover decision file (if reached) exists under `paperclip/docs/architecture/`.

Non-destructive guarantee holds: at any point during phases 1–7, the existing dashboard, Sofia, and the v1 graph endpoints continue to function unchanged.
