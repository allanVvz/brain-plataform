#!/usr/bin/env python3
"""Create and verify the migration-runner manifest without a fixed name list."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def build_manifest(directory: Path) -> dict[str, Any]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        payload = path.read_bytes()
        migrations.append({
            "filename": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        })
    if not migrations:
        raise SystemExit(f"no migrations found in {directory}")
    canonical = json.dumps(migrations, separators=(",", ":"), sort_keys=True).encode()
    return {
        "schema_version": 1,
        "runner_version": "ledger-subset-v1",
        "count": len(migrations),
        "latest": migrations[-1]["filename"],
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "migrations": migrations,
    }


def verify_applied(manifest: dict[str, Any], applied: set[str]) -> list[str]:
    expected = {
        str(item["filename"])
        for item in manifest.get("migrations", [])
        if isinstance(item, dict) and item.get("filename")
    }
    return sorted(expected - applied)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--directory", type=Path, default=Path("supabase/migrations"))
    create.add_argument("--output", type=Path)
    verify = sub.add_parser("verify-applied")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--applied", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "create":
        value = build_manifest(args.directory)
        rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    applied = {
        line.strip() for line in args.applied.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    missing = verify_applied(manifest, applied)
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, sort_keys=True))
        raise SystemExit(1)
    print(json.dumps({
        "ok": True,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "expected": manifest.get("count"),
        "applied": len(applied),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
