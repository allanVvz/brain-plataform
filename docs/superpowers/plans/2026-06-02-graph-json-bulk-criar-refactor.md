# Graph JSON Bulk Criar Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sofia Criar produce, validate, preview, and persist one canonical graph JSON document atomically, while preserving the structured MD document workflow.

**Architecture:** The Create chat remains conversational, but its output becomes a canonical `GraphJson` document before any graph persistence happens. The backend validates the full document, asks Sofia/operator clarification on invalid structure, and imports the whole document in one service call that writes vault MD, `knowledge_items`, `knowledge_nodes`, `knowledge_edges`, and optional RAG/Embedded artifacts coherently. The frontend renders the document preview in one pass and never creates graph nodes one by one.

**Tech Stack:** FastAPI, PostgREST/Supabase local Docker, Next.js dashboard, React Flow, Pydantic schemas, pytest, Vitest.

---

## Context Snapshot

- Running backend branch validated locally: `feat/docker-self-hosted-stack`, commit `03fd33a`, image `ai-brain-backend:local`, API container healthy on `:8080`.
- Docker local schema has the critical tables: `knowledge_items`, `knowledge_nodes`, `knowledge_edges`, `knowledge_rag_entries`, `knowledge_rag_chunks`, `kb_entries`, `sofia_plan_sessions`, `knowledge_artifacts`, `knowledge_artifact_versions`, `system_events`.
- QA remote project visible through Supabase MCP: `svkogegypdqquzlfzaor`, Postgres 17.6. Docker local is Postgres 15.8.
- Data inconsistency found:
  - Docker local: `knowledge_nodes=43`, `knowledge_edges=101`, `knowledge_items=12`, `knowledge_rag_entries=0`, `knowledge_rag_chunks=0`, `kb_entries=0`.
  - QA remote: `knowledge_nodes=135`, `knowledge_edges=379`, `knowledge_items=33`, `knowledge_rag_entries=18`, `knowledge_rag_chunks=18`, `kb_entries=0`.
  - QA has orphan-risk in primary tree: `audience` has 3 nodes without incoming primary edge, `campaign` has 2. Docker local has 1 `knowledge_item` node without incoming primary edge.
- Current `/kb-intake/save` writes each plan entry as a file and persists each `knowledge_item` one by one, then best-effort applies hierarchy. This is the wrong failure boundary for the new requirement.
- Current `GraphJson` schema/validator is MVP and does not yet match `ai_brain_regras_negocio_grafo.md`; it lacks `copy`, `rule`, `offer`, flexible briefing positions, FAQ lowest-node priority, and approved-only FAQ -> Embedded rules.
- MD flow must be preserved: grouped FAQ markdown is an intentional document node, not many FAQ cards. Existing tests cover this behavior.

## File Structure

- Modify: `api/schemas/graph_json_v2.py`
  - Own the canonical graph document payload shape.
  - Add fields needed for MD documents, source lineage, validation status, branch path, and import metadata.
- Modify: `api/services/graph_json_v2_validator.py`
  - Enforce `ai_brain_regras_negocio_grafo.md`.
  - Validate a whole graph document before persistence.
- Create: `api/services/graph_json_importer.py`
  - Convert a validated `GraphJson` document into durable DB rows and vault files in a single orchestrated import.
  - This service is the only place that materializes Graph JSON into `knowledge_items`, `knowledge_nodes`, and `knowledge_edges`.
- Modify: `api/routes/graph_documents.py`
  - Add `POST /graph-documents/import-json`.
  - Keep existing current/publish endpoints, but route import through the new importer.
- Modify: `api/services/kb_intake_service.py`
  - Convert normalized Sofia plan to Graph JSON before save.
  - Replace direct item-by-item graph persistence with `graph_json_importer.import_graph_json`.
  - Keep vault MD writing, but under importer control.
- Modify: `api/services/knowledge_graph.py`
  - Keep low-level helpers, but stop using `apply_plan_hierarchy` as the main Create persistence path.
  - Retain it only for legacy repair/import compatibility.
