from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "affected_services", ROOT / "ops/microservices/affected-services.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def test_runtime_only_builds_runtime():
    assert module.affected_services(["apps/conversation-runtime/api/main.py"]) == [
        "conversation-runtime"
    ]


def test_dashboard_and_graphbundle_do_not_build_vps_images():
    assert module.affected_services(["dashboard/app/page.tsx"]) == []
    assert module.affected_services(["data/graph_bundles/example.json"]) == []


def test_release_orchestration_change_does_not_build_service_images():
    assert module.affected_services([
        ".github/workflows/build-monorepo-images.yml",
        "ops/vps/deploy-microservice-blue-green.sh",
    ]) == []


def test_contract_change_builds_only_actual_contract_consumers():
    assert module.affected_services(["packages/brain-contracts/brain_contracts/models.py"]) == [
        "control-plane", "conversation-runtime", "transport"
    ]


def test_shared_auth_change_builds_all_services():
    assert module.affected_services(["packages/brain-shared/brain_shared/auth.py"]) == list(
        module.SERVICES
    )
