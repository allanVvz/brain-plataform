import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "graphbundle_plan_validator", ROOT / "ops/microservices/validate-graphbundle-plan.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _checksum(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _files(tmp_path: Path) -> tuple[Path, Path, str, str]:
    bundle_dir = tmp_path / "graph_bundles"
    bundle_dir.mkdir()
    bundle = bundle_dir / "test-bundle.json"
    plan = tmp_path / "plan.json"
    draft, runtime = _checksum("draft"), _checksum("runtime")
    bundle.write_text(json.dumps({"persona": {"slug": "test-persona"}}), encoding="utf-8")
    plan.write_text(json.dumps({
        "disposition": "awaiting_approval", "publication_allowed": True,
        "validation_errors": [], "draft_checksum": draft, "runtime_checksum": runtime,
        "next_version": 2, "branches_affected": ["audience:retail"],
    }), encoding="utf-8")
    return bundle, plan, draft, runtime


def test_graphbundle_plan_validator_accepts_approved_scoped_plan(tmp_path):
    bundle, plan, draft, runtime = _files(tmp_path)
    result = MODULE.validate(bundle, plan, persona_slug="test-persona",
                             approved_draft_checksum=draft, approved_runtime_checksum=runtime,
                             bundle_root=bundle.parent)
    assert result["next_version"] == 2


@pytest.mark.parametrize("field,value", [
    ("publication_allowed", False), ("validation_errors", ["missing source"]),
    ("draft_checksum", "sha256:" + "0" * 64),
])
def test_graphbundle_plan_validator_rejects_nonpublishable_or_drifted_plan(tmp_path, field, value):
    bundle, plan, draft, runtime = _files(tmp_path)
    payload = json.loads(plan.read_text(encoding="utf-8"))
    payload[field] = value
    plan.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        MODULE.validate(bundle, plan, persona_slug="test-persona",
                        approved_draft_checksum=draft, approved_runtime_checksum=runtime,
                        bundle_root=bundle.parent)
