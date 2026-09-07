from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from routes import menu


def test_public_menu_stops_before_raw_graph_reads_without_active_v3(monkeypatch):
    monkeypatch.setattr(
        menu, "_resolve_persona",
        lambda _slug: {"id": "persona-1", "slug": "persona", "config": {}},
    )
    monkeypatch.setattr(menu, "_public_graph_context", lambda _slug: None)
    monkeypatch.setattr(
        menu.supabase_client, "get_knowledge_node_by_slug",
        lambda *_args, **_kwargs: pytest.fail("raw graph read happened before active v3"),
    )

    with pytest.raises(HTTPException) as exc:
        menu.build_menu_payload("persona")

    assert exc.value.status_code == 409
    assert exc.value.detail == "active_graph_publication_v3_required"


def test_public_graph_context_rejects_non_active_publication(monkeypatch):
    monkeypatch.setattr(
        menu.supabase_client, "get_persona",
        lambda _slug: {"id": "persona-1", "slug": "persona"},
    )
    monkeypatch.setattr(
        menu.supabase_client, "get_active_graph_publication",
        lambda _persona_id: {"id": "publication-1", "status": "compiled"},
    )
    assert menu._public_graph_context("persona") is None


def test_public_menu_is_reconstructed_from_active_document_only(monkeypatch):
    persona = {"id": "persona-1", "slug": "persona", "name": "Persona", "config": {}}
    nodes = [
        {"id": "gallery", "node_type": "gallery", "slug": "site", "title": "Site", "status": "active", "data": {"action": {"enabled": True, "destination_type": "public_site"}}},
        {"id": "group", "node_type": "product_group", "slug": "novidades", "title": "Novidades", "status": "validated", "data": {}},
        {"id": "product", "node_type": "product", "slug": "draft-only", "title": "Produto do draft", "summary": "Publicado sem escrita crua", "status": "validated", "data": {"price_cents": 1234}},
        {"id": "faq", "node_type": "faq", "slug": "faq-draft-only", "title": "Pergunta?", "status": "validated", "data": {"question": "Pergunta?", "answer": "Resposta.", "source": "source:test"}},
    ]
    edges = [
        {"id": "gp", "source": "group", "target": "product", "relation_type": "contains", "metadata": {"active": True}},
        {"id": "pf", "source": "product", "target": "faq", "relation_type": "contains", "metadata": {"active": True}},
        *[{"id": f"publish-{node_id}", "source": node_id, "target": "gallery", "relation_type": "publishes_to", "metadata": {"active": True}} for node_id in ("group", "product", "faq")],
    ]
    body = {"schema_version": "3.0", "persona": {"id": "persona-1", "slug": "persona"}, "nodes": nodes, "edges": edges}
    checksum = menu._canonical_json_checksum(body)
    publication = {"id": "publication-1", "persona_id": "persona-1", "version": 7, "status": "active", "checksum": checksum, "document_json": {**body, "checksum": checksum}}
    monkeypatch.setattr(menu, "_resolve_persona", lambda _slug: persona)
    monkeypatch.setattr(menu.supabase_client, "get_persona", lambda _slug: persona)
    monkeypatch.setattr(menu.supabase_client, "get_active_graph_publication", lambda _id: publication)
    monkeypatch.setattr(menu.supabase_client, "list_public_site_formats", lambda **_kwargs: [])
    monkeypatch.setattr(menu.public_site, "public_site_payload", lambda *_args, **_kwargs: {})
    for name in ("get_knowledge_node_by_slug", "list_product_collection_nodes", "list_product_nodes", "list_edges_for_nodes"):
        monkeypatch.setattr(menu.supabase_client, name, lambda *_args, _name=name, **_kwargs: pytest.fail(f"raw graph reader called: {_name}"))

    payload = menu.build_menu_payload("persona")

    product = payload["persona"]["collections"][0]["categories"][0]["products"][0]
    assert product["slug"] == "draft-only"
    assert product["faqs"][0]["answer"] == "Resposta."
    assert payload["publication_id"] == "publication-1"
    assert payload["graph_checksum"] == checksum
