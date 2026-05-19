#!/usr/bin/env bash
# scripts/smoke-check.sh
# Validates a deployed ai-brain Cloud Run service.
#
# Usage:
#   scripts/smoke-check.sh prod
#   scripts/smoke-check.sh qa
#   scripts/smoke-check.sh https://custom-url.run.app
#
# Checks:
#   - /health returns 200
#   - /api/menu/baita-conveniencia returns 200 and parses with the expected shape
#
# Exit codes:
#   0 = all OK
#   1 = health failed
#   2 = menu endpoint failed
#   3 = menu payload missing collection
set -euo pipefail

target="${1:-prod}"
case "$target" in
  prod)
    url="https://ai-brain-api-837167469397.us-central1.run.app"
    expect_min_categories=10
    ;;
  qa)
    url="https://ai-brain-api-qa-837167469397.us-central1.run.app"
    expect_min_categories=8
    ;;
  http*)
    url="$target"
    expect_min_categories=1
    ;;
  *)
    echo "usage: $0 <prod|qa|https://url>" >&2
    exit 64
    ;;
esac

# -k tolerates corporate cert chains (matches gcloud SSL workaround used in repo).
echo "[smoke] target=$url"
code=$(curl -sk -o /dev/null -w "%{http_code}" "$url/health" || true)
echo "[smoke] /health -> $code"
[[ "$code" == "200" ]] || exit 1

# Use a workspace-local temp file so python.exe on Windows can resolve the path.
# Git Bash's mktemp returns /tmp/... which is invisible to native Windows python.
tmp_dir="${TMPDIR:-$PWD}/.smoke-tmp"
mkdir -p "$tmp_dir"
tmp="$tmp_dir/smoke-$$.json"
trap 'rm -f "$tmp"' EXIT
code=$(curl -sk -o "$tmp" -w "%{http_code}" "$url/api/menu/baita-conveniencia" || true)
echo "[smoke] /api/menu/baita-conveniencia -> $code"
[[ "$code" == "200" ]] || { cat "$tmp"; exit 2; }

# Convert path for Windows-native python.exe if cygpath is available (Git Bash on Windows).
if command -v cygpath >/dev/null 2>&1; then
  tmp_for_py=$(cygpath -w "$tmp")
else
  tmp_for_py="$tmp"
fi

python - "$tmp_for_py" "$expect_min_categories" <<'PY'
import json, sys
path = sys.argv[1]
expect = int(sys.argv[2])
with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)
coll=(d.get("persona") or {}).get("collections") or []
if not coll:
    print("[smoke] FAIL: no collection in payload"); sys.exit(3)
c=coll[0]
cats=c.get("categories") or []
prods=sum(len(cc.get("products") or []) for cc in cats)
print(f"[smoke] collection='{c.get('display_name')}' categories={len(cats)} products={prods}")
if len(cats) < expect:
    print(f"[smoke] FAIL: expected >= {expect} categories, got {len(cats)}"); sys.exit(3)
print("[smoke] PASS")
PY
