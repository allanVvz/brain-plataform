"""Tock Fatal publishes through the GraphBundle pipeline (graph_publications),
not the legacy graph_document event trail. context_cards.current_graph() must
fall back to the active graph_publications row instead of 404ing.
"""
from __future__ import annotations

import pytest

from schemas.graph_json_v2 import GraphJson, Node
from services import context_cards, graph_conversation_contract, graph_json_v2_store


def _compiled_document() -> dict:
    """Shape produced by graph_compiler_v3.compile_graph() and stored as
    graph_publications.document_json."""
    return {
        "schema_version": "3.0",
        "persona": {"id": "persona-uuid-1", "slug": "tock-fatal"},
        "nodes": [
            {
                "id": "persona:tock-fatal",
                "projection_node_id": "uuid-persona",
                "node_type": "persona",
                "slug": "tock-fatal",
                "title": "Tock Fatal",
                "summary": "Persona de teste para publicacao via GraphBundle.",
                "tags": ["persona"],
                "status": "validated",
                "data": {"source": "test", "status": "validated"},
            },
            {
                "id": "faq:preco-blusa",
                "projection_node_id": "uuid-faq",
                "node_type": "faq",
                "slug": "preco-blusa",
                "title": "Preco da blusa",
                "summary": "R$ 39,90",
                "tags": ["faq"],
                "status": "approved",
                "data": {
                    "question": "Qual o preco da blusa?",
                    "answer": "R$ 39,90",
                    "status": "approved",
                    "source": "test",
                    "metadata": {"role": "knowledge_faq"},
                },
            },
        ],
        "edges": [
            {
                "id": "edge:contains:1",
                "source": "persona:tock-fatal",
                "target": "faq:preco-blusa",
                "relation_type": "contains",
                "weight": 0.9,
                "metadata": {},
                "primary": True,
            },
        ],
        "parents": {"faq:preco-blusa": "persona:tock-fatal"},
        "checksum": "sha256:" + "c" * 64,
    }


def test_persona_without_legacy_event_resolves_via_graph_publications(monkeypatch):
    document = _compiled_document()
    # No graph_document event trail at all: the legacy store must genuinely
    # find nothing so current_graph() is forced onto the fallback path.
    monkeypatch.setattr(
        graph_json_v2_store.supabase_client, "list_system_events", lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        graph_json_v2_store.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-uuid-1", "slug": "tock-fatal"},
    )
    monkeypatch.setattr(
        graph_json_v2_store.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: {
            "id": "publication-1",
            "persona_id": "persona-uuid-1",
            "version": 31,
            "checksum": "sha256:" + "b" * 64,
            "status": "active",
            "document_json": document,
        },
    )

    version, checksum, graph = context_cards.current_graph("tock-fatal")

    assert version == 31
    assert checksum == "sha256:" + "b" * 64
    assert graph.schema_version == "2.0"
    assert {node.id for node in graph.nodes} == {"persona:tock-fatal", "faq:preco-blusa"}

    faq = next(node for node in graph.nodes if node.node_type == "faq")
    assert faq.lifecycle.status == "approved"
    assert faq.parent_id == "persona:tock-fatal"

    rendered = context_cards._rendered(faq)
    assert "Qual o preco da blusa?" in rendered
    assert "R$ 39,90" in rendered

    coordinate = graph_conversation_contract.coordinate_for_node(
        graph, faq.id, graph_version=version,
    )
    assert coordinate["path_node_ids"] == ["persona:tock-fatal", "faq:preco-blusa"]

    cards = context_cards.resolve_cards(
        graph=graph, graph_version=version, graph_checksum=checksum, query="preco da blusa",
    )
    assert any(card.id == faq.id for card in cards)


def test_persona_with_legacy_event_ignores_graph_publications(monkeypatch):
    legacy_graph = GraphJson(
        graph_id="aurora-main",
        tenant="production",
        persona_slug="aurora",
        status="published",
        nodes=[
            Node(
                id="persona:aurora",
                node_type="persona",
                slug="aurora",
                label="Aurora",
                data={"status": "validated", "source": "test"},
            ),
        ],
    )
    monkeypatch.setattr(
        context_cards.graph_json_v2_store, "load_current", lambda _slug: (5, legacy_graph),
    )
    monkeypatch.setattr(
        context_cards.graph_json_v2_store,
        "latest_event",
        lambda _slug: {"payload": {"checksum": "sha256:" + "a" * 64}},
    )
    monkeypatch.setattr(
        context_cards.graph_json_v2_store,
        "load_active_publication",
        lambda _slug: (_ for _ in ()).throw(
            AssertionError("must not query graph_publications when a legacy event exists")
        ),
    )

    version, checksum, graph = context_cards.current_graph("aurora")

    assert version == 5
    assert checksum == "sha256:" + "a" * 64
    assert graph is legacy_graph


def test_missing_both_sources_still_raises_lookup_error(monkeypatch):
    monkeypatch.setattr(context_cards.graph_json_v2_store, "load_current", lambda _slug: None)
    monkeypatch.setattr(
        context_cards.graph_json_v2_store, "load_active_publication", lambda _slug: None,
    )

    with pytest.raises(LookupError):
        context_cards.current_graph("nobody")
