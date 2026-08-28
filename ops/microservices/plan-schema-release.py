#!/usr/bin/env python3
"""Build a deterministic, read-only schema release plan from a release manifest."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def _manifest_validator():
    path = ROOT / "ops/microservices/validate-release-manifest.py"
    spec = importlib.util.spec_from_file_location("release_manifest_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def build_plan(manifest_path: Path) -> dict:
    manifest = _manifest_validator().validate(manifest_path)
    target = manifest["schema_version"]
    migrations: list[tuple[int, Path]] = []
    seen: dict[int, str] = {}
    for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        match = MIGRATION.fullmatch(path.name)
        if not match:
            raise ValueError(f"invalid migration filename: {path.name}")
        version = int(match.group(1))
        if version in seen:
            raise ValueError(f"duplicate migration version {version}: {seen[version]}, {path.name}")
        seen[version] = path.name
        if version <= target:
            migrations.append((version, path))
    if not migrations or migrations[-1][0] != target:
        raise ValueError(f"target migration {target:03d} is missing")
    if any(version > target for version in seen):
        raise ValueError("manifest schema_version is behind migrations in its checkout")

    digest = hashlib.sha256()
    entries = []
    for version, path in migrations:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{path.name}\0{content_hash}\n".encode())
        entries.append({"version": version, "filename": path.name, "sha256": content_hash})
    return {
        "schema_version": target,
        "migration_count": len(entries),
        "target_migration": entries[-1]["filename"],
        "inventory_checksum": "sha256:" + digest.hexdigest(),
        "migrations": entries,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} RELEASE_MANIFEST.json", file=sys.stderr)
        return 2
    try:
        plan = build_plan(Path(argv[1]).resolve())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid schema release: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
