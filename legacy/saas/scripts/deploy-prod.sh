#!/usr/bin/env bash
# scripts/deploy-prod.sh
# Promote develop -> main and deploy ai-brain-api Cloud Run.
#
# Workflow (each gate must pass before the next runs):
#   1. develop branch is clean and pushed (so origin/develop == HEAD).
#   2. QA smoke-check on ai-brain-api-qa passes — refuses to promote a broken QA.
#   3. git merge --no-ff develop into main + push origin main.
#   4. gcloud run deploy ai-brain-api with env.yaml.
#   5. PROD smoke-check.
#
# Pre-conditions:
#   - env.yaml exists locally with service_role JWT (NOT anon).
#   - gcloud authenticated with project ai-brain-api.
#
# Refuses to run if env.yaml has the anon key by mistake — checks JWT role claim.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f env.yaml ]]; then
  echo "[deploy-prod] FATAL: env.yaml not found. Copy env.yaml.example and fill in PROD values." >&2
  exit 1
fi

# Decode the SUPABASE_SERVICE_KEY JWT payload (base64url) and confirm role.
key=$(grep -E '^SUPABASE_SERVICE_KEY:' env.yaml | sed -E 's/.*"([^"]+)".*/\1/')
if [[ -z "$key" ]]; then
  echo "[deploy-prod] FATAL: SUPABASE_SERVICE_KEY missing from env.yaml" >&2; exit 1
fi
payload=$(echo "$key" | cut -d. -f2)
# pad base64
while (( ${#payload} % 4 )); do payload+="="; done
decoded=$(printf '%s' "$payload" | tr '_-' '/+' | base64 -d 2>/dev/null || true)
if ! echo "$decoded" | grep -q '"role":"service_role"'; then
  echo "[deploy-prod] FATAL: env.yaml SUPABASE_SERVICE_KEY is NOT a service_role JWT (likely anon)." >&2
  echo "[deploy-prod]        /api/menu would return 404 'Persona not found' because RLS blocks anon." >&2
  exit 1
fi

# Gate 1: develop must be clean and pushed.
dirty=$(git -C . status --porcelain | wc -l)
[[ "$dirty" -eq 0 ]] || { echo "[deploy-prod] FATAL: working tree dirty"; exit 1; }
git fetch origin --quiet
if ! git diff --quiet origin/develop develop; then
  echo "[deploy-prod] FATAL: local develop differs from origin/develop. Push first." >&2; exit 1
fi

# Gate 2: QA must be healthy.
echo "[deploy-prod] running QA smoke-check before promoting..."
bash scripts/smoke-check.sh qa

# Gate 3: merge develop -> main + push.
git checkout main
git pull origin main --ff-only
git merge --no-ff develop -m "merge develop -> main (deploy-prod $(date -u +%Y-%m-%dT%H:%M:%SZ))"
git push origin main

# Gate 4: deploy.
echo "[deploy-prod] gcloud run deploy ai-brain-api..."
gcloud run deploy ai-brain-api \
  --source ./api \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file env.yaml \
  --quiet

# Gate 5: PROD smoke-check.
echo "[deploy-prod] deployed. Running smoke-check..."
bash scripts/smoke-check.sh prod

# Return to develop for the next iteration.
git checkout develop
echo "[deploy-prod] DONE. ai-brain-api PROD updated. Back on develop."
