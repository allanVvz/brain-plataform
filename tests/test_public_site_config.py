from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import personas  # noqa: E402
from services.public_site import DEFAULT_FORMATS  # noqa: E402


BASE_PERSONA = {
    "id": "p1",
    "slug": "baita-conveniencia",
    "name": "Baita Conveniencia",
    "catalog_url": None,
    "config": {},
}


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(personas.auth_service, "current_user", lambda _request: {"role": "admin"})
    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)


def test_public_site_rejects_unknown_format(monkeypatch):
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda slug: BASE_PERSONA)
    monkeypatch.setattr(personas.supabase_client, "list_public_site_formats", lambda enabled_only=True: DEFAULT_FORMATS)

    with pytest.raises(HTTPException) as exc:
        personas.update_public_site(
            "baita-conveniencia",
            personas.PublicSiteUpdate(format_key="blog_generico"),
            request=object(),
        )

    assert exc.value.status_code == 422
    assert "format_key" in str(exc.value.detail)


def test_public_site_rejects_duplicate_site_slug(monkeypatch):
    rows = [
        BASE_PERSONA,
        {
            "id": "p2",
            "slug": "vz-lupas",
            "name": "VZ Lupas",
            "config": {"public_site": {"site_slug": "vitrine-baita", "format_key": "cardapio"}},
        },
    ]
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda slug: BASE_PERSONA)
    monkeypatch.setattr(personas.supabase_client, "get_personas", lambda: rows)
    monkeypatch.setattr(personas.supabase_client, "list_public_site_formats", lambda enabled_only=True: DEFAULT_FORMATS)

    with pytest.raises(HTTPException) as exc:
        personas.update_public_site(
            "baita-conveniencia",
            personas.PublicSiteUpdate(site_slug="vitrine-baita"),
            request=object(),
        )

    assert exc.value.status_code == 409
