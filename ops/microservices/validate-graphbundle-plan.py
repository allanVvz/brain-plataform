#!/usr/bin/env python3
"""Validate a compiled GraphBundle plan without touching publication state."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
PERSONA_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(
    bundle_path: Path,
    plan_path: Path,
    *,
    persona_slug: str,
    approved_draft_checksum: str,
    approved_runtime_checksum: str,
    bundle_root: Path | None = None,
) -> dict:
    bundle_path = bundle_path.resolve()
    plan_path = plan_path.resolve()
    allowed_root = (bundle_root or ROOT / "data/graph_bundles").resolve()
    _require(allowed_root in bundle_path.parents, "bundle must be under data/graph_bundles")
    _require(PERSONA_SLUG.fullmatch(persona_slug) is not None, "invalid persona slug")
    _require(CHECKSUM.fullmatch(approved_draft_checksum) is not None, "invalid approved draft checksum")
    _require(CHECKSUM.fullmatch(approved_runtime_checksum) is not None, "invalid approved runtime checksum")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _require(isinstance(bundle, dict) and isinstance(plan, dict), "bundle and plan must be objects")
    _require((bundle.get("persona") or {}).get("slug") == persona_slug, "persona scope mismatch")
    _require(plan.get("disposition") == "awaiting_approval", "plan is not awaiting approval")
    _require(plan.get("publication_allowed") is True, "bundle is not publication allowed")
    _require(plan.get("validation_errors") == [], "plan has validation errors")
    _require(plan.get("draft_checksum") == approved_draft_checksum, "approved draft checksum mismatch")
    _require(plan.get("runtime_checksum") == approved_runtime_checksum, "approved runtime checksum mismatch")
    return {
        "persona_slug": persona_slug,
        "draft_checksum": approved_draft_checksum,
        "runtime_checksum": approved_runtime_checksum,
        "next_version": plan.get("next_version"),
        "branches_affected": plan.get("branches_affected") or [],
        "breaking_contract_changes": plan.get("breaking_contract_changes") or [],
        "chunks_reused": plan.get("chunks_reused"),
        "chunks_to_embed": plan.get("chunks_to_embed"),
        "validation_errors": [],
        "disposition": "awaiting_approval",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--persona-slug", required=True)
    parser.add_argument("--approved-draft-checksum", required=True)
    parser.add_argument("--approved-runtime-checksum", required=True)
    args = parser.parse_args(argv[1:])
    try:
        summary = validate(
            Path(args.bundle), Path(args.plan), persona_slug=args.persona_slug,
            approved_draft_checksum=args.approved_draft_checksum,
            approved_runtime_checksum=args.approved_runtime_checksum,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid GraphBundle publication plan: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
