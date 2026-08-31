import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_manifest_validator",
    ROOT / "ops/microservices/validate-release-manifest.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _sha256(path: Path) -> str:
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _manifest() -> dict:
    source_sha = "a" * 40
    digest = "sha256:" + "b" * 64
    return {
        "source_sha": source_sha,
        "contracts_version": "1.0.0",
        "schema_version": 131,
        "route_map_checksum": _sha256(ROOT / "ops/microservices/route-map.json"),
        "n8n_checksum": _sha256(ROOT / "apps/conversation-runtime/n8n/persona-conversation-template.json"),
        "services": {
            "gateway": {"repository": "allanVvz/brain-plataform", "sha": source_sha,
                        "digest": digest, "required_schema_version": 131},
            "control-plane": {"repository": "allanVvz/brain-control-plane", "sha": "c" * 40,
                              "digest": digest, "required_schema_version": 131},
            "conversation-runtime": {"repository": "allanVvz/brain-conversation-runtime", "sha": "d" * 40,
                                     "digest": digest, "required_schema_version": 131},
            "transport": {"repository": "allanVvz/brain-transport", "sha": "e" * 40,
                          "digest": digest, "required_schema_version": 131},
        },
    }


def test_validator_accepts_exact_release_boundary(tmp_path):
    path = tmp_path / "release.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert MODULE.validate(path)["schema_version"] == 131


def test_validator_accepts_additive_contract_1_1_during_blue_green(tmp_path):
    manifest = _manifest()
    manifest["contracts_version"] = "1.1.0"
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert MODULE.validate(path)["contracts_version"] == "1.1.0"


def test_validator_rejects_unknown_contract_version(tmp_path):
    manifest = _manifest()
    manifest["contracts_version"] = "2.0.0"
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="contracts_version"):
        MODULE.validate(path)


@pytest.mark.parametrize("mutation", ["service", "schema", "checksum", "gateway_sha"])
def test_validator_rejects_unreleasable_manifest(tmp_path, mutation):
    manifest = _manifest()
    if mutation == "service":
        manifest["services"]["extra"] = manifest["services"]["transport"]
    elif mutation == "schema":
        manifest["schema_version"] = 130
    elif mutation == "checksum":
        manifest["route_map_checksum"] = "sha256:" + "0" * 64
    else:
        manifest["services"]["gateway"]["sha"] = "f" * 40
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        MODULE.validate(path)
