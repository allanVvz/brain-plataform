#!/usr/bin/env python3
"""Validate an immutable integrated microservice release manifest."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SERVICES = {
    "gateway": "allanVvz/brain-plataform",
    "control-plane": "allanVvz/brain-control-plane",
    "conversation-runtime": "allanVvz/brain-conversation-runtime",
    "transport": "allanVvz/brain-transport",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _checksum(path: Path) -> str:
    # Git checks out text with platform-specific line endings. Release
    # identity must remain stable between Windows authoring and Linux CI/VPS.
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def validate(path: Path, *, verify_checkout_artifacts: bool = True) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), "manifest must be an object")
    required = {
        "source_sha", "contracts_version", "schema_version",
        "route_map_checksum", "n8n_checksum", "services",
    }
    _require(required <= manifest.keys(), f"missing fields: {sorted(required - manifest.keys())}")
    _require(bool(SHA.fullmatch(str(manifest["source_sha"]))), "invalid source_sha")
    _require(
        manifest["contracts_version"] in {"1.0.0", "1.1.0"},
        "contracts_version must be 1.0.0 or 1.1.0 during the additive blue/green window",
    )
    _require(isinstance(manifest["schema_version"], int) and manifest["schema_version"] >= 131,
             "schema_version must be at least 131")
    _require(bool(DIGEST.fullmatch(str(manifest["route_map_checksum"]))),
             "invalid route_map_checksum")
    _require(bool(DIGEST.fullmatch(str(manifest["n8n_checksum"]))), "invalid n8n_checksum")

    services = manifest["services"]
    _require(isinstance(services, dict), "services must be an object")
    _require(set(services) == set(EXPECTED_SERVICES), "service set does not match release boundary")
    for name, repository in EXPECTED_SERVICES.items():
        item = services[name]
        _require(isinstance(item, dict), f"services.{name} must be an object")
        _require(item.get("repository") == repository, f"unexpected repository for {name}")
        _require(bool(SHA.fullmatch(str(item.get("sha", "")))), f"invalid SHA for {name}")
        _require(bool(DIGEST.fullmatch(str(item.get("digest", "")))), f"invalid digest for {name}")
        required_schema = item.get("required_schema_version")
        _require(isinstance(required_schema, int) and 131 <= required_schema <= manifest["schema_version"],
                 f"invalid required_schema_version for {name}")
    _require(services["gateway"]["sha"] == manifest["source_sha"],
             "gateway SHA must equal source_sha")

    if verify_checkout_artifacts:
        route_map = ROOT / "ops/microservices/route-map.json"
        n8n = ROOT / "api/n8n-workflows/persona-conversation-template.json"
        _require(_checksum(route_map) == manifest["route_map_checksum"], "route map checksum drift")
        _require(_checksum(n8n) == manifest["n8n_checksum"], "n8n checksum drift")
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} RELEASE_MANIFEST.json", file=sys.stderr)
        return 2
    try:
        manifest = validate(Path(argv[1]).resolve())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid release manifest: {exc}", file=sys.stderr)
        return 1
    print(
        f"valid release manifest: schema={manifest['schema_version']} "
        f"contracts={manifest['contracts_version']} services={len(manifest['services'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
