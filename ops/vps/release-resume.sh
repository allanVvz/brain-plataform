#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_SHA="${1:?usage: release-resume.sh <full-git-sha> <actor> <reason>}"
ACTOR="${2:?resume actor required}"
REASON="${3:?resume reason required}"
cd "$ROOT_DIR"
stage="$(python3 ops/vps/release_lifecycle.py show --field stage)"
if [[ "$stage" == "awaiting_resume_authorization" ]]; then
  python3 ops/vps/release_lifecycle.py authorize-resume --actor "$ACTOR" --reason "$REASON"
elif [[ "$stage" != "workers_resumed" && "$stage" != "verified" ]]; then
  echo "release is not resumable from stage=$stage" >&2
  exit 1
fi
bash ops/vps/resume-production-workers.sh "$TARGET_SHA"