- Modify: `dashboard/app/knowledge/capture/page.tsx`
  - Preview and save `graph_json`, not `normalized_plan` entries as the persistence source.
  - Keep structured MD preview and grouped FAQ rendering.
- Modify: `dashboard/app/knowledge/graph/GraphPageClient.tsx`
  - Consume imported/published Graph JSON as one render payload.
  - Do not issue node/edge create calls for Sofia Criar output.
- Modify: `dashboard/lib/graph-json-v2.ts`
  - Parse canonical Graph JSON including MD document nodes and validation metadata.
- Test: `tests/test_graph_json_validator.py`
  - Add canonical business-rule cases.
- Test: `tests/test_graph_json_importer.py`
  - Add atomic import contract using fake Supabase client.
- Test: `tests/test_kb_intake_graph_json_save.py`
  - Add save contract: Sofia plan -> Graph JSON -> importer, no item-by-item graph persistence.
- Test: `tests/e2e_criar_faq_golden_dataset_by_branch.py`
  - Preserve grouped FAQ MD behavior.
- Test: `dashboard/__tests__/GraphPageClient.test.tsx`
  - Confirm Graph JSON preview renders all nodes/edges in one pass.

---

### Task 1: Align Graph JSON Schema With Business Rules

**Files:**
- Modify: `api/schemas/graph_json_v2.py`
- Modify: `tests/test_graph_json_validator.py`

- [ ] **Step 1: Add failing schema coverage for MD and branch metadata**

Add a test payload with:
- `schema_version: "2.0"`
- node types: `persona`, `brand`, `campaign`, `briefing`, `audience`, `product_group`, `product`, `copy`, `rule`, `faq`, `embedded`
- a grouped FAQ node with `data.markdown_document=true`, `data.markdown`, `data.question_count`, `data.validation_status="pending_validation"`
- no `faq -> embedded` edge while FAQ is pending.

Run:

```powershell
python -m pytest tests/test_graph_json_validator.py -q
```

Expected: FAIL because the current validator does not accept the full rule set.

- [ ] **Step 2: Extend schema models**

Update `Node.data` contract by convention, not new DB tables:

```python
class Node(BaseModel):
    id: str
    node_type: str
    slug: str
    label: str
    parent_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
```

Keep the model flexible, but require the validator to check:
- `source`
- `status` or `validation_status`
- `branch_path` for FAQ
- `source_node_id` / `source_node_type` when FAQ is derived from a lower node
- `markdown_document=true` for grouped FAQ documents.

- [ ] **Step 3: Run validator tests**

Run:

```powershell
python -m pytest tests/test_graph_json_validator.py -q
```

Expected: PASS after Task 2 updates validator rules.

### Task 2: Rewrite Graph JSON Validator to Match `ai_brain_regras_negocio_grafo.md`

**Files:**
- Modify: `api/services/graph_json_v2_validator.py`
- Test: `tests/test_graph_json_validator.py`

- [ ] **Step 1: Encode allowed parent rules**

Use the business-rule parent sets:

```python
CANONICAL_PARENT = {
    "brand": ("persona",),
    "campaign": ("brand", "briefing"),
    "briefing": ("brand", "campaign"),
    "audience": ("campaign", "briefing"),
    "product_group": ("audience",),
    "product": ("product_group",),
    "offer": ("product", "product_group"),
    "copy": ("product", "product_group", "offer"),
    "rule": ("campaign", "briefing", "brand", "persona"),
    "faq": ("copy", "product", "product_group", "audience", "briefing", "campaign", "brand", "persona", "rule"),
    "embedded": ("faq",),
    "gallery": ("persona",),
    "asset": ("product", "product_group", "campaign", "brand", "gallery"),
}
```

- [ ] **Step 2: Add whole-document rules**

Validate:
- exactly one persona node;
- every non-protected node has one primary path to persona;
- no `persona -> embedded`;
- no non-FAQ source to Embedded;
- FAQ can target Embedded only when approved/validated;
- if Copy exists below a product/group, FAQ must be below Copy or Rule, not parallel;
- if Product exists below Product Group, FAQ cannot hang from Product Group unless grouped/general metadata explicitly says it is scoped to the group and not product-specific;
- no orphan node, no cycle, no duplicate `(node_type, slug)`;
- every primary edge must mirror `target.parent_id`.

