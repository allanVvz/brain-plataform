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
