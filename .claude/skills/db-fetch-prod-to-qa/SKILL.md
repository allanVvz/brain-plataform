---
name: db-fetch-prod-to-qa
description: Copy a curated subset of tables from the PROD Supabase project to the QA Supabase project. Use when QA needs richer data than the migration seed (for example to validate menu rendering with all 383 Baita products and real images) without polluting QA with operational PII (leads, messages, agent logs). Always run dry-run first to see row counts; only --apply when intended.
---

# db-fetch-prod-to-qa

Replicates curated knowledge tables from PROD Supabase (`slyxppvghniknqofhqzt`) into QA Supabase (`qhnepdcqtkjjslqqiyvp`) so QA reflects real catalog data.

## Tables that ARE copied

In dependency order:

```
personas
brand_profiles
campaigns
knowledge_node_type_registry
knowledge_relation_type_registry
knowledge_artifacts
knowledge_artifact_versions
knowledge_nodes
knowledge_edges
knowledge_rag_entries
knowledge_rag_chunks
knowledge_rag_links
assets
asset_readings
approved_knowledge_snapshots
```

## Tables that are NEVER copied (PII / operational)

`leads`, `messages`, `lead_audience_memberships`, `app_users`, `user_persona_access`, `agent_logs`, `n8n_executions`, `system_events`, `system_health`, `flow_insights`, `integration_status`, `sync_runs`, `sync_logs`, `kb_intake`.

If you need any of these in QA, copy them manually with anonymized data — never via this script.

## Pre-flight

1. `psql` and `pg_dump` installed locally (Postgres client tools).
2. Create two gitignored files at repo root with Supabase pooler connection strings:

   `env.yaml.db` (PROD):
   ```bash
   SUPABASE_DB_URL="postgresql://postgres.slyxppvghniknqofhqzt:<password>@aws-0-us-west-1.pooler.supabase.com:5432/postgres"
   ```

   `env.qa.yaml.db` (QA):
   ```bash
   SUPABASE_DB_URL="postgresql://postgres.qhnepdcqtkjjslqqiyvp:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
   ```

   Get the connection string from Supabase dashboard -> Project Settings -> Database -> Connection string (Transaction pooler, port 5432). Use the database password you set when creating the project.

3. Already covered by `.gitignore` (`env*.yaml.db`). Never commit these.

## How to run

```bash
# Step 1: dry-run. Lists PROD row counts. Nothing is written.
bash scripts/db-fetch-prod-to-qa.sh

# Step 2: actually copy.
bash scripts/db-fetch-prod-to-qa.sh --apply
```

The `--apply` run:

1. `pg_dump --data-only --no-owner --disable-triggers` of PROD subset.
2. `TRUNCATE ... RESTART IDENTITY CASCADE` on QA tables.
3. `psql -f` of the dump into QA.
4. Prints QA row counts after restore.
5. Calls `smoke-check qa`.

Takes ~30s-2min depending on data volume.

## Safety

- Refuses if PROD and QA DB URLs are identical.
- Only the 15 tables above are touched. Assets/storage buckets are NOT copied (they live in Supabase Storage, not Postgres). After running this, signed URLs for QA assets will 404 unless you also re-upload binaries to the QA `assets-raw` bucket. The smoke-check ignores asset URLs and only checks payload shape.

## Related

- `deploy-qa` — deploy the QA backend after data refresh if you changed code too.
- `smoke-check qa` — invoked automatically at the end.

## Future enhancement

A `db-fetch-prod-assets-to-qa.sh` companion script could mirror `storage.buckets/assets-raw/*` via the Supabase Storage API. Not implemented today because QA mostly validates rendering shape, not actual image bytes.
