#!/usr/bin/env python3
"""Reject migration files that cannot run inside one psql transaction."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAFE_FILENAME = re.compile(r"\d{3}_[a-z0-9_]+\.sql")
UNSAFE_STATEMENT = re.compile(
    r"^\s*(?:BEGIN|START\s+TRANSACTION|COMMIT|VACUUM)\b"
    r"|^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b",
    flags=re.I | re.M,
)
DOLLAR_DELIMITER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def executable_sql(text: str) -> str:
    """Remove comments and dollar-quoted function bodies before gate checks."""
    output: list[str] = []
    cursor = 0
    while match := DOLLAR_DELIMITER.search(text, cursor):
        output.append(text[cursor : match.start()])
        closing = text.find(match.group(), match.end())
        if closing < 0:
            raise ValueError("unterminated dollar-quoted block")
        output.append("\n")
        cursor = closing + len(match.group())
    output.append(text[cursor:])
    outside = re.sub(r"/\*.*?\*/", "", "".join(output), flags=re.S)
    return re.sub(r"--.*$", "", outside, flags=re.M)


def validate_filenames(filenames: list[str]) -> None:
    for filename in filenames:
        if not SAFE_FILENAME.fullmatch(filename):
            raise ValueError(f"unsafe migration filename: {filename}")
        path = ROOT / "supabase" / "migrations" / filename
        sql = executable_sql(path.read_text(encoding="utf-8"))
        if UNSAFE_STATEMENT.search(sql):
            raise ValueError(
                f"migration is incompatible with atomic schema apply: {filename}"
            )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} MIGRATION_LIST", file=sys.stderr)
        return 2
    try:
        filenames = Path(argv[1]).read_text(encoding="utf-8").splitlines()
        validate_filenames(filenames)
    except (OSError, ValueError) as exc:
        print(f"atomic migration validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
