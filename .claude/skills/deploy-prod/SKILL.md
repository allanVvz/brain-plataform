---
name: deploy-prod
description: Promote ai-brain from develop to main and deploy the PROD Cloud Run service. Use when the user wants to ship QA changes to production. The script enforces gates (clean tree, develop pushed, QA smoke green, service_role JWT in env.yaml) and aborts on any failure. After main is fast-forwarded and gcloud run deploy completes, validates with a PROD smoke-check.
---

# deploy-prod

Promotes the current `develop` branch to `main` and deploys it to the production Cloud Run service `ai-brain-api`.

## Pre-flight gates (the script enforces all of these — refuses to proceed if any fail)

1. `env.yaml` exists with `SUPABASE_SERVICE_KEY` carrying a `role:service_role` JWT, not anon. The script decodes the JWT payload and aborts otherwise. *(Anon key causes `/api/menu` to return 404 "Persona not found" because RLS blocks the read.)*
2. Working tree clean (`git status --porcelain` returns empty).
3. Local `develop` == `origin/develop` (you pushed everything).
4. **QA smoke-check passes** (`scripts/smoke-check.sh qa`). Never promote a broken QA.

## How to run

```bash
bash scripts/deploy-prod.sh
```

Sequence:

1. Validate env.yaml has the service_role JWT.
2. Validate tree + push state.
3. Run QA smoke-check.
4. `git checkout main && git pull --ff-only origin main`.
5. `git merge --no-ff develop -m "merge develop -> main (deploy-prod <UTC>)"`.
6. `git push origin main`.
7. `gcloud run deploy ai-brain-api --source ./api --region us-central1 --allow-unauthenticated --env-vars-file env.yaml`.
8. PROD smoke-check.
9. `git checkout develop` (back to QA branch for the next iteration).

Takes ~5-8 minutes total.

## env.yaml format (PROD)

```yaml
SUPABASE_URL: "https://slyxppvghniknqofhqzt.supabase.co"
SUPABASE_SERVICE_KEY: "<service_role JWT — NOT anon — for slyxppvghniknqofhqzt>"
OPENAI_API_KEY: "<sk-proj-...>"
ENVIRONMENT: "production"
ALLOWED_ORIGINS: "http://localhost:3000,http://localhost:5173,https://brain-plataform.vercel.app,https://baita-cardapio.vercel.app,https://baita-cardapio-allanvvzs-projects.vercel.app"
```

## After deploy

- PROD URL: `https://ai-brain-api-837167469397.us-central1.run.app`
- Expected `/api/menu/baita-conveniencia` payload: 16 categorias, 383 produtos, banners com signed URLs (`storage/v1/object/sign/assets-raw/...`).
- The frontend `baita-cardapio` already points at this URL via Vercel `VITE_AI_BRAIN_API_URL`. No frontend redeploy needed unless the cardapio code changed.

## Rollback

Each Cloud Run deploy creates a new revision. To rollback:

```bash
gcloud run revisions list --service ai-brain-api --region us-central1 --limit 5
gcloud run services update-traffic ai-brain-api --region us-central1 --to-revisions <previous-revision>=100
```

## Related

- `deploy-qa` — must succeed first; this script gates on it.
- `cardapio-deploy prod` — deploys the frontend after backend.
- `smoke-check` — invoked twice (before and after).
