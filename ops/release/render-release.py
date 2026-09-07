#!/usr/bin/env python3
"""Render a release manifest, preserving active digests for unchanged services."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location


ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("manifest_renderer", ROOT / "ops/microservices/render-monorepo-release-manifest.py")
renderer = module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(renderer)


def render_payload(
    *, active: dict, changed: set[str], new_digests: dict[str, str], source_sha: str
) -> dict:
    digests = {name: row["digest"] for name, row in active["services"].items()}
    for service in changed:
        digest = new_digests.get(service, "")
        if not digest:
            raise ValueError(f"new digest missing for changed service: {service}")
        if digest == active["services"][service]["digest"]:
            raise ValueError(f"changed service reused active digest: {service}")
        digests[service] = digest
    payload = renderer.render(
        source_sha=source_sha,
        digests=digests,
        schema_version=renderer.latest_schema_version(),
    )
    for service in set(active["services"]) - changed:
        payload["services"][service] = active["services"][service]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--digests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    active = json.loads(args.active.read_text(encoding="utf-8"))
    changed = set(json.loads(os.environ.get("CHANGED_SERVICES", "[]")))
    new_digests: dict[str, str] = {}
    for service in changed:
        path = args.digests / f"{service}.digest"
        if not path.is_file():
            raise SystemExit(f"new digest missing for changed service: {service}")
        new_digests[service] = path.read_text(encoding="utf-8").strip()
    try:
        payload = render_payload(
            active=active, changed=changed, new_digests=new_digests,
            source_sha=os.environ["SOURCE_SHA"],
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
