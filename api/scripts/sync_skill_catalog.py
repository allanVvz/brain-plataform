"""Preview or apply one Brain skill manifest to the canonical graph tables.

The default mode is an offline dry-run. ``--check-db`` performs read-only
inspection. ``--apply`` is a production mutation and requires a separately
approved, non-secret authorization reference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = API_ROOT.parent
sys.path.insert(0, str(API_ROOT))

from services.skill_catalog import (  # noqa: E402
    SupabaseSkillCatalogRepository,
    sync_skill_manifest,
)


DEFAULT_MANIFEST = REPOSITORY_ROOT / "data" / "skills" / "humanizer.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and synchronize a BrainSkillManifestV1. Defaults to offline dry-run."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-db",
        action="store_true",
        help="inspect current database state without writes",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="write the knowledge item and disconnected rule node",
    )
    parser.add_argument(
        "--authorization-reference",
        help="non-secret ticket or approval reference; required with --apply",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.apply and not str(args.authorization_reference or "").strip():
        parser.error("--apply requires --authorization-reference from a separate production approval")
    if args.authorization_reference and not args.apply:
        parser.error("--authorization-reference is only valid with --apply")

    repository = SupabaseSkillCatalogRepository() if (args.check_db or args.apply) else None
    result = sync_skill_manifest(
        args.manifest,
        repository,
        repository_root=REPOSITORY_ROOT,
        apply=args.apply,
    )
    payload = result.to_dict()
    payload["mode"] = "apply" if args.apply else "database-dry-run" if args.check_db else "offline-dry-run"
    if args.apply:
        payload["authorization_reference"] = args.authorization_reference
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
