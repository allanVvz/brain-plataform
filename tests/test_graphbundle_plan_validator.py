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


def _public_site_bundle(*, publish_brand: bool) -> dict:
    edges = []
    if publish_brand:
        edges.append({
            "source": "brand:retail", "target": "gallery:default",
            "relation_type": "publishes_to", "metadata": {"active": True},
        })
    return {
        "nodes": [
            {"id": "campaign:page", "node_type": "campaign", "data": {"campaign_subtype": "public_site_page"}},
            {"id": "brand:retail", "node_type": "brand", "data": {}},
            {"id": "gallery:default", "node_type": "gallery", "data": {}},
        ],
        "edges": edges,
    }


def test_public_site_preflight_requires_one_published_brand() -> None:
    with pytest.raises(ValueError, match="exactly one published Brand; found 0"):
        MODULE._validate_public_site_projection(_public_site_bundle(publish_brand=False))


def test_public_site_preflight_accepts_one_published_brand() -> None:
    MODULE._validate_public_site_projection(_public_site_bundle(publish_brand=True))


def test_graphbundle_workflow_pauses_only_the_target_persona() -> None:
    workflow = (ROOT / ".github/workflows/publish-graphbundle.yml").read_text(encoding="utf-8")
    assert "target persona binding is not safety paused" in workflow
    assert ".deploy/control/claims-paused.json" not in workflow


def test_public_site_preflight_requires_all_groups_and_only_imaged_products() -> None:
    bundle = _public_site_bundle(publish_brand=True)
    bundle["nodes"].extend([
        {"id": "group:dresses", "node_type": "product_group", "data": {}},
        {"id": "product:dress", "node_type": "product", "data": {}},
        {"id": "asset:dress", "node_type": "asset", "data": {}},
    ])
    bundle["edges"].extend([
        {"source": "asset:dress", "target": "gallery:default", "relation_type": "publishes_to", "metadata": {"active": True}},
        # Asset publicado precisa da ligacao canonica com a Gallery; sem ela a
        # invariante de gallery_asset dispara antes e o teste nunca chegaria a
        # exercitar as checagens de ProductGroup/produto sem imagem.
        {"source": "asset:dress", "target": "gallery:default", "relation_type": "gallery_asset", "metadata": {"active": True}},
        {"source": "product:dress", "target": "asset:dress", "relation_type": "uses_asset", "metadata": {"role": "product_image"}},
    ])
    with pytest.raises(ValueError, match="must publish every ProductGroup"):
        MODULE._validate_public_site_projection(bundle)
    bundle["edges"].append(
        {"source": "group:dresses", "target": "gallery:default", "relation_type": "publishes_to", "metadata": {"active": True}}
    )
    with pytest.raises(ValueError, match="missing=product:dress"):
        MODULE._validate_public_site_projection(bundle)
    bundle["edges"].append(
        {"source": "product:dress", "target": "gallery:default", "relation_type": "publishes_to", "metadata": {"active": True}}
    )
    MODULE._validate_public_site_projection(bundle)
