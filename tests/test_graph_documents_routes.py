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


from routes import graph_documents


def _req():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


def _graph_json():
    return {
        "schema_version": "2.0",
        "graph_id": "g1",
        "tenant": "qa",
        "persona_slug": "allanvvz",
        "brand_slug": "vz-lupas",
        "status": "draft",
        "nodes": [
            {"id": "n1", "node_type": "persona", "slug": "allanvvz", "label": "Allan"},
            {"id": "n2", "node_type": "brand", "slug": "vz-lupas", "label": "VZ", "parent_id": "n1"},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "relation": "main"}],
    }


def test_current_success_and_auth_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(
        graph_documents,
        "_latest_event",
        lambda persona_slug, brand_slug: {
            "entity_id": "allanvvz:default:v1",
            "created_at": "2026-05-29T00:00:00Z",
            "payload": {
                "persona_slug": persona_slug,
                "brand_slug": brand_slug,
                "version": 1,
                "graph_json": _graph_json(),
                "source": "seed",
                "note": "ok",
            },
        },
    )
    ok = graph_documents.graph_document_current(_req(), persona_slug="allanvvz", brand_slug=None)
    assert ok["version"] == 1

    monkeypatch.setattr(
        graph_documents.auth_service,
        "current_user",
        lambda request: (_ for _ in ()).throw(HTTPException(401, "Sessao obrigatoria.")),
    )
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_current(_req(), persona_slug="allanvvz", brand_slug=None)
    assert exc.value.status_code == 401


def test_apply_patch_success_and_validation_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: None)
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "save_version", lambda persona_slug, version, graph, **kwargs: "abc123")
    monkeypatch.setattr(
        graph_documents.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: {"ok": True, "nodes_imported": 2, "edges_imported": 1},
    )

    body = graph_documents.ApplyPatchBody(persona_slug="allanvvz", graph_json=_graph_json())
    ok = graph_documents.graph_document_apply_patch(body, _req())
    assert ok["ok"] is True
    assert ok["version"] == 1

    bad = _graph_json()
    bad["schema_version"] = "1.0"
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_apply_patch(
            graph_documents.ApplyPatchBody(persona_slug="allanvvz", graph_json=bad), _req()
        )
    assert exc.value.status_code == 422


def test_publish_success_and_validation_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(graph_documents, "_latest_event", lambda persona_slug, brand_slug: None)
    monkeypatch.setattr(
        graph_documents.graph_json_v2_store,
        "save_version",
        lambda persona_slug, version, graph, **kwargs: "pub123",
    )
    reindex_calls = []
    monkeypatch.setattr(
        graph_documents.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: reindex_calls.append(kwargs)
        or {"ok": True, "nodes_imported": len(kwargs["graph_json"].nodes), "edges_imported": len(kwargs["graph_json"].edges)},
    )
    body = graph_documents.PublishGraphDocumentBody(
        persona_slug="allanvvz",
        brand_slug=None,
        graph_json=_graph_json(),
        source="import",
        note="ok",
    )
    ok = graph_documents.graph_document_publish(body, _req())
    assert ok["ok"] is True
    assert ok["version"] == 1
    # Publishing materializes the derived tables (reindex).
    assert ok["reindex_ok"] is True
    assert ok["nodes_imported"] == 2
    assert reindex_calls, "publish must trigger import_graph_json"

    bad = _graph_json()
    bad["schema_version"] = "legacy"
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_publish(
            graph_documents.PublishGraphDocumentBody(persona_slug="allanvvz", graph_json=bad), _req()
        )
    assert exc.value.status_code == 422


def test_import_json_success_and_validation_error(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: None)
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "save_version", lambda persona_slug, version, graph, **kwargs: "imp123")
    monkeypatch.setattr(
        graph_documents.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: calls.append(kwargs) or {
            "ok": True,
            "graph_id": kwargs["graph_json"].graph_id,
            "nodes_imported": len(kwargs["graph_json"].nodes),
            "edges_imported": len(kwargs["graph_json"].edges),
            "knowledge_item_ids": [],
            "knowledge_node_ids": [],
            "knowledge_edge_ids": [],
            "written_files": [],
        },
    )

    ok = graph_documents.graph_document_import_json(
        graph_documents.ImportGraphDocumentBody(
            persona_slug="allanvvz",
            graph_json=_graph_json(),
            source="test",
            session_id="sess-1",
        ),
        _req(),
    )
    assert ok["ok"] is True
    assert ok["version"] == 1
    assert ok["checksum"] == "imp123"
    assert calls[0]["source"] == "test"
    assert calls[0]["session_id"] == "sess-1"

    bad = _graph_json()
    bad["nodes"][1]["parent_id"] = None
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_import_json(
            graph_documents.ImportGraphDocumentBody(persona_slug="allanvvz", graph_json=bad),
            _req(),
        )
    assert exc.value.status_code == 422


