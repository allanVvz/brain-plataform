from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


renderer = _load("release_renderer", "ops/microservices/render-monorepo-release-manifest.py")
validator = _load("release_validator", "ops/microservices/validate-release-manifest.py")


def _digest(char: str) -> str:
    return "sha256:" + char * 64


class _ManifestDocument:
    def __init__(self, payload: dict):
        self.payload = payload

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return json.dumps(self.payload)


def test_runtime_only_release_preserves_other_service_provenance():
    old_sha = "a" * 40
    new_sha = "b" * 40
    base = renderer.render(
        source_sha=old_sha,
        schema_version=140,
        digests={name: _digest(str(index + 1)) for index, name in enumerate(renderer.SERVICES)},
    )
    updated = renderer.render(
        source_sha=new_sha,
        schema_version=140,
        digests={"conversation-runtime": _digest("f")},
        base_manifest=base,
    )
    for name in set(renderer.SERVICES) - {"conversation-runtime"}:
        assert updated["services"][name] == base["services"][name]
    assert updated["services"]["conversation-runtime"]["sha"] == new_sha
    assert updated["services"]["conversation-runtime"]["digest"] == _digest("f")

    assert validator.validate(
        _ManifestDocument(updated), verify_checkout_artifacts=False,
    ) == updated


def test_incremental_release_requires_complete_base():
    try:
        renderer.render(
            source_sha="b" * 40,
            schema_version=140,
            digests={"conversation-runtime": _digest("f")},
        )
    except ValueError as exc:
        assert "complete base" in str(exc)
    else:
        raise AssertionError("incomplete service provenance was accepted")


def test_service_contract_provenance_is_validated():
    manifest = renderer.render(
        source_sha="a" * 40,
        schema_version=140,
        digests={name: _digest(str(index + 1)) for index, name in enumerate(renderer.SERVICES)},
    )
    manifest["services"]["conversation-runtime"]["contracts_checksum"] = "invalid"
    try:
        validator.validate(_ManifestDocument(manifest), verify_checkout_artifacts=False)
    except ValueError as exc:
        assert "contracts_checksum for conversation-runtime" in str(exc)
    else:
        raise AssertionError("invalid per-service contract checksum was accepted")


def test_contract_consumers_must_use_the_same_exact_version():
    manifest = renderer.render(
        source_sha="a" * 40,
        schema_version=140,
        digests={name: _digest(str(index + 1)) for index, name in enumerate(renderer.SERVICES)},
    )
    manifest["services"]["conversation-runtime"]["contracts_version"] = "3.1.0"
    manifest["services"]["conversation-runtime"]["contracts_checksum"] = _digest("e")
    try:
        validator.validate(_ManifestDocument(manifest), verify_checkout_artifacts=False)
    except ValueError as exc:
        assert "version mismatch between active contract consumers" in str(exc)
    else:
        raise AssertionError("incompatible contract consumers were accepted")


def test_compatible_helper_change_preserves_service_provenance():
    manifest = renderer.render(
        source_sha="a" * 40,
        schema_version=140,
        digests={name: _digest(str(index + 1)) for index, name in enumerate(renderer.SERVICES)},
    )
    original = {name: dict(value) for name, value in manifest["services"].items()}
    manifest["services"]["conversation-runtime"]["contracts_checksum"] = _digest("e")
    assert validator.validate(
        _ManifestDocument(manifest), verify_checkout_artifacts=False,
    ) == manifest
    for name in set(renderer.SERVICES) - {"conversation-runtime"}:
        assert manifest["services"][name] == original[name]