- [ ] **Step 3: Preserve grouped FAQ MD**

Add validator acceptance for:

```python
faq.data["markdown_document"] is True
faq.data["question_count"] > 1
faq.node_type == "faq"
```

This means one FAQ node can hold many questions in markdown. Do not require one node per question.

### Task 3: Build Graph JSON Importer

**Files:**
- Create: `api/services/graph_json_importer.py`
- Test: `tests/test_graph_json_importer.py`

- [ ] **Step 1: Write failing atomic import test**

Test that a valid graph JSON:
- validates before writes;
- writes all vault files;
- persists all `knowledge_items`;
- creates/updates all `knowledge_nodes`;
- creates/updates all primary `knowledge_edges`;
- returns one import report.

Mock the Supabase client so a failure during node/edge import proves no “success” is returned.

- [ ] **Step 2: Implement importer boundary**

Create:

```python
def import_graph_json(*, graph_json: GraphJson, source: str, session_id: str | None = None) -> dict:
    ...
```

Required behavior:
- call validator first;
- build a deterministic import plan;
- persist entries in stable topological order;
- collect node IDs by Graph JSON ID;
- create primary edges only after all nodes exist;
- never create a graph without at least one primary connection from each non-root node;
- return `ok=False` with validator errors before any write when invalid.

- [ ] **Step 3: Preserve MD document writes**

For nodes with `data.markdown`:
- write/update the vault MD file;
- persist `knowledge_items.content`;
- preserve `metadata.markdown_document`, `metadata.question_count`, `metadata.branch_path`;
- do not split grouped FAQ questions into multiple nodes.

### Task 4: Convert Sofia Normalized Plan to Graph JSON Before Save

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Create or modify helper in `api/services/graph_json_importer.py`
- Test: `tests/test_kb_intake_graph_json_save.py`

- [ ] **Step 1: Add plan-to-graph-json test**

Use an existing normalized plan with:

```text
Persona -> Brand -> Campaign -> Briefing -> Audience -> Product Group -> Product -> Copy -> FAQ
```

Assert:
- returned Graph JSON has all nodes at once;
- every non-persona node has `parent_id`;
- every parent relation has a `primary_tree=true` edge;
- grouped FAQ remains one node with markdown.

- [ ] **Step 2: Implement converter**

Add:

```python
def normalized_plan_to_graph_json(plan: dict, session: dict) -> GraphJson:
    ...
```

Do not persist inside this function. It is pure conversion.

- [ ] **Step 3: Replace save persistence path**

In `save()`:
- keep classification, confirmation, hash, count validation;
- build `graph_json`;
- validate `graph_json`;
- if invalid, return a structured error that the frontend can show to Sofia;
- call `graph_json_importer.import_graph_json`;
- remove Create dependency on `apply_plan_hierarchy` as the primary persistence path.

### Task 5: Sofia Intervention on Invalid JSON

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Modify: `dashboard/app/knowledge/capture/page.tsx`
- Test: `tests/test_kb_intake_graph_json_save.py`

- [ ] **Step 1: Return clarification payload on invalid Graph JSON**

When graph JSON validation fails, return:

```json
{
  "error_code": "GRAPH_JSON_INVALID",
  "requires_sofia_intervention": true,
  "graph_json_validation": {
    "blocking": ["..."],
    "questions": ["Qual campanha deve ser pai deste público?"]
  }
}
```

- [ ] **Step 2: Frontend routes error back into chat**

In `CaptureWorkspace.save()`, when `GRAPH_JSON_INVALID` appears:
- do not show only generic `Erro: 500`;
- append a Sofia/system message explaining the missing parent or invalid path;
- keep stage before save;
- do not redirect to graph.

### Task 6: Add `POST /graph-documents/import-json`

**Files:**
- Modify: `api/routes/graph_documents.py`
- Test: `tests/test_graph_documents_routes.py`

- [ ] **Step 1: Add route test**

Route accepts:

```json
{
  "persona_slug": "tock-fatal",
  "graph_json": { "...": "..." },
  "source": "kb_intake.save"
}
```

