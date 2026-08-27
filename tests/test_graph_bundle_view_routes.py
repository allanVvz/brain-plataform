from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from routes import graph_bundles
from services import graph_bundle_view


def _request():
    return SimpleNamespace(
        state=SimpleNamespace(
            user={"id": "admin-1", "role": "admin", "account_type": "internal"},
            persona_access=[],
        )
    )


def _minimal_bundle(slug: str) -> dict:
    return {
        "bundle_version": "1.0",
        "persona": {"id": f"persona-{slug}", "slug": slug},
        "metadata": {
            "publication_allowed": False,
            "embedding_profile": {
                "embedding_provider": "local",
                "embedding_model": "test",
                "embedding_dimension": 3,
            },
        },
        "nodes": [
            {
                "id": f"persona:{slug}",
                "node_type": "persona",
                "slug": slug,
                "title": slug,
                "summary": "Draft",
                "status": "validated",
                "data": {"source": "test", "status": "validated"},
            }
        ],
        "edges": [],
    }


def test_versions_keeps_zypi_blocked_draft_visible(monkeypatch, tmp_path):
    monkeypatch.setattr(graph_bundle_view, "SOFIA_SESSION_ROOT", tmp_path)
    monkeypatch.setattr(
        graph_bundle_view.supabase_client,
        "get_persona",
        lambda slug: {"id": "zypi-id", "slug": slug, "name": "Zypi"},
    )
    monkeypatch.setattr(graph_bundle_view, "_publication_rows", lambda *_a, **_k: [])

    payload = graph_bundle_view.list_versions("zypi-shop")

    draft = next(item for item in payload["versions"] if item["ref"].startswith("bundle:"))
    assert draft["source"] == "draft"
    assert draft["state"] == "blocked"
    assert draft["validation_error_count"] > 0
    assert payload["default_ref"] == draft["ref"]


def test_draft_ref_cannot_cross_persona_scope(monkeypatch, tmp_path):
    root = tmp_path / "bundles"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir(parents=True)
    (root / "alpha" / "v1.json").write_text(json.dumps(_minimal_bundle("alpha")), encoding="utf-8")
    (root / "beta" / "v1.json").write_text(json.dumps(_minimal_bundle("beta")), encoding="utf-8")
    monkeypatch.setattr(graph_bundle_view, "BUNDLE_ROOT", root)
    monkeypatch.setattr(graph_bundle_view, "SOFIA_SESSION_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(
        graph_bundle_view.supabase_client,
        "get_persona",
        lambda slug: {"id": f"persona-{slug}", "slug": slug},
    )

    alpha = graph_bundle_view.get_view("alpha", source="draft", ref="bundle:v1.json")
    assert alpha["persona"]["slug"] == "alpha"
    assert alpha["document"]["persona"]["slug"] == "alpha"

    (root / "alpha" / "v1.json").unlink()
    with pytest.raises(graph_bundle_view.GraphBundleViewNotFound):
        graph_bundle_view.get_view("alpha", source="draft", ref="bundle:v1.json")


def test_publication_catalog_and_view_expose_staged_and_active(monkeypatch, tmp_path):
    monkeypatch.setattr(graph_bundle_view, "BUNDLE_ROOT", tmp_path / "bundles")
    monkeypatch.setattr(graph_bundle_view, "SOFIA_SESSION_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(
        graph_bundle_view.supabase_client,
        "get_persona",
        lambda slug: {"id": "persona-alpha", "slug": slug, "name": "Alpha"},
    )
    rows = [
        {
            "id": "pub-active",
            "persona_id": "persona-alpha",
            "version": 4,
            "checksum": "sha256:active",
            "status": "active",
            "compiler_version": "3.0",
            "document_json": {"nodes": [], "edges": [], "branch_memberships": {}},
        },
        {
            "id": "pub-staged",
            "persona_id": "persona-alpha",
            "version": 5,
            "checksum": "sha256:staged",
            "status": "compiled",
            "compiler_version": "3.0",
            "document_json": {"nodes": [], "edges": [], "branch_memberships": {}},
        },
    ]
    monkeypatch.setattr(graph_bundle_view, "_publication_rows", lambda *_a, **_k: rows)

    catalog = graph_bundle_view.list_versions("alpha")
    assert [item["state"] for item in catalog["versions"]] == ["active", "staged"]
    assert catalog["default_ref"] == "publication:pub-active"

    staged = graph_bundle_view.get_view(
        "alpha", source="publication", ref="publication:pub-staged"
    )
    assert staged["state"] == "staged"
    assert staged["checksum"] == "sha256:staged"
    assert staged["read_only"] is True


def test_routes_authenticate_and_forward_read_only_queries(monkeypatch):
    calls = []
    monkeypatch.setattr(
        graph_bundles.auth_service,
        "assert_persona_access",
        lambda request, persona_slug: calls.append(("auth", persona_slug)),
    )
    monkeypatch.setattr(
        graph_bundles.graph_bundle_view,
        "list_versions",
        lambda slug: {"persona": {"slug": slug}, "versions": [], "read_only": True},
    )
    monkeypatch.setattr(
        graph_bundles.graph_bundle_view,
        "get_view",
        lambda slug, source, ref: {"persona": {"slug": slug}, "source": source, "ref": ref, "read_only": True},
    )

    versions = graph_bundles.graph_bundle_versions(_request(), persona_slug="alpha")
    view = graph_bundles.graph_bundle_view_get(
        _request(), persona_slug="alpha", source="draft", ref="bundle:v1.json"
    )

    assert calls == [("auth", "alpha"), ("auth", "alpha")]
    assert versions["read_only"] is True
    assert view["read_only"] is True


def test_router_exposes_only_get_operations():
    graph_routes = [route for route in graph_bundles.router.routes if route.path.startswith("/graph-bundles/")]
    assert graph_routes
    assert all(route.methods == {"GET"} for route in graph_routes)


def test_route_maps_missing_ref_to_404(monkeypatch):
    monkeypatch.setattr(graph_bundles.auth_service, "assert_persona_access", lambda *_a, **_k: None)
    monkeypatch.setattr(
        graph_bundles.graph_bundle_view,
        "get_view",
        lambda *_a, **_k: (_ for _ in ()).throw(
            graph_bundle_view.GraphBundleViewNotFound("graph_bundle_draft_not_found")
        ),
    )

    with pytest.raises(HTTPException) as exc:
        graph_bundles.graph_bundle_view_get(
            _request(), persona_slug="alpha", source="draft", ref="bundle:missing.json"
        )
    assert exc.value.status_code == 404
