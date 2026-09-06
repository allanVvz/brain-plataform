"""Compile a local GraphBundle and print a dry-run PublicationPlan."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Production publication is owned by the control-plane microservice. Importing
# the frozen monolith here can approve a runtime checksum that staging will
# never reproduce, even when both copies advertise the same compiler version.
REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE_API_DIR = REPO_ROOT / "apps" / "control-plane" / "api"
if str(CONTROL_PLANE_API_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE_API_DIR))

from services.graph_bundle import build_publication_plan, compile_bundle  # noqa: E402


def _json_file(value: str) -> dict:
    with Path(value).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {value}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a GraphBundle without publishing or writing production state."
    )
    parser.add_argument("bundle", help="Path to the GraphBundle JSON file")
    against = parser.add_mutually_exclusive_group()
    against.add_argument("--against", help="Optional compiled v3 document to diff against")
    against.add_argument(
        "--against-bundle",
        help="Optional trusted GraphBundle source of the active publication to compile and diff against",
    )
    parser.add_argument("--next-version", type=int, default=1)
    parser.add_argument("--output", help="Optional path for the reviewable PublicationPlan JSON")
    parser.add_argument(
        "--include-document",
        action="store_true",
        help="Include the complete compiled candidate document in stdout",
    )
    args = parser.parse_args()

    try:
        current_document = (
            _json_file(args.against)
            if args.against
            else compile_bundle(_json_file(args.against_bundle))
            if args.against_bundle
            else None
        )
        plan = build_publication_plan(
            _json_file(args.bundle),
            current_document=current_document,
            next_version=args.next_version,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "disposition": "blocked",
            "validation_errors": [f"input_error:{type(exc).__name__}:{exc}"],
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    printable = dict(plan)
    if not args.include_document:
        printable.pop("candidate_document", None)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not plan["validation_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
