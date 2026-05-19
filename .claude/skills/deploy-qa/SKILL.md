---
name: deploy-qa
description: Deploy the ai-brain-api-qa Cloud Run service from the current develop branch. Use when the user wants to ship a QA build to the test environment, typically after committing changes on develop or before promoting to main. Wraps gcloud run deploy with env.qa.yaml and runs a smoke-check after.
---

# deploy-qa

Deploys the QA build of `ai-brain-api` to Cloud Run.

## Pre-flight (the script enforces these)

1. `env.qa.yaml` exists at repo root (gitignored, copy from `env.yaml.example`).
2. Current branch is `develop` (warns + asks confirmation if not).
3. `gcloud` is authenticated as `allan.ulisses@pucpr.edu.br` with project `ai-brain-api`.
4. `gcloud config get auth/disable_ssl_validation` is `True` on this machine (corporate CA chain).
5. Python `py_compile` of `api/main.py + routes/*.py + services/*.py` passes locally.

## How to run

```bash
bash scripts/deploy-qa.sh
```

The script will:

1. Verify `env.qa.yaml` presence and warn if branch != develop.
2. `python -m py_compile` sanity on backend modules.
3. `gcloud run deploy ai-brain-api-qa --source ./api --region us-central1 --allow-unauthenticated --env-vars-file env.qa.yaml`.
4. Call `scripts/smoke-check.sh qa` to validate the new revision.

Takes ~3-5 minutes (most is Cloud Build).

## What env.qa.yaml must contain

```yaml
SUPABASE_URL: "https://qhnepdcqtkjjslqqiyvp.supabase.co"
SUPABASE_SERVICE_KEY: "<service_role JWT for QA project — NOT anon>"
OPENAI_API_KEY: "<sk-proj-...>"
ENVIRONMENT: "qa"
ALLOWED_ORIGINS: "http://localhost:3000,http://localhost:5173,https://baita-cardapio-qa.vercel.app,https://baita-cardapio-allanvvzs-projects.vercel.app"
```

## After deploy

- Service URL: `https://ai-brain-api-qa-837167469397.us-central1.run.app`
- Validate by hand: `curl -sk https://ai-brain-api-qa-837167469397.us-central1.run.app/api/menu/baita-conveniencia | jq '.persona.collections[0].display_name'`
- The QA Supabase has the schema (37 migrations) plus a minimal Baita seed (9 categorias, 4 produtos sem assets). For richer data, run `db-fetch-prod-to-qa`.

## Related

- `deploy-prod` — runs after QA is green to promote develop -> main.
- `db-fetch-prod-to-qa` — copies catalog data from PROD Supabase into QA when seed is not enough.
- `smoke-check` — invoked automatically at the end of deploy-qa.
