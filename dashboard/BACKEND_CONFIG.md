# Frontend -> Backend (AI Brain) configuration

The dashboard talks to the backend through the same-origin prefix `/api-brain/*`.
The Next.js server rewrites that prefix to the local Docker backend at
`API_INTERNAL_BASE_URL`.

```
browser  --> fetch('/api-brain/auth/me') --> Next.js (:3000)
                                               rewrite in next.config.js
                                                      |
                                                      v
                                         API_INTERNAL_BASE_URL
                                                      |
                                                      v
                                         AI Brain backend (:8080)
```

## Default local setup

| Variable | Scope | Value |
|---|---|---|
| `API_INTERNAL_BASE_URL` | server only | `http://localhost:8080` |
| `NEXT_PUBLIC_API_BASE_URL` | browser | `/api-brain` |
Rules:
- Do not expose backend service keys or `OPENAI_API_KEY` to the browser.
- `API_INTERNAL_BASE_URL` stays server-side only.
- The local operational backend is always `http://localhost:8080`.
- The dashboard should not be configured to call the legacy backend directly.

## Local Docker flow

1. `python infra/generate_keys.py --write .env.compose`
2. `docker compose --env-file .env.compose up -d --build`
3. Set `dashboard/.env.local`:
   - `API_INTERNAL_BASE_URL=http://localhost:8080`
   - `NEXT_PUBLIC_API_BASE_URL=/api-brain`
4. `cd dashboard && npm run dev:local`
5. Verify:
   - `curl http://localhost:8080/health`
   - `curl http://localhost:3000/api-brain/health`

## Auth

- For local audit, use the seed admin user from the Docker stack.
- The shared admin token is QA-only and depends on `ENVIRONMENT=qa` inside the backend container.
