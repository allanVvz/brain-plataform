---
name: smoke-check
description: Run smoke validation against ai-brain Cloud Run service (PROD, QA, or arbitrary URL). Verifies /health returns 200 and /api/menu/baita-conveniencia returns a parseable payload with the expected category count. Use when the user wants to quickly check if a deployed ai-brain backend is healthy before promoting code or after a deploy.
---

# smoke-check

Validates an ai-brain Cloud Run deployment end-to-end against the public `/api/menu` contract used by `baita-cardapio`.

## When to use

- After a `gcloud run deploy` finishes, before declaring success.
- Before promoting `develop -> main` (gate inside `scripts/deploy-prod.sh` already calls this).
- When debugging "is prod broken or is it the frontend?".

## How

Run one of:

```bash
bash scripts/smoke-check.sh prod
bash scripts/smoke-check.sh qa
bash scripts/smoke-check.sh https://my-other-revision-xxxxx-uc.a.run.app
```

The script:

1. Resolves URL: `prod` -> `https://ai-brain-api-837167469397.us-central1.run.app`, `qa` -> `https://ai-brain-api-qa-837167469397.us-central1.run.app`.
2. `GET /health` must return 200. Otherwise exit 1.
3. `GET /api/menu/baita-conveniencia` must return 200. Otherwise exit 2.
4. Parses payload, checks `persona.collections[0].categories.length >= minCategories` (10 for prod, 8 for qa).
5. Prints `[smoke] PASS` and exits 0.

## Failure modes and triage

| Symptom | Root cause | Fix |
|---|---|---|
| `/api/menu` returns 401 `Sessao obrigatoria` | Deployed code predates `PUBLIC_PREFIXES += /api/menu` in `api/middleware/auth.py` | Redeploy from current `develop` or `main` |
| `/api/menu` returns 404 `Persona not found: baita-conveniencia` | Cloud Run env var `SUPABASE_SERVICE_KEY` is the anon JWT | `gcloud run services update <service> --update-env-vars SUPABASE_SERVICE_KEY=<service_role JWT>` |
| Categories count below threshold | Supabase has empty `knowledge_nodes` for that persona | Apply the BAITA seed (migration 037 or `scripts/db-fetch-prod-to-qa.sh`) |
| `curl` exits with code 35 (SSL) | Corporate CA chain blocks gcloud | `gcloud config set auth/disable_ssl_validation True` is already applied; this is the `-k` flag in the script |

## Related

- `deploy-qa` — calls smoke-check after deploying.
- `deploy-prod` — calls smoke-check both before (QA gate) and after (PROD verify).
