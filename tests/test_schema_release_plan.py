import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "schema_release_plan", ROOT / "ops/microservices/plan-schema-release.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _checksum(path: Path) -> str:
    return "sha256:" + hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()


def _manifest() -> dict:
    digest = "sha256:" + "b" * 64
    source_sha = "a" * 40
    services = {
        "gateway": ("allanVvz/brain-plataform", source_sha),
        "control-plane": ("allanVvz/brain-control-plane", "c" * 40),
        "conversation-runtime": ("allanVvz/brain-conversation-runtime", "d" * 40),
        "transport": ("allanVvz/brain-transport", "e" * 40),
    }
    return {
        "source_sha": source_sha,
        "contracts_version": "1.0.0",
        "schema_version": 132,
        "route_map_checksum": _checksum(ROOT / "ops/microservices/route-map.json"),
        "n8n_checksum": _checksum(ROOT / "api/n8n-workflows/persona-conversation-template.json"),
        "services": {
            name: {"repository": repository, "sha": sha, "digest": digest,
                   "required_schema_version": 131}
            for name, (repository, sha) in services.items()
        },
    }


def test_schema_plan_ends_at_manifest_version_and_is_checksummed(tmp_path):
    path = tmp_path / "release.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    plan = MODULE.build_plan(path)
    assert plan["schema_version"] == 132
    assert plan["target_migration"] == "132_runtime_vector_distance_grant.sql"
    assert plan["migrations"][-1]["version"] == 132
    assert plan["inventory_checksum"].startswith("sha256:")


def test_schema_plan_rejects_manifest_behind_checkout(tmp_path):
    manifest = _manifest()
    manifest["schema_version"] = 130
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        MODULE.build_plan(path)
