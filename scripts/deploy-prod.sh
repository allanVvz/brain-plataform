#!/usr/bin/env bash
# scripts/deploy-prod.sh
#
# Historical production deploy script was retired with the local Docker +
# Vercel operating model. Keep this file as a guardrail so old automation
# fails loudly instead of deploying the wrong backend.
set -euo pipefail

cat >&2 <<'EOF'
[deploy-prod] retired.

Current production flow:
  1. Run the AI Brain backend through Docker Compose.
  2. Expose the backend through an approved public HTTPS endpoint.
  3. Set Vercel env:
       API_INTERNAL_BASE_URL=<public backend URL>
       NEXT_PUBLIC_API_BASE_URL=/api-brain
  4. Deploy the dashboard:
       vercel deploy --prod --yes
  5. Validate:
       https://brain-plataform.vercel.app/login
       https://brain-plataform.vercel.app/api-brain/health

Use scripts/deploy-vercel.ps1 for the dashboard helper flow.
EOF

exit 64
