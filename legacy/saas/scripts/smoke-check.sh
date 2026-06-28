#!/usr/bin/env bash
# scripts/smoke-check.sh
# Validate an AI Brain backend URL.
#
# Usage:
#   scripts/smoke-check.sh local
#   scripts/smoke-check.sh https://public-backend.example.com
set -euo pipefail

target="${1:-local}"
case "$target" in
  local)
    url="http://localhost:8080"
    ;;
  http*)
    url="$target"
    ;;
  *)
    echo "usage: $0 <local|https://backend-url>" >&2
    exit 64
    ;;
esac

echo "[smoke] target=$url"
code=$(curl -sk -o /dev/null -w "%{http_code}" "$url/health" || true)
echo "[smoke] /health -> $code"
[[ "$code" == "200" ]] || exit 1

tmp_dir="${TMPDIR:-$PWD}/.smoke-tmp"
mkdir -p "$tmp_dir"
tmp="$tmp_dir/smoke-$$.json"
trap 'rm -f "$tmp"' EXIT

code=$(curl -sk -o "$tmp" -w "%{http_code}" "$url/api/menu/baita-conveniencia?nocache=1" || true)
echo "[smoke] /api/menu/baita-conveniencia -> $code"
[[ "$code" == "200" ]] || { cat "$tmp"; exit 2; }

if command -v cygpath >/dev/null 2>&1; then
  tmp_for_py=$(cygpath -w "$tmp")
else
  tmp_for_py="$tmp"
fi

python - "$tmp_for_py" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)
collections = d.get("collections") or (d.get("persona") or {}).get("collections") or []
if not collections:
    print("[smoke] FAIL: no collection in payload")
    sys.exit(3)
categories = sum(len(c.get("categories") or []) for c in collections)
products = sum(
    len(cat.get("products") or [])
    for c in collections
    for cat in (c.get("categories") or [])
)
print(f"[smoke] collections={len(collections)} categories={categories} products={products}")
print("[smoke] PASS")
PY
