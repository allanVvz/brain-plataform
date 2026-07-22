from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from utils.env import get_backend_env, is_production_runtime


def test_environment_production_disables_implicit_local_origins(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://dashboard.example.com")
    assert is_production_runtime() is True
    assert get_backend_env()["allowed_origins"] == ["https://dashboard.example.com"]


def test_preview_origin_regex_is_preserved(monkeypatch):
    regex = r"^https://brain-git-[a-z0-9-]+-team\.vercel\.app$"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://dashboard.example.com")
    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", regex)
    assert get_backend_env()["allowed_origin_regex"] == regex