Expected:
- 422 on invalid full graph;
- 200 on valid graph;
- result includes import counts and document version/checksum.

- [ ] **Step 2: Implement route**

Call the importer. Do not create nodes directly in the route.

### Task 7: Frontend One-Pass Preview and Save

**Files:**
- Modify: `dashboard/app/knowledge/capture/page.tsx`
- Modify: `dashboard/lib/graph-json-v2.ts`
- Test: `dashboard/__tests__/GraphPageClient.test.tsx`

- [ ] **Step 1: Preview Graph JSON document**

Replace any preview behavior that derives visible graph from individual frontend node actions with:
- `plan_state.graph_json`
- parsed nodes
- parsed edges
- one React Flow payload.

- [ ] **Step 2: Save Graph JSON**

Change save payload from only:

```ts
{ plan_hash, normalized_plan }
```

to:

```ts
{ plan_hash, normalized_plan, graph_json }
```

Backend remains source of truth; frontend graph_json is advisory unless hash matches.

### Task 8: Regression Tests for MD Structured Creation

**Files:**
- Preserve/extend: `tests/e2e_criar_faq_golden_dataset_by_branch.py`
- Preserve/extend: `tests/e2e_criar_fractal_topdown_tree_integrity.py`
- Preserve/extend: `tests/test_approved_faq_publication_contract.py`

- [ ] **Step 1: Assert grouped FAQ markdown still works**

Required assertions:
- one FAQ node/document for grouped policy;
- markdown contains multiple question headings;
- no internal terms like `node`, `grafo`, `arvore` leak to customer-facing FAQ;
- FAQ starts `pending_validation`;
- no FAQ -> Embedded edge until approval.

- [ ] **Step 2: Assert approval still creates RAG/Embedded**

Approval test must assert:
- approved FAQ creates RAG entry;
- approved FAQ creates RAG chunk;
- approved FAQ connects to Embedded;
- Embedded markdown rebuild includes connected approved FAQs.

### Task 9: Database Consistency Audits

**Files:**
- Create: `api/scripts/audit_graph_consistency.py`
- Test: optional smoke via script output.

- [ ] **Step 1: Add read-only audit script**

Audit:
- nodes without incoming primary edge;
- non-FAQ edges into Embedded;
- pending FAQ connected to Embedded;
- grouped FAQ node split into multiple question nodes;
- knowledge_items without knowledge_node_id;
- QA/Docker count diff.

- [ ] **Step 2: Run against Docker local**

Run:

```powershell
docker compose --env-file .env.compose exec -T api python scripts/audit_graph_consistency.py --persona all
```

- [ ] **Step 3: Run against QA**

Run through configured QA environment or Supabase MCP read-only SQL.

### Task 10: Verification Commands

Run:

```powershell
cd api
python -m pytest tests/test_graph_json_validator.py tests/test_graph_documents_routes.py tests/test_kb_intake_graph_json_save.py tests/test_graph_json_importer.py -q
```

Run:

```powershell
cd dashboard
npm.cmd run test -- GraphPageClient.test.tsx
npm.cmd run build:check
```

Run local Docker smoke:

```powershell
docker compose --env-file .env.compose up -d --build
curl.exe http://localhost:8080/health
```

Acceptance criteria:
- `/marketing/criacao` no longer surfaces generic `Erro: 500 /kb-intake/save`; invalid graph JSON becomes Sofia clarification.
- Sofia Criar save imports the full graph in one backend operation.
- No graph is persisted without primary path to Persona.
- FAQ grouped markdown remains one document node.
- FAQ approval remains the only route to RAG/Embedded.
- Graph page renders imported JSON in one pass.

---

## Self-Review

- Spec coverage: covers JSON generation, import JSON, batch persistence, no disconnected graph, Sofia intervention, database inconsistency audit, and MD preservation.
- Known gap: this plan does not create new tables. It uses existing tables and metadata as required by AGENTS.md.
- Risk: current Graph JSON V2 endpoint stores current published documents through `system_events`, while `apply-patch` uses `graph_json_v2_store`; implementation should reconcile storage behavior before broad rollout.
