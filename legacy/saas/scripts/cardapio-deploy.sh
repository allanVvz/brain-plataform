#!/usr/bin/env bash
# scripts/cardapio-deploy.sh
# Deploy the baita-cardapio frontend to Vercel.
#
# Usage:
#   scripts/cardapio-deploy.sh prod          # promote main to production
#   scripts/cardapio-deploy.sh qa            # preview deploy from current branch, aliased to baita-cardapio-qa
#
# Pre-conditions:
#   - The baita-cardapio repo is checked out at $CARDAPIO_DIR (default ../baita-cardapio
#     relative to ai-brain repo, or set CARDAPIO_DIR env var).
#   - Vercel CLI authenticated as allanvvz.
#   - For prod: VITE_AI_BRAIN_API_URL already set on Vercel production environment
#     (one-time: `vercel env add VITE_AI_BRAIN_API_URL production`).
#   - For qa: VITE_AI_BRAIN_API_URL already set on Vercel preview env scoped to qa branch
#     (one-time: `printf "https://ai-brain-api-qa-...\n" | vercel env add VITE_AI_BRAIN_API_URL preview qa`).
set -euo pipefail

mode="${1:-}"
case "$mode" in
  prod|qa) ;;
  *)
    echo "usage: $0 <prod|qa>" >&2
    exit 64
    ;;
esac

ai_brain_root="$(cd "$(dirname "$0")/.." && pwd)"
cardapio_dir="${CARDAPIO_DIR:-$(dirname "$ai_brain_root")/baita-cardapio}"
[[ -d "$cardapio_dir" ]] || { echo "[cardapio] FATAL: $cardapio_dir not found" >&2; exit 1; }

cd "$cardapio_dir"
branch=$(git rev-parse --abbrev-ref HEAD)

if [[ "$mode" == "prod" ]]; then
  if [[ "$branch" != "main" ]]; then
    echo "[cardapio] WARN: expected branch=main for prod deploy, got $branch" >&2
    read -p "[cardapio] continue? (y/N): " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
  fi
  echo "[cardapio] vercel deploy --prod (main)..."
  url=$(vercel deploy --prod --yes 2>&1 | tail -1)
  echo "[cardapio] deployed: $url"
  echo "[cardapio] alias: https://baita-cardapio.vercel.app"
  curl -sk -o /dev/null -w "[cardapio] https://baita-cardapio.vercel.app/cardapio/baita -> %{http_code}\n" https://baita-cardapio.vercel.app/cardapio/baita
  exit 0
fi

# qa: preview deploy + alias baita-cardapio-qa
if [[ "$branch" != "qa" ]]; then
  echo "[cardapio] WARN: expected branch=qa for QA preview, got $branch" >&2
  read -p "[cardapio] continue? (y/N): " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
fi

echo "[cardapio] vercel deploy (preview)..."
deploy_url=$(vercel deploy --yes 2>&1 | grep -oE 'https://baita-cardapio-[a-z0-9]+-allanvvzs-projects\.vercel\.app' | head -1)
[[ -n "$deploy_url" ]] || { echo "[cardapio] could not parse preview URL"; exit 1; }
echo "[cardapio] preview: $deploy_url"

echo "[cardapio] alias -> baita-cardapio-qa.vercel.app"
vercel alias set "${deploy_url#https://}" baita-cardapio-qa.vercel.app
echo "[cardapio] DONE. https://baita-cardapio-qa.vercel.app (SSO active — use Vercel MCP get_access_to_vercel_url to test)"
