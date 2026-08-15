"""A customer's media is readable only within its own persona.

`GET /knowledge/file` requires a session but does no persona scoping — any
authenticated user can read any object in the allowed buckets. That is
tolerable for marketing material in a public bucket; it is not for a photo or
voice note a customer sent. Hence `/assets/{id}/media`, which is scoped, and
the private `whatsapp-media` bucket, which has no public URL at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

AUDIO = b"OggS" + b"\x00" * 508  # 512 bytes, enough to exercise ranges


@pytest.fixture
def client(monkeypatch):
    from routes import assets as mod

    app = FastAPI()
    app.include_router(mod.router)
    return mod, TestClient(app)


def _wire_asset(monkeypatch, mod, persona_id="persona-1", status="ready"):
    asset = {
        "id": "asset-1",
        "persona_id": persona_id,
        "status": status,
        "mime_type": "audio/ogg",
        "storage_bucket": "whatsapp-media" if status == "ready" else None,
        "storage_path": "persona-1/42/asset-1-nota.ogg" if status == "ready" else None,
        "metadata": {},
    }
    monkeypatch.setattr(mod.supabase_client, "get_asset", lambda _id: asset)
    monkeypatch.setattr(mod.supabase_client, "download_from_storage", lambda b, p: AUDIO)
    return asset


def test_media_is_served_within_the_owning_persona(monkeypatch, client):
    mod, http = client
    _wire_asset(monkeypatch, mod)
    monkeypatch.setattr(mod.auth_service, "assert_persona_access", lambda *a, **k: None)

    resp = http.get("/assets/asset-1/media")
    assert resp.status_code == 200
    assert resp.content == AUDIO
    assert resp.headers["content-type"].startswith("audio/ogg")
    # Range support is what makes a voice note seekable in the browser.
    assert resp.headers["accept-ranges"] == "bytes"
    # Customer content must never enter a cache shared between personas.
    assert "private" in resp.headers["cache-control"]


def test_another_persona_is_refused(monkeypatch, client):
    mod, http = client
    _wire_asset(monkeypatch, mod, persona_id="persona-A")

    def _deny(*_a, **_k):
        raise HTTPException(403, "forbidden")

    monkeypatch.setattr(mod.auth_service, "assert_persona_access", _deny)

    assert http.get("/assets/asset-1/media").status_code == 403


def test_range_request_returns_partial_content(monkeypatch, client):
    mod, http = client
    _wire_asset(monkeypatch, mod)
    monkeypatch.setattr(mod.auth_service, "assert_persona_access", lambda *a, **k: None)

    resp = http.get("/assets/asset-1/media", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert resp.content == AUDIO[:100]
    assert resp.headers["content-range"] == f"bytes 0-99/{len(AUDIO)}"


def test_media_still_downloading_reports_not_ready(monkeypatch, client):
    """A file whose bytes have not landed yet is a 409, not a broken 200."""
    mod, http = client
    _wire_asset(monkeypatch, mod, status="reading")
    monkeypatch.setattr(mod.auth_service, "assert_persona_access", lambda *a, **k: None)

    resp = http.get("/assets/asset-1/media")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "media_not_ready"


def test_whatsapp_bucket_is_not_exposed_by_the_unscoped_file_route():
    """The private bucket must stay out of /knowledge/file's allowlist."""
    source = (API_DIR / "routes" / "knowledge.py").read_text(encoding="utf-8")
    marker = 'allowed_buckets = {"assets-raw", "assets-derived", "knowledge"}'
    assert marker in source, "the /knowledge/file allowlist changed — re-check media scoping"
    assert "whatsapp-media" not in source
