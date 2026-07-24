from __future__ import annotations

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

from routes import graph_documents, qa_contract  # noqa: E402
from schemas.graph_json_v2 import GraphJson  # noqa: E402
from services import graph_json_v2_validator  # noqa: E402


def _request(role: str = "admin", access: list[dict] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            user={"id": "u1", "role": role},
            persona_access=access or [],
        )
    )


def _graph_json(persona_slug: str = "baita-conveniencia") -> dict:
    return {
        "schema_version": "2.0",
        "graph_id": f"{persona_slug}-main",
        "tenant": "local",
        "persona_slug": persona_slug,
        "status": "draft",
        "nodes": [
            {"id": "node:persona:baita", "node_type": "persona", "slug": persona_slug, "label": "Baita"},
            {
                "id": "node:brand:baita",
                "node_type": "brand",
                "slug": "baita",
                "label": "Baita",
                "parent_id": "node:persona:baita",
            },
        ],
        "edges": [
            {
                "id": "edge:persona-brand",
                "source": "node:persona:baita",
                "target": "node:brand:baita",
                "relation": "belongs_to_persona",
                "primary_tree": True,
            }
        ],
    }


def test_graph_json_v2_validator_accepts_canonical_persona_brand():
    graph = GraphJson.model_validate(_graph_json())
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid is True
    assert errors == []


def test_graph_json_v2_validator_rejects_cross_persona_payload():
    payload = _graph_json()
    payload["persona_slug"] = "tock-fatal"
    graph = GraphJson.model_validate(payload)
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid is False
    assert any("persona ownership mismatch" in error for error in errors)


def test_graph_json_v2_validator_requires_asset_to_finish_at_gallery():
    payload = _graph_json()
    payload["nodes"] += [
        {"id": "node:gallery:default", "node_type": "gallery", "slug": "gallery-default", "label": "Gallery", "parent_id": "node:persona:baita"},
        {"id": "node:asset:brand", "node_type": "asset", "slug": "brand-image", "label": "Imagem", "parent_id": "node:brand:baita"},
    ]
    payload["edges"] += [
        {"id": "edge:persona-gallery", "source": "node:persona:baita", "target": "node:gallery:default", "relation": "contains", "primary_tree": True},
        {"id": "edge:brand-asset", "source": "node:brand:baita", "target": "node:asset:brand", "relation": "uses_asset", "primary_tree": True},
    ]
    graph = GraphJson.model_validate(payload)
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid is False
    assert any("must have a secondary asset -> gallery edge" in error for error in errors)


def test_graph_json_v2_validator_allows_unfed_embedded_without_persona_edge():
    payload = _graph_json()
    payload["nodes"].append(
        {"id": "node:embedded:default", "node_type": "embedded", "slug": "embedded-default", "label": "Embedded", "parent_id": "node:persona:baita"}
    )
    graph = GraphJson.model_validate(payload)
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid is True, errors


def test_current_requires_persona_access(monkeypatch):
    monkeypatch.setattr(graph_documents, "_latest_event", lambda persona_slug, brand_slug: None)
    request = _request(
        role="user",
        access=[{"persona_slug": "tock-fatal", "can_view": True, "can_edit": True}],
    )
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_current(request, persona_slug="baita-conveniencia")
    assert exc.value.status_code == 403


def test_apply_patch_requires_edit_access(monkeypatch):
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: None)
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "save_version", lambda persona_slug, version, graph: "abc")
    request = _request(
        role="user",
        access=[{"persona_slug": "baita-conveniencia", "can_view": True, "can_edit": False}],
    )
    body = graph_documents.ApplyPatchBody(persona_slug="baita-conveniencia", graph_json=_graph_json())
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_apply_patch(body, request)
    assert exc.value.status_code == 403


def test_apply_patch_rejects_body_graph_persona_mismatch(monkeypatch):
    request = _request(role="admin")
    body = graph_documents.ApplyPatchBody(persona_slug="tock-fatal", graph_json=_graph_json("baita-conveniencia"))
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_apply_patch(body, request)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "GRAPH_PERSONA_MISMATCH"


def test_publish_persists_event_and_reindexes(monkeypatch):
    calls: dict[str, object] = {}
    monkeypatch.setattr(graph_documents, "_latest_event", lambda persona_slug, brand_slug: None)
    monkeypatch.setattr(
        graph_documents.graph_json_v2_store,
        "save_version",
        lambda persona_slug, version, graph, **kwargs: "pub123",
    )
    def fake_import_graph_json(**kwargs):
        calls["reindex"] = kwargs
        return {"ok": True, "nodes_imported": len(kwargs["graph_json"].nodes), "edges_imported": len(kwargs["graph_json"].edges)}

    monkeypatch.setattr(graph_documents.graph_json_importer, "import_graph_json", fake_import_graph_json)
    body = graph_documents.PublishGraphDocumentBody(persona_slug="baita-conveniencia", graph_json=_graph_json())
    result = graph_documents.graph_document_publish(body, _request(role="admin"))
    assert result["ok"] is True
    assert result["version"] == 1
    assert result["reindex_ok"] is True
    assert "reindex" in calls


def test_sofia_graph_command_requires_persona_access(monkeypatch):
    request = _request(
        role="user",
        access=[{"persona_slug": "tock-fatal", "can_view": True, "can_edit": True}],
    )
    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "get_persona",
        lambda slug: {"id": "p1", "slug": slug},
    )

    def deny_access(request, persona_id=None, persona_slug=None):
        raise HTTPException(403, "Persona access denied")

    monkeypatch.setattr(qa_contract.auth_service, "assert_persona_access", deny_access)
    body = qa_contract.SofiaGraphCommandBody(
        persona_slug="baita-conveniencia",
        command="focus_node node:brand:baita",
        context=qa_contract.SofiaGraphCommandContext(selected_node_id="node:brand:baita"),
    )
    with pytest.raises(HTTPException) as exc:
        qa_contract.sofia_graph_command(body, request)
    assert exc.value.status_code == 403
