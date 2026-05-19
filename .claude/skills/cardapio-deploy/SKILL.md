---
name: cardapio-deploy
description: Deploy the baita-cardapio Vite frontend to Vercel — production from main branch or QA preview aliased to baita-cardapio-qa.vercel.app from the qa branch. Use when the baita-cardapio code changed or when the AI-BRAIN backend URL changed and the frontend needs a rebuild to pick up the new VITE_AI_BRAIN_API_URL.
---

# cardapio-deploy

Deploys the public Baita Cardapio frontend to Vercel.

## Targets

| mode | branch | URL | env scope |
|---|---|---|---|
| `prod` | `main` (baita-cardapio repo) | https://baita-cardapio.vercel.app | Vercel production env |
| `qa` | `qa` (baita-cardapio repo) | https://baita-cardapio-qa.vercel.app (SSO active) | Vercel preview env, branch=qa |

The Vercel project is `allanvvzs-projects/baita-cardapio` and is linked to GitHub `allanVvz/Card-pio`.

## Pre-flight

1. The baita-cardapio repo is cloned at `../baita-cardapio` relative to this repo (or set `CARDAPIO_DIR` env var).
2. Vercel CLI authenticated (`vercel whoami` returns `allanvvz`).
3. One-time env setup already done (skip if already in place):

   For prod:
   ```bash
   cd ../baita-cardapio
   printf "https://ai-brain-api-837167469397.us-central1.run.app\n" | vercel env add VITE_AI_BRAIN_API_URL production
   ```

   For qa:
   ```bash
   printf "https://ai-brain-api-qa-837167469397.us-central1.run.app\n" | vercel env add VITE_AI_BRAIN_API_URL preview qa
   ```

## How to run

```bash
# Production
bash scripts/cardapio-deploy.sh prod

# QA preview (aliases to https://baita-cardapio-qa.vercel.app)
bash scripts/cardapio-deploy.sh qa
```

The script:

- Validates branch matches the target (warns if not, asks confirmation).
- Runs `vercel deploy --prod --yes` for prod, or `vercel deploy --yes` + `vercel alias set ... baita-cardapio-qa.vercel.app` for qa.
- Curls the public URL for a HEAD check.

## QA preview SSO

The QA alias `baita-cardapio-qa.vercel.app` has Vercel Authentication active. To access from a browser without Vercel login, ask Claude to call `mcp__vercel__get_access_to_vercel_url` and use the returned `_vercel_share=...` query string.

## When do I need to redeploy the frontend?

- The cardapio code changed.
- The AI-BRAIN API URL changed (rare — only if Cloud Run service name changed).
- `VITE_AI_BRAIN_API_URL` env was edited via `vercel env`.

You do NOT need to redeploy the frontend when only the AI-BRAIN backend code changes — Cloud Run serves the new payload on the same URL and the SPA picks it up via TanStack Query polling (15s refresh).

## Related

- `deploy-prod` — backend prod. Usually runs first; cardapio-deploy only if the frontend itself changed.
- `deploy-qa` — backend QA.
- `smoke-check` — backend health; cardapio-deploy verifies frontend HTTP only.
