from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_qa_contract_routes_mounted_with_and_without_api_prefix() -> None:
    from main import app

    paths = {route.path for route in app.routes}
    expected = [
        "/qa/reset-destructive",
        "/catalog/ingest",
        "/graph/generate",
        "/graph/validate",
        "/faq/approve",
        "/embeds/generate",
        "/sofia/graph-command",
        "/seed/official-real",
        "/sdr/ask",
    ]
    for path in expected:
        assert path in paths
        assert f"/api{path}" in paths
