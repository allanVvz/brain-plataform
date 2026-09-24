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
MONOREPO_REPOSITORY = "allanVvz/brain-plataform"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MONOREPO_CONTRACT_VERSION = re.compile(r"^3\.[0-9]+\.[0-9]+$")
CONTRACT_CONSUMERS = {"control-plane", "conversation-runtime", "transport"}


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
        "route_map_checksum", "services",
    }
    _require(required <= manifest.keys(), f"missing fields: {sorted(required - manifest.keys())}")
    _require(bool(SHA.fullmatch(str(manifest["source_sha"]))), "invalid source_sha")
    contracts_version = str(manifest["contracts_version"])
    _require(
        contracts_version in {"1.0.0", "1.1.0"}
        or bool(MONOREPO_CONTRACT_VERSION.fullmatch(contracts_version)),
        "contracts_version is not supported by this checkout",
    )
    _require(isinstance(manifest["schema_version"], int) and manifest["schema_version"] >= 131,
             "schema_version must be at least 131")
    _require(bool(DIGEST.fullmatch(str(manifest["route_map_checksum"]))),
             "invalid route_map_checksum")

    services = manifest["services"]
    _require(isinstance(services, dict), "services must be an object")
    _require(set(services) == set(EXPECTED_SERVICES), "service set does not match release boundary")
    monorepo_release = contracts_version.startswith("3.")
    if monorepo_release:
        _require(bool(DIGEST.fullmatch(str(manifest.get("contracts_checksum", "")))),
                 "monorepo manifest requires contracts_checksum")
    consumer_contract_versions: set[str] = set()
    for name, repository in EXPECTED_SERVICES.items():
        item = services[name]
        _require(isinstance(item, dict), f"services.{name} must be an object")
        expected_repository = MONOREPO_REPOSITORY if monorepo_release else repository
        _require(item.get("repository") == expected_repository, f"unexpected repository for {name}")
        _require(bool(SHA.fullmatch(str(item.get("sha", "")))), f"invalid SHA for {name}")
        _require(bool(DIGEST.fullmatch(str(item.get("digest", "")))), f"invalid digest for {name}")
        service_contracts_version = str(item.get("contracts_version") or contracts_version)
        _require(
            service_contracts_version in {"1.0.0", "1.1.0"}
            or bool(MONOREPO_CONTRACT_VERSION.fullmatch(service_contracts_version)),
            f"invalid contracts_version for {name}",
        )
        service_contracts_checksum = str(
            item.get("contracts_checksum") or manifest.get("contracts_checksum") or ""
        )
        if service_contracts_version.startswith("3."):
            _require(bool(DIGEST.fullmatch(service_contracts_checksum)),
                     f"invalid contracts_checksum for {name}")
        if name in CONTRACT_CONSUMERS:
            # The package checksum records the exact source in each image.
            # Compatible helper changes can change those bytes without
            # changing the versioned wire contract between services.
            consumer_contract_versions.add(service_contracts_version)
        required_schema = item.get("required_schema_version")
        _require(isinstance(required_schema, int) and 131 <= required_schema <= manifest["schema_version"],
                 f"invalid required_schema_version for {name}")
    _require(
        len(consumer_contract_versions) == 1,
        "brain-contracts version mismatch between active contract consumers",
    )
    # source_sha identifies the manifest revision. Service provenance is
    # intentionally independent: unchanged services keep their prior SHA and
    # digest during a compatible single-service release.

    if verify_checkout_artifacts:
        route_map = ROOT / "ops/microservices/route-map.json"
        _require(_checksum(route_map) == manifest["route_map_checksum"], "route map checksum drift")
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
