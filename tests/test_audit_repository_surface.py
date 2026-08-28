from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/microservices/audit-repository-surface.py"
FIXTURE = ROOT / "tests/fixtures/repository-surface/api"


def _module():
    spec = importlib.util.spec_from_file_location("audit_repository_surface", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_audit_follows_helper_calls_and_db_literals():
    result = _module().audit(FIXTURE, "repositories.transport", roots=["main"])

    assert result["reachable_functions"] == ["_helper", "get_message"]
    assert result["unreachable_functions"] == ["dead"]
    assert result["literal_tables"] == ["messages"]
    assert result["literal_rpcs"] == ["claim_message"]
