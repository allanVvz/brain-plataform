#!/usr/bin/env bash
# scripts/db-fetch-prod-to-qa.sh
# Copy selected tables from PROD Supabase to QA Supabase.
#
# Why not pg_dump --schema=public the whole thing?
#   - PROD has live operational data (leads, messages, agent_logs, system_events) that
#     does NOT belong in QA. We only want the curated knowledge layer + baita-cardapio
#     menu so QA reflects real catalog data.
#   - QA already has the 37 migrations applied. This script truncates the target tables
#     and reinserts PROD rows for the safe subset.
#
# Tables copied (in dependency order):
#   personas, brand_profiles, campaigns,
#   knowledge_node_type_registry, knowledge_relation_type_registry,
#   knowledge_artifacts, knowledge_artifact_versions,
#   knowledge_nodes, knowledge_edges,
#   knowledge_rag_entries, knowledge_rag_chunks, knowledge_rag_links,
#   assets, asset_readings,
#   approved_knowledge_snapshots
#
# Tables NEVER copied: leads, messages, lead_audience_memberships, app_users,
#   user_persona_access, agent_logs, n8n_executions, system_events, system_health,
#   flow_insights, integration_status, sync_runs, sync_logs, kb_intake.
#
# Pre-conditions:
#   - psql and pg_dump installed (`gcloud components install` or apt/brew).
#   - env.yaml + env.qa.yaml present (gitignored) for connection strings.
#   - You have the database password for BOTH projects (Supabase dashboard ->
#     Settings -> Database -> Connection string).
#
# How to provide DB URLs (one-time):
#   Add these lines to env.yaml.local and env.qa.yaml.local (gitignored):
#     SUPABASE_DB_URL: "postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres"
#   This script reads them from env.yaml.db and env.qa.yaml.db respectively
#   so secrets never live alongside the Cloud Run env files.
#
# Usage:
#   scripts/db-fetch-prod-to-qa.sh           # dry-run: shows row counts only
#   scripts/db-fetch-prod-to-qa.sh --apply   # actually copies data
set -euo pipefail

cd "$(dirname "$0")/.."

apply=0
[[ "${1:-}" == "--apply" ]] && apply=1

prod_db_file="env.yaml.db"
qa_db_file="env.qa.yaml.db"

for f in "$prod_db_file" "$qa_db_file"; do
  if [[ ! -f "$f" ]]; then
    cat >&2 <<EOF
[db-sync] FATAL: $f not found.
Create it with a single line:
  SUPABASE_DB_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
Grab the connection string from Supabase dashboard -> Project Settings -> Database.
Add the file to .gitignore (already covered by env*.yaml.db pattern below).
EOF
    exit 1
  fi
done

# shellcheck disable=SC1090
. "$prod_db_file"
prod_url="$SUPABASE_DB_URL"
# shellcheck disable=SC1090
. "$qa_db_file"
qa_url="$SUPABASE_DB_URL"

# Sanity: refuse if URLs are identical.
[[ "$prod_url" != "$qa_url" ]] || { echo "[db-sync] FATAL: PROD and QA URLs are the same"; exit 1; }

tables=(
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
)

echo "[db-sync] PROD row counts:"
for t in "${tables[@]}"; do
  c=$(psql "$prod_url" -tAc "SELECT count(*) FROM public.$t" 2>/dev/null || echo "?")
  printf '  %-40s %s\n' "$t" "$c"
done

if [[ "$apply" -eq 0 ]]; then
  echo "[db-sync] dry-run only. Re-run with --apply to copy."
  exit 0
fi

# Dump each table from PROD and restore into QA in dependency order. Using
# --data-only because schemas are already aligned via migrations. CASCADE
# truncates respect FK chains.
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

table_list=$(IFS=,; echo "${tables[*]}")
# Convert comma list into -t flags.
dump_flags=()
for t in "${tables[@]}"; do dump_flags+=(-t "public.$t"); done

echo "[db-sync] pg_dump PROD (data only)..."
pg_dump "$prod_url" --data-only --no-owner --disable-triggers "${dump_flags[@]}" \
  > "$tmpdir/prod-data.sql"
ls -la "$tmpdir/prod-data.sql"

echo "[db-sync] TRUNCATE QA tables (CASCADE)..."
psql "$qa_url" -c "TRUNCATE $(IFS=,; echo "${tables[*]/#/public.}") RESTART IDENTITY CASCADE;"

echo "[db-sync] psql restore into QA..."
psql "$qa_url" -f "$tmpdir/prod-data.sql"

echo "[db-sync] QA row counts after restore:"
for t in "${tables[@]}"; do
  c=$(psql "$qa_url" -tAc "SELECT count(*) FROM public.$t" 2>/dev/null || echo "?")
  printf '  %-40s %s\n' "$t" "$c"
done

echo "[db-sync] running QA smoke-check..."
bash scripts/smoke-check.sh qa
echo "[db-sync] DONE."
