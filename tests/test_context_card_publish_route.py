from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import knowledge
from schemas.graph_json_v2 import GraphJson


def _request():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "editor-1", "role": "admin"}))


def _graph() -> GraphJson:
    return GraphJson.model_validate({
        "schema_version": "2.1",
        "graph_id": "aurora-context-card",
        "tenant": "test",
        "persona_slug": "aurora",
        "status": "published",
        "nodes": [
            {
                "id": "persona", "node_type": "persona", "slug": "aurora",
                "title": "Aurora", "lifecycle": {"status": "approved"},
                "provenance": {"source": "fixture"}, "spec": {"summary": "Aurora"},
            },
            {
                "id": "faq", "node_type": "faq", "slug": "faq-preco",
                "title": "Quanto custa?", "lifecycle": {"status": "approved", "revision": 3},
                "provenance": {"source": "fixture"},
                "spec": {"question": "Quanto custa?", "answer": "R$ 180"},
            },
        ],
        "edges": [
            {"id": "contains-faq", "source": "persona", "target": "faq", "relation_type": "contains"},
        ],
    })


def _install_auth(monkeypatch):
    monkeypatch.setattr(knowledge.supabase_client, "get_persona", lambda slug: {"id": "p1", "slug": slug})
    monkeypatch.setattr(knowledge.auth_service, "current_user", lambda request: {"id": "editor-1", "role": "admin"})
    monkeypatch.setattr(knowledge.auth_service, "is_admin", lambda user: True)
    monkeypatch.setattr(knowledge.context_cards_service, "emit_metric", lambda *args, **kwargs: None)


def test_save_and_publish_applies_update_then_approval_and_waits_for_activation(monkeypatch):
    _install_auth(monkeypatch)
    graph = _graph()
    monkeypatch.setattr(knowledge.graph_json_v2_store, "load_current", lambda slug: (7, graph))
    captured = {}

    def commit(**kwargs):
        captured.update(kwargs)
        updated = next(node for node in kwargs["graph"].nodes if node.id == "faq")
        assert updated.lifecycle.revision == 4
        assert updated.lifecycle.status == "approved"
        assert updated.lifecycle.approved_by == "editor-1"
        assert updated.spec["answer"] == "Agora R$ 220"
        return {"ok": True, "version": 8, "status": "published"}

    monkeypatch.setattr(knowledge.graph_document_publisher, "commit", commit)
    monkeypatch.setattr(knowledge.context_cards_service, "current_graph", lambda slug: (8, "checksum-8", graph))
    monkeypatch.setattr(knowledge.context_cards_service, "cards_for_ids", lambda **kwargs: [])

    result = knowledge.publish_context_card(
        "faq",
        knowledge.PublishContextCardBody(
            persona_slug="aurora", content="Agora R$ 220",
            expected_version=7, reason="Preço aprovado pela operação",
        ),
        _request(),
    )
    assert result["status"] == "published"
    assert captured["expected_version"] == 7
    assert captured["reason"] == "Preço aprovado pela operação"


def test_save_and_publish_returns_409_on_optimistic_version_conflict(monkeypatch):
    _install_auth(monkeypatch)
    graph = _graph()
    monkeypatch.setattr(knowledge.graph_json_v2_store, "load_current", lambda slug: (8, graph))
    monkeypatch.setattr(
        knowledge.graph_document_publisher,
        "commit",
        lambda **kwargs: (_ for _ in ()).throw(
            knowledge.graph_document_publisher.VersionConflict(expected=7, current=8)
        ),
    )
    with pytest.raises(HTTPException) as exc:
        knowledge.publish_context_card(
            "faq",
            knowledge.PublishContextCardBody(
                persona_slug="aurora", content="Novo preço",
                expected_version=7, reason="Revisão operacional",
            ),
            _request(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "GRAPH_VERSION_CONFLICT"


def test_viewer_cannot_publish_context_card(monkeypatch):
    monkeypatch.setattr(knowledge.supabase_client, "get_persona", lambda slug: {"id": "p1", "slug": slug})
    monkeypatch.setattr(knowledge.auth_service, "current_user", lambda request: {"id": "viewer", "role": "viewer"})
    monkeypatch.setattr(knowledge.auth_service, "is_admin", lambda user: False)
    monkeypatch.setattr(knowledge.auth_service, "allowed_access", lambda request: [])
    with pytest.raises(HTTPException) as exc:
        knowledge.publish_context_card(
            "faq",
            knowledge.PublishContextCardBody(
                persona_slug="aurora", content="Não autorizado",
                expected_version=7, reason="Tentativa viewer",
            ),
            _request(),
        )
    assert exc.value.status_code == 403
