from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("classify_release", ROOT / "ops/release/classify-release.py")
module = module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
POLICY = json.loads((ROOT / "ops/release/release-services.json").read_text())


def test_content_and_documentation_never_build_images():
    result = module.classify(["data/graph_bundles/acme/v1.json", "docs/graph.md"], POLICY)
    assert result["content_only"] is True
    assert result["services"] == []
    assert result["build_images"] is False


def test_control_plane_change_is_isolated():
    result = module.classify(["apps/control-plane/api/routes/graph_bundles.py"], POLICY)
    assert result["services"] == ["control-plane"]
    assert result["runtime_approval"] is True


def test_fixture_inside_service_does_not_build_image():
    result = module.classify(
        ["apps/control-plane/api/tests/fixtures/graph.json"], POLICY
    )
    assert result["content_only"] is True
    assert result["services"] == []
    assert result["build_images"] is False


def test_release_policy_and_workflow_changes_are_infrastructure():
    result = module.classify(
        ["ops/release/classify-release.py", ".github/workflows/release-main.yml"],
        POLICY,
    )
    assert result["infrastructure"] is True
    assert result["services"] == []
    assert set(result["deploy_services"]) == set(POLICY["services"])


def test_contract_change_selects_every_service_and_runtime_gate():
    result = module.classify(["packages/brain-contracts/brain_contracts/events.py"], POLICY)
    assert set(result["services"]) == set(POLICY["services"])
    assert result["runtime_approval"] is True


def test_dashboard_and_migration_are_separate_impacts():
    result = module.classify(["dashboard/app/page.tsx", "supabase/migrations/999_x.sql"], POLICY)
    assert result["dashboard"] is True
    assert result["schema"] is True
    assert result["services"] == []


def test_repository_has_one_migration_per_version_and_latest_is_134():
    spec = spec_from_file_location(
        "manifest_renderer", ROOT / "ops/microservices/render-monorepo-release-manifest.py"
    )
    renderer = module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(renderer)
    assert renderer.latest_schema_version() == 134


def test_manifest_preserves_unchanged_service_identity():
    render_spec = spec_from_file_location(
        "render_release", ROOT / "ops/release/render-release.py"
    )
    render_release = module_from_spec(render_spec)
    assert render_spec.loader
    render_spec.loader.exec_module(render_release)
    active = json.loads(
        (ROOT / "ops/microservices/release-manifest.json").read_text()
    )
    changed = "control-plane"
    new_digest = "sha256:" + "a" * 64
    if new_digest == active["services"][changed]["digest"]:
        new_digest = "sha256:" + "b" * 64
    result = render_release.render_payload(
        active=active,
        changed={changed},
        new_digests={changed: new_digest},
        source_sha="f" * 40,
    )
    assert result["services"][changed]["digest"] == new_digest
    assert result["services"][changed]["sha"] == "f" * 40
    for service in set(active["services"]) - {changed}:
        assert result["services"][service] == active["services"][service]


def test_unified_release_never_resumes_agents_automatically():
    workflow = (ROOT / ".github/workflows/release-main.yml").read_text(encoding="utf-8")
    assert "production-resume" not in workflow
    assert "resume-microservice-workers.sh" not in workflow
