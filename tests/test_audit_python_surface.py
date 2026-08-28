from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/microservices/audit-python-surface.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_python_surface", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_follows_internal_imports_and_excludes_tests_and_scripts():
    api = ROOT / "tests/fixtures/python-surface/api"

    result = _module().audit(api, ["main"])

    assert result["reachable"] == ["main", "routes", "routes.health"]
    assert result["unreachable"] == ["routes.dead"]
