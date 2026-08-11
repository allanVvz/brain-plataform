from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services import graph_document_publisher


def _graph() -> GraphJson:
    return GraphJson.model_validate(
        {
            "schema_version": "2.0",
            "graph_id": "publisher-test",
            "tenant": "qa",
            "persona_slug": "acme",
            "nodes": [
                {"id": "persona", "node_type": "persona", "slug": "acme", "label": "Acme"},
                {
                    "id": "brand",
                    "node_type": "brand",
                    "slug": "brand",
                    "label": "Brand",
                    "parent_id": "persona",
                    "data": {"status": "pending_validation"},
                },
            ],
            "edges": [
                {
                    "id": "edge-brand",
                    "source": "persona",
                    "target": "brand",
                    "relation": "belongs_to_persona",
                }
            ],
        }
    )


def test_projection_failure_does_not_publish(monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr(graph_document_publisher, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(graph_document_publisher, "_idempotent_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(graph_document_publisher, "_load_current", lambda *args: None)
    monkeypatch.setattr(
        graph_document_publisher.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )
    monkeypatch.setattr(
        graph_document_publisher.graph_json_v2_store,
        "save_version",
        lambda *args, **kwargs: saved.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        graph_document_publisher.publish(
            graph=_graph(),
            persona_slug="acme",
            brand_slug=None,
            source="test",
        )
    assert saved == []


def test_expected_version_conflict_happens_before_projection(monkeypatch):
    projected: list[bool] = []
    monkeypatch.setattr(graph_document_publisher, "_idempotent_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(graph_document_publisher, "_load_current", lambda *args: (4, _graph()))
    monkeypatch.setattr(
        graph_document_publisher.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: projected.append(True),
    )

    with pytest.raises(graph_document_publisher.VersionConflict) as exc:
        graph_document_publisher.publish(
            graph=_graph(),
            persona_slug="acme",
            brand_slug=None,
            source="test",
            expected_version=3,
        )
    assert exc.value.current == 4
    assert projected == []


def test_idempotency_replay_skips_projection(monkeypatch):
    replay = {
        "ok": True,
        "idempotent_replay": True,
        "version": 7,
        "checksum": "same",
        "projections": {"nodes_imported": 2},
    }
    monkeypatch.setattr(graph_document_publisher, "_idempotent_result", lambda *args, **kwargs: replay)
    result = graph_document_publisher.publish(
        graph=_graph(),
        persona_slug="acme",
        brand_slug=None,
        source="test",
        idempotency_key="same-request",
    )
    assert result == replay


def test_commit_activation_replay_skips_projection(monkeypatch):
    graph = _graph()
    graph.schema_version = "2.1"
    replay = {
        "ok": True,
        "idempotent_replay": True,
        "version": 7,
        "checksum": "same",
        "projections": {"nodes_imported": 2},
    }
    monkeypatch.setattr(
        graph_document_publisher, "_idempotent_result", lambda *args, **kwargs: replay
    )
    monkeypatch.setattr(
        graph_document_publisher.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not project")),
    )

    result = graph_document_publisher.commit(
        graph=graph,
        persona_slug="acme",
        brand_slug=None,
        source="test",
        reason="test replay",
        published_by="test",
        expected_version=7,
        idempotency_key="same-request",
    )

    assert result == replay


def test_activation_event_is_a_valid_idempotency_replay(monkeypatch):
    requested_event_types: list[str] = []

    def _events(**kwargs):
        requested_event_types.extend(kwargs["event_types"])
        return [{
            "id": "activation-1",
            "event_type": "graph_version_activated",
            "entity_id": "acme:default:v7",
            "payload": {
                "persona_slug": "acme",
                "brand_slug": None,
                "version": 7,
                "checksum": "same",
                "idempotency_key": "same-request",
                "projections": {"nodes_imported": 2},
            },
        }]

    monkeypatch.setattr(
        graph_document_publisher.supabase_client, "list_system_events", _events
    )

    replay = graph_document_publisher._idempotent_result(
        "acme", None, "same-request"
    )

    assert "graph_version_activated" in requested_event_types
    assert replay and replay["idempotent_replay"] is True
    assert replay["version"] == 7
