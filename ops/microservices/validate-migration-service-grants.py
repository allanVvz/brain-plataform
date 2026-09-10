#!/usr/bin/env python3
"""Reject new public RPCs that isolated microservice roles cannot execute.

Migration 131 removed implicit service_role inheritance.  This check examines
the post-cutover migration inventory as a whole, allowing a later additive
migration to repair a grant while still blocking the release until that grant
and the PostgREST schema reload are both present.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")
FUNCTION_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+public\.([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


def validate(root: Path, minimum_version: int = 138) -> list[str]:
    sql_parts: list[str] = []
    functions: set[str] = set()
    for path in sorted(root.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if not match or int(match.group(1)) < minimum_version:
            continue
        sql = path.read_text(encoding="utf-8")
        sql_parts.append(sql)
        functions.update(FUNCTION_RE.findall(sql))

    combined = "\n".join(sql_parts)
    errors: list[str] = []
    for name in sorted(functions):
        grant = re.compile(
            rf"grant\s+execute\s+on\s+function\s+public\.{re.escape(name)}\s*\(.*?\)\s+to\s+brain_(?:control_plane|runtime|transport|gateway)",
            re.IGNORECASE | re.DOTALL,
        )
        if not grant.search(combined):
            errors.append(f"public RPC {name} has no isolated microservice grant")
    if functions and not re.search(
        r"notify\s+pgrst\s*,\s*['\"]reload schema['\"]", combined, re.IGNORECASE
    ):
        errors.append("public RPC migrations do not reload the PostgREST schema cache")
    return errors


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("supabase/migrations")
    errors = validate(root)
    if errors:
        print("invalid microservice migration grants:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("valid isolated microservice RPC grants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
