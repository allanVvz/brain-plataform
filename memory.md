# Brain Platform Memory

Updated: 2026-06-28

## Current Direction

- The repository is being moved to a local-first/self-hosted stack.
- Supabase Cloud, Cloud Run and other SaaS runtime dependencies should not be required for local operation.
- The database is local Postgres in Docker (`brain-db`) exposed on `localhost:54322`.
- A local Supabase-compatible gateway remains as a compatibility layer, using Nginx + PostgREST on `localhost:54321`; it is not Supabase Cloud.
- Dashboard runs on `localhost:3000`; API runs on `localhost:8000`.

## Authentication And Privacy

- Login is handled by local `app_users` and signed HTTP-only session cookies.
- Persona access is controlled through `user_persona_access`.
- Non-admin users must only see personas assigned to them.
- Admin users can see all personas.
- Sofia/KB intake sessions now store `user_id`; another user cannot read or mutate a session they do not own.
- OpenAI and Anthropic credentials are user-managed integrations stored encrypted in `user_integration_connections`.
- Model calls use the logged-in user's OpenAI/Anthropic credential first, with server env vars only as fallback.
- API keys must never be exposed through `NEXT_PUBLIC_*` or browser payloads.

## Local Validation Results

Created validation users:

- `privacy-a@brain.local` with access only to `baita-conveniencia`.
- `privacy-b@brain.local` with access only to `tock-fatal`.

Validated:

- A sees only `baita-conveniencia`.
- B sees only `tock-fatal`.
- A requesting `tock-fatal` returns 403.
- B requesting `baita-conveniencia` returns 403.
- A can load graph data for `baita-conveniencia`.
- A cannot load graph data for `tock-fatal`.
- Non-admin access to global pipeline/log endpoints returns 403 where appropriate.
- Sofia session created by A returns 200 for A and 403 for B.
- Per-user model config was tested with fake-shaped credentials and then removed.

## Current Stack Commands

- Start local stack: `docker compose up -d --build`
- Check stack: `docker compose ps`
- API health: `GET http://localhost:8000/health/ready`
- Dashboard login: `http://localhost:3000/login`

## Known Fragilities

- The worktree contains a broad local-first refactor and is not a small isolated patch.
- Runtime artifacts in `.codex-run/` are local logs/PIDs and should not be committed.
- The local schema has shown historical drift, for example references to `messages.Lead_Stage`.
- Some global operational tables still exist by design; route-level filtering/admin gates are required when returning them.
- Fake-shaped provider credentials can pass local shape validation; real provider validation would require live network/API calls.

## Recent Verification

- Python syntax checks passed for modified backend modules.
- `npm run build` passed for the dashboard.
- Docker stack was rebuilt and was running after validation:
  - `brain-api`
  - `brain-dashboard`
  - `brain-db`
  - `brain-postgrest`
  - `brain-supabase-gateway`

## Graph JSON v2 Integration Slice - 2026-06-28

- Integrated the first local-first slice from `origin/study-branch-state-audit-20260628` into `study-merge-local-first-sofia-qa`.
- Added Graph JSON v2 schema, canonical validator, local draft/version store, importer, `/graph-documents/*` routes, dashboard API clients and `dashboard/lib/graph-json-v2.ts`.
- Security corrections applied during integration:
  - Reads use `auth_service.assert_persona_access(... persona_slug=...)`.
  - Writes require admin or `user_persona_access.can_edit=true`.
  - Request `persona_slug` must match `graph_json.persona_slug`.
  - Published payload is revalidated before event persistence and v1 materialization.
- Current implementation is intentionally parallel to v1: published v2 docs are stored as `system_events`; draft/apply-patch versions are local files under `data/graph_documents`; v1 `knowledge_nodes/knowledge_edges` remain the serving fallback.
- Validation run:
  - `PYTHONDONTWRITEBYTECODE=1 api/.venv/Scripts/python.exe -m py_compile ...` passed for the new/changed backend files.
  - `PYTHONDONTWRITEBYTECODE=1 api/.venv/Scripts/python.exe -m pytest tests/test_graph_json_v2_integration.py -q` passed: 6 tests.
  - `npm run build` in `dashboard/` passed.
- Remaining integration risk: the full Sofia/CRIAR Graph JSON v2 loop from `study-branch-state-audit-20260628` still has large overlaps in `kb_intake_service.py`, `assets.py`, `knowledge.py`, `graph.py`, migrations 039-046, product import, QA contract routes, and dashboard graph/capture UI. Bring these in by feature slices, not as one merge.

## Sofia Graph Tab Integration - 2026-06-28

- Integrated Sofia side panel into `/knowledge/graph` from `origin/study-branch-state-audit-20260628`.
- Graph tab now attempts Graph JSON v2 by default (`NEXT_PUBLIC_GRAPH_JSON_V2 !== "0"`) and falls back to v1 `/knowledge/graph-data` when no v2 document is published.
- Added local-first `/sofia/graph-command` backend route with session/plan_json response, persona access guard, visual patch commands, confirm and undo support.
- Dashboard API now has compatibility methods used by the restored Graph UI: `getGraphDocument`, `publishGraphDocument`, `sofiaGraphCommand`.
- Validation run:
  - `api/.venv/Scripts/python.exe -m pytest tests/test_graph_json_v2_integration.py -q` passed: 9 tests.
  - `py_compile` for `sofia_graph.py`, `graph_documents.py`, `main.py` passed.
  - `npm run build` in `dashboard/` passed.
  - `docker compose up -d --build` rebuilt/restarted `brain-api`.
  - Real API checks with login cookie passed:
    - `GET /health/ready` -> 200.
    - `POST /auth/login` with local admin -> 200.
    - `GET /graph-documents/current?persona_slug=baita-conveniencia` -> 200.
    - `POST /sofia/graph-command` -> 200 with visual patch + `plan_json`.
  - Real dashboard route `GET http://localhost:3000/knowledge/graph` after login -> 200.
- Remaining limitation: Sofia Graph route is deterministic/local-first and does not yet pull the full `qa_contract.py` + `sofia_orchestrator.py` LLM/tool orchestration from the audit branch.
