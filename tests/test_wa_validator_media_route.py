"""Safe HTTP contract for direct-validator media fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for candidate in (API_DIR, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _client():
    from routes import wa_validator as route

    app = FastAPI()
    app.include_router(route.router)
    return route, TestClient(app)


def test_media_fixture_is_scoped_and_never_enqueues_outbound(monkeypatch):
    route, client = _client()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WA_VALIDATOR_RUN_ENABLED", "true")
    monkeypatch.setattr(route, "_assert_session_access", lambda _request, session_id: {"id": session_id})

    captured = {}

    def store(session_id: str, **kwargs):
        captured.update({"session_id": session_id, **kwargs})
        return {
            "session_id": session_id,
            "asset": {"id": "asset-1", "status": "ready"},
            "outbound_enqueued": False,
        }

    monkeypatch.setattr(route.wa_validator_service, "store_validation_media", store)
    response = client.post(
        "/wa-validator/sessions/session-1/media",
        files={"file": ("ex 1.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
        data={"idempotency_key": "media-0123456789abcdef"},
    )

    assert response.status_code == 200
    assert response.json()["outbound_enqueued"] is False
    assert captured["session_id"] == "session-1"
    assert captured["filename"] == "ex 1.png"
    assert captured["content_type"] == "image/png"
    assert captured["content"].startswith(b"\x89PNG")


def test_media_fixture_obeys_the_production_run_kill_switch(monkeypatch):
    _route, client = _client()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("WA_VALIDATOR_RUN_ENABLED", raising=False)

    response = client.post(
        "/wa-validator/sessions/session-1/media",
        files={"file": ("ex 1.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
        data={"idempotency_key": "media-0123456789abcdef"},
    )

    assert response.status_code == 503
