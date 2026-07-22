from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from middleware.auth import is_public_path


def test_public_menu_contract_does_not_expose_nested_admin_routes():
    assert is_public_path("/api/menu/baita-conveniencia") is True
    assert is_public_path("/api/menu/baita-conveniencia/admin-assets") is False
    assert is_public_path("/api/menu/baita-conveniencia/admin-blocks") is False


def test_internal_diagnostics_and_docs_require_session():
    assert is_public_path("/health") is True
    assert is_public_path("/health/ready") is True
    assert is_public_path("/health/storage") is False
    assert is_public_path("/docs") is False
    assert is_public_path("/openapi.json") is False
