#!/usr/bin/env bash
# Retired legacy remote DB sync helper.
#
# The current operational flow is local-first through Docker Compose. This
# script intentionally exits so old automation cannot connect to retired remote
# database projects.
set -euo pipefail

cat >&2 <<'EOF'
[db-fetch-prod-to-qa] retired.

Use Docker Compose and explicit migrations/seeds for the local data plane.
Remote database copy flows are not part of the current production path.
EOF

exit 64
