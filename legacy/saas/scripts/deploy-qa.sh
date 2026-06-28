#!/usr/bin/env bash
# scripts/deploy-qa.sh
#
# Historical remote QA deploy script was retired with the local Docker
# operating model.
set -euo pipefail

cat >&2 <<'EOF'
[deploy-qa] retired.

Current QA/local flow:
  docker compose --env-file .env.compose up -d --build
  curl http://localhost:8080/health
  curl http://localhost:8080/api/menu/baita-conveniencia

For dashboard QA, run:
  cd dashboard
  npm run dev:local
EOF

exit 64
