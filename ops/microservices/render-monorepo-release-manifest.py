#!/usr/bin/env python3
"""Render, but never deploy, an independently versioned service manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("gateway", "control-plane", "conversation-runtime", "transport")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def contracts_version() -> str:
    metadata = tomllib.loads(
        (ROOT / "packages/brain-contracts/pyproject.toml").read_text(encoding="utf-8")
    )
    return str(metadata["project"]["version"])


def checksum(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def contracts_checksum() -> str:
    digest = hashlib.sha256()
    source = ROOT / "packages/brain-contracts/brain_contracts"
    for path in sorted(source.glob("*.py")):
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + digest.hexdigest()


def render(
    *, source_sha: str, digests: dict[str, str], schema_version: int,
    base_manifest: dict | None = None,
) -> dict:
    if not SHA.fullmatch(source_sha):
        raise ValueError("source_sha must be a 40-character lowercase SHA")
    if not digests or not set(digests) <= set(SERVICES):
        raise ValueError("at least one known service digest is required")
    if not all(DIGEST.fullmatch(value) for value in digests.values()):
        raise ValueError("every supplied service digest must be sha256")
    previous = dict((base_manifest or {}).get("services") or {})
    if set(previous) - set(SERVICES):
        raise ValueError("base manifest contains an unknown service")
    if set(previous) | set(digests) != set(SERVICES):
        raise ValueError("a new manifest needs all services; an incremental manifest needs a complete base")
    package_checksum = contracts_checksum()
    services = {}
    for name in SERVICES:
        if name not in digests:
            services[name] = dict(previous[name])
            continue
        services[name] = {
            "repository": "allanVvz/brain-plataform",
            "sha": source_sha,
            "digest": digests[name],
            "required_schema_version": schema_version,
            "contracts_version": contracts_version(),
            "contracts_checksum": package_checksum,
            "build_context": f"apps/{name}",
        }
    return {
        "source_sha": source_sha,
        "contracts_version": contracts_version(),
        "contracts_checksum": package_checksum,
        "schema_version": schema_version,
        "route_map_checksum": checksum(ROOT / "ops/microservices/route-map.json"),
        "services": services,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--schema-version", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path)
    for name in SERVICES:
        parser.add_argument(f"--{name}-digest")
    args = parser.parse_args()
    digests = {
        name: value for name in SERVICES
        if (value := getattr(args, f"{name.replace('-', '_')}_digest"))
    }
    base = json.loads(args.base_manifest.read_text(encoding="utf-8")) if args.base_manifest else None
    schema_version = args.schema_version or ((base or {}).get("schema_version"))
    if not isinstance(schema_version, int):
        parser.error("--schema-version is required when no base manifest is supplied")
    payload = render(
        source_sha=args.source_sha, digests=digests,
        schema_version=schema_version, base_manifest=base,
    )
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"rendered monorepo release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
