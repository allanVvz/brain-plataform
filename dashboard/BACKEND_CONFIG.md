# Frontend → Backend (AI Brain) configuration

The dashboard never calls the backend host directly from the browser. Every
browser request goes to the **same-origin relative prefix** `/api-brain/*`, and
the Next.js server rewrites it to the real backend. This avoids CORS and keeps
the backend URL (and any secret) out of the browser bundle.

```
browser  ──fetch('/api-brain/auth/me')──►  Next.js (:3000)
                                              │  rewrite in next.config.js
                                              ▼
                                    API_INTERNAL_BASE_URL  (server-only)
                                              │
                                              ▼
                                    AI Brain backend (Docker :8080)
```

`Server: uvicorn` on a `/api-brain/*` response is **expected** — it is the
backend's header passed back through the proxy. It does NOT mean a FastAPI/uvicorn
process is bound to :3000. (Native Next routes like `/dashboard` carry no
`Server` header.)

## Environment variables

| Variable | Scope | Purpose | Example |
|---|---|---|---|
| `API_INTERNAL_BASE_URL` | **server only** (private) | rewrite target for `/api-brain/*` | `http://localhost:8080` |
| `NEXT_PUBLIC_API_BASE_URL` | browser | the relative proxy prefix | `/api-brain` |
| `NEXT_PUBLIC_SUPABASE_URL` / `_PUBLISHABLE_KEY` | browser | `@supabase/ssr` client (anon only) | cloud Supabase |

Rules:
- The browser can only read `NEXT_PUBLIC_*`. Never put `SERVICE_ROLE_KEY`,
  `SUPABASE_SERVICE_KEY` or `OPENAI_API_KEY` in a `NEXT_PUBLIC_*` var.
- `API_INTERNAL_BASE_URL` has **no** `NEXT_PUBLIC_` prefix on purpose — it stays
  server-side and is never shipped to the browser.
- Legacy `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_AI_BRAIN_URL` are still honored as a
  fallback for the rewrite target, but `API_INTERNAL_BASE_URL` takes precedence.

Resolution order for the rewrite target (`next.config.js`):
`API_INTERNAL_BASE_URL` → `NEXT_PUBLIC_API_URL` → `NEXT_PUBLIC_AI_BRAIN_URL` →
(dev) `http://localhost:8080` / (prod, unset) `http://127.0.0.1:9` (fails fast).

## Option A — Local development (recommended)

Frontend on `localhost:3000` consuming the Docker backend on `localhost:8080`.

```bash
# 1. backend stack
docker compose --env-file .env.compose up -d
docker compose --env-file .env.compose ps        # api must be healthy on 8080

# 2. dashboard env (dashboard/.env.local)
#    API_INTERNAL_BASE_URL=http://localhost:8080
#    NEXT_PUBLIC_API_BASE_URL=/api-brain

# 3. dashboard
cd dashboard
npm run dev:local        # next dev -p 3000

# 4. (first run) seed a login user in the Docker DB
docker compose --env-file .env.compose exec api \
  python scripts/create_auth_user.py --email admin@local.dev --username admin \
  --password admin123 --role admin --persona baita-conveniencia --can-edit --can-manage
```

> Env vars are read at server start. After editing `.env.local`, restart `next dev`.

## Option B — Vercel Preview consuming your local Docker

Vercel runs in the cloud, so `localhost` / `host.docker.internal` from a Vercel
function do **not** reach your machine. You must expose the local backend with a
public tunnel:

```bash
cloudflared tunnel --url http://localhost:8080
# or
ngrok http 8080
```

Then set on the Vercel project (Preview env):

```
API_INTERNAL_BASE_URL=https://<your-tunnel-url>
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

The browser still calls `/api-brain/*`; the Vercel function rewrites to the tunnel.
CORS is avoided because the browser only ever sees the same-origin Vercel domain.

## Option C — Real production

Run the backend on a public host (VPS with the Docker stack behind TLS, or Cloud
Run) and point the rewrite at it:

```
API_INTERNAL_BASE_URL=https://api.seudominio.com
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

For self-hosted assets to render, Kong/Storage must also be reachable on a public
HTTPS domain (see `infra/README.md`, gotcha #2). `localhost` is never valid for
external users in production.

## Tests

```bash
cd dashboard
npm run test:api-health       # GET http://localhost:8080/health -> 200
npm run test:frontend-proxy   # GET :3000/api-brain/health -> 200, /auth/me -> 200|401
```

Port sanity (Windows):

```powershell
netstat -ano | findstr :3000   # must be Next.js (node.exe)
netstat -ano | findstr :8080   # must be the Docker API
```
