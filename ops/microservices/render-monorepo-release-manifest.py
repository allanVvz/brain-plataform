#!/usr/bin/env python3
"""Render, but never deploy, a four-image monorepo release manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("gateway", "control-plane", "conversation-runtime", "transport")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def checksum(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def contracts_checksum() -> str:
    digest = hashlib.sha256()
    source = ROOT / "packages/brain-contracts/brain_contracts"
    for path in sorted(source.glob("*.py")):
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + digest.hexdigest()


def render(*, source_sha: str, digests: dict[str, str], schema_version: int) -> dict:
    if not SHA.fullmatch(source_sha):
        raise ValueError("source_sha must be a 40-character lowercase SHA")
    if set(digests) != set(SERVICES) or not all(DIGEST.fullmatch(value) for value in digests.values()):
        raise ValueError("one sha256 digest is required for each service")
    package_checksum = contracts_checksum()
    return {
        "source_sha": source_sha,
        "contracts_version": "3.0.0",
        "contracts_checksum": package_checksum,
        "schema_version": schema_version,
        "route_map_checksum": checksum(ROOT / "ops/microservices/route-map.json"),
        "n8n_checksum": checksum(ROOT / "apps/conversation-runtime/n8n/persona-conversation-template.json"),
        "services": {
            name: {
                "repository": "allanVvz/brain-plataform",
                "sha": source_sha,
                "digest": digests[name],
                "required_schema_version": 131,
                "build_context": f"apps/{name}",
            }
            for name in SERVICES
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--schema-version", type=int, default=132)
    parser.add_argument("--output", type=Path, required=True)
    for name in SERVICES:
        parser.add_argument(f"--{name}-digest", required=True)
    args = parser.parse_args()
    digests = {name: getattr(args, f"{name.replace('-', '_')}_digest") for name in SERVICES}
    payload = render(source_sha=args.source_sha, digests=digests, schema_version=args.schema_version)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"rendered monorepo release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