def test_rollback_success_and_not_found(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    graph_obj = graph_documents.GraphJson.model_validate(_graph_json())
    monkeypatch.setattr(
        graph_documents.graph_json_v2_store,
        "load_version",
        lambda persona_slug, version: graph_obj if version == 1 else None,
    )
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: (1, graph_obj))
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "save_version", lambda persona_slug, version, graph, **kwargs: "rb123")
    monkeypatch.setattr(
        graph_documents.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: {"ok": True, "nodes_imported": 2, "edges_imported": 1},
    )

    ok = graph_documents.graph_document_rollback(
        graph_documents.RollbackBody(persona_slug="allanvvz", version=1),
        _req(),
    )
    assert ok["ok"] is True
    assert ok["new_version"] == 2

    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_rollback(
            graph_documents.RollbackBody(persona_slug="allanvvz", version=99),
            _req(),
        )
    assert exc.value.status_code == 404


def test_reindex_success_and_validation_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    graph_obj = graph_documents.GraphJson.model_validate(_graph_json())
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: (3, graph_obj))
    monkeypatch.setattr(
        graph_documents.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: {"ok": True, "nodes_imported": len(kwargs["graph_json"].nodes), "edges_imported": len(kwargs["graph_json"].edges)},
    )
    ok = graph_documents.graph_document_reindex(graph_documents.ReindexBody(persona_slug="allanvvz"), _req())
    assert ok["ok"] is True
    assert ok["indexed_nodes"] == 2
    assert ok["reindex_ok"] is True

    invalid_graph = graph_documents.GraphJson.model_validate(_graph_json())
    invalid_graph.schema_version = "1.0"
    monkeypatch.setattr(graph_documents.graph_json_v2_store, "load_current", lambda persona_slug: (4, invalid_graph))
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_reindex(graph_documents.ReindexBody(persona_slug="allanvvz"), _req())
    assert exc.value.status_code == 422


def test_versions_success_and_auth_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(
        graph_documents.supabase_client,
        "list_system_events",
        lambda **kwargs: [
            {
                "entity_id": "allanvvz:default:v1",
                "created_at": "2026-05-29T00:00:00Z",
                "payload": {"persona_slug": "allanvvz", "brand_slug": None, "version": 1, "source": "seed", "note": None},
            }
        ],
    )
    ok = graph_documents.graph_document_versions(_req(), persona_slug="allanvvz", brand_slug=None)
    assert len(ok["versions"]) == 1

    monkeypatch.setattr(
        graph_documents.auth_service,
        "current_user",
        lambda request: (_ for _ in ()).throw(HTTPException(401, "Sessao obrigatoria.")),
    )
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_versions(_req(), persona_slug="allanvvz", brand_slug=None)
    assert exc.value.status_code == 401


def test_events_success_and_auth_error(monkeypatch):
    monkeypatch.setattr(graph_documents.auth_service, "current_user", lambda request: {"id": "u1", "role": "admin"})
    monkeypatch.setattr(
        graph_documents.supabase_client,
        "list_system_events",
        lambda **kwargs: [
            {
                "id": "evt1",
                "event_type": "graph_document_published",
                "entity_id": "allanvvz:default:v1",
                "created_at": "2026-05-29T00:00:00Z",
                "payload": {"persona_slug": "allanvvz", "brand_slug": None, "version": 1},
            }
        ],
    )
    ok = graph_documents.graph_document_events(_req(), persona_slug="allanvvz", brand_slug=None, limit=10)
    assert len(ok["events"]) == 1

    monkeypatch.setattr(
        graph_documents.auth_service,
        "current_user",
        lambda request: (_ for _ in ()).throw(HTTPException(401, "Sessao obrigatoria.")),
    )
    with pytest.raises(HTTPException) as exc:
        graph_documents.graph_document_events(_req(), persona_slug="allanvvz", brand_slug=None, limit=10)
    assert exc.value.status_code == 401
