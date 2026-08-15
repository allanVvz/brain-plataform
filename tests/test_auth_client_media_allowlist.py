from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from middleware.auth import is_client_path_allowed


def test_client_can_only_get_the_exact_asset_media_path():
    assert is_client_path_allowed("GET", "/assets/asset-1/media") is True
    assert is_client_path_allowed("GET", "/assets/asset-1") is False
    assert is_client_path_allowed("GET", "/assets") is False
    assert is_client_path_allowed("GET", "/assets/asset-1/media/metadata") is False


def test_client_asset_mutations_remain_blocked():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert is_client_path_allowed(method, "/assets/asset-1/media") is False
        assert is_client_path_allowed(method, "/assets/asset-1") is False
