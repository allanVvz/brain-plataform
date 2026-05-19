#!/usr/bin/env bash
# scripts/deploy-qa.sh
# Deploy ai-brain-api-qa Cloud Run service from the current develop branch.
#
# Pre-conditions:
#   - You are on branch `develop` with a clean tree (or you've explicitly accepted local diffs).
#   - env.qa.yaml exists in repo root (NOT committed; see env.yaml.example).
#   - gcloud authenticated (allan.ulisses@pucpr.edu.br) with project ai-brain-api.
#
# Post-conditions:
#   - Cloud Run service ai-brain-api-qa serves 100% traffic on the new revision.
#   - smoke-check passes against the QA URL.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f env.qa.yaml ]]; then
  echo "[deploy-qa] FATAL: env.qa.yaml not found. Copy env.yaml.example and fill in QA values." >&2
  exit 1
fi

branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$branch" != "develop" ]]; then
  echo "[deploy-qa] WARN: current branch is '$branch', not 'develop'." >&2
  read -p "[deploy-qa] continue anyway? (y/N): " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
fi

# Local sanity before paying for a build.
echo "[deploy-qa] py_compile sanity..."
python -m py_compile api/main.py api/routes/*.py api/services/*.py

echo "[deploy-qa] gcloud run deploy ai-brain-api-qa..."
gcloud run deploy ai-brain-api-qa \
  --source ./api \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file env.qa.yaml \
  --quiet

url="https://ai-brain-api-qa-837167469397.us-central1.run.app"
echo "[deploy-qa] deployed. Running smoke-check..."
bash scripts/smoke-check.sh qa
echo "[deploy-qa] DONE. URL: $url"
