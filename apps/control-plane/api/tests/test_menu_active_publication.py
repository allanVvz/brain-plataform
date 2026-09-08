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


def test_collection_scope_isolates_brand_and_resolves_only_approved_registry_asset(monkeypatch):
    persona = {
        "id": "persona-1", "slug": "persona", "name": "Persona",
        "config": {"public_site": {"default_collection_slug": "vitrine"}},
    }
    nodes = [
        {"id": "gallery", "node_type": "gallery", "slug": "site", "title": "Site", "status": "active", "data": {"action": {"enabled": True, "destination_type": "public_site"}}},
        {"id": "retail", "node_type": "brand", "slug": "retail", "title": "Retail", "status": "validated", "data": {}},
        {"id": "wholesale", "node_type": "brand", "slug": "wholesale", "title": "Wholesale", "status": "validated", "data": {}},
        {"id": "campaign", "node_type": "campaign", "slug": "vitrine", "title": "Vitrine", "status": "validated", "data": {"brand_node_id": "retail"}},
        {"id": "group", "node_type": "product_group", "slug": "vestidos", "title": "Vestidos", "status": "validated", "data": {}},
        {"id": "product", "node_type": "product", "slug": "dress", "title": "Dress", "status": "validated", "data": {}},
        {"id": "retail-offer", "node_type": "offer", "slug": "dress-retail", "title": "Retail offer", "status": "validated", "data": {"price_cents": 1000}},
        {"id": "wholesale-offer", "node_type": "offer", "slug": "dress-wholesale", "title": "Wholesale offer", "status": "validated", "data": {"price_cents": 700}},
        {"id": "product-asset", "node_type": "asset", "slug": "product-photo", "title": "Product photo", "status": "validated", "data": {"asset_function": "vitrine", "blob": {"registry_id": "asset-product"}}},
        {"id": "group-asset", "node_type": "asset", "slug": "group-photo", "title": "Group photo", "status": "validated", "data": {"asset_function": "vitrine", "blob": {"registry_id": "asset-group"}}},
    ]
    links = [
        ("campaign", "retail"), ("campaign", "group"), ("group", "product"),
        ("product", "retail-offer"), ("product", "wholesale-offer"),
        ("retail", "retail-offer"), ("wholesale", "wholesale-offer"),
        ("product", "product-asset"), ("group", "group-asset"),
    ]
    edges = [
        {"id": f"edge-{index}", "source": source, "target": target, "relation_type": "contains", "metadata": {"active": True}}
        for index, (source, target) in enumerate(links)
    ] + [
        {"id": f"publish-{node['id']}", "source": node["id"], "target": "gallery", "relation_type": "publishes_to", "metadata": {"active": True}}
        for node in nodes if node["id"] != "gallery"
    ]
    body = {"schema_version": "3.0", "persona": {"id": "persona-1", "slug": "persona"}, "nodes": nodes, "edges": edges}
    checksum = menu._canonical_json_checksum(body)
    publication = {"id": "pub", "version": 4, "status": "active", "checksum": checksum, "document_json": {**body, "checksum": checksum}}
    assets = {
        "asset-product": {"id": "asset-product", "persona_id": "persona-1", "status": "approved", "storage_bucket": "assets", "storage_path": "product.jpg"},
        "asset-group": {"id": "asset-group", "persona_id": "persona-1", "status": "approved", "storage_bucket": "assets", "storage_path": "group.jpg"},
    }
    monkeypatch.setattr(menu, "_resolve_persona", lambda _slug: persona)
    monkeypatch.setattr(menu.supabase_client, "get_persona", lambda _slug: persona)
    monkeypatch.setattr(menu.supabase_client, "get_active_graph_publication", lambda _id: publication)
    monkeypatch.setattr(menu.supabase_client, "get_asset", lambda asset_id: assets.get(asset_id))
    monkeypatch.setattr(menu.supabase_client, "asset_display_url", lambda row: f"https://cdn/{row['storage_path']}")
    monkeypatch.setattr(menu.supabase_client, "list_public_site_formats", lambda **_kwargs: [])
    monkeypatch.setattr(menu.public_site, "public_site_payload", lambda *_args, **_kwargs: {})

    payload = menu.build_menu_payload("persona", collection_slug="vitrine")
    collection = payload["persona"]["collections"][0]
    product = collection["categories"][0]["products"][0]
    assert payload["persona"]["brand"]["slug"] == "retail"
    assert product["price_cents"] == 1000
    assert product["offer_id"] == "retail-offer"
    assert collection["categories"][0]["cover"] == "https://cdn/group.jpg"
    assert collection["categories"][0]["cta_message"].endswith("[vitrine:vestidos]")


def test_graph_url_without_registry_object_is_omitted(monkeypatch):
    monkeypatch.setattr(menu.supabase_client, "get_asset", lambda _asset_id: None)
    payload = menu._active_asset_payload(
        {"id": "asset", "data": {"url": "https://stale.invalid/x.jpg", "blob": {"registry_id": "missing"}}},
        persona_id="persona-1", registry_cache={},
    )
    assert payload["url"] == ""


def test_published_validated_asset_accepts_ready_registry_row(monkeypatch):
    monkeypatch.setattr(menu.supabase_client, "get_asset", lambda _asset_id: {
        "id": "asset", "persona_id": "persona-1", "status": "ready",
        "storage_bucket": "assets-raw", "storage_path": "persona/product.jpg",
    })
    monkeypatch.setattr(menu.supabase_client, "asset_display_url", lambda _row: "https://cdn/product.jpg")
    payload = menu._active_asset_payload(
        {"id": "node", "status": "validated", "data": {"blob": {"registry_id": "asset"}}},
        persona_id="persona-1", registry_cache={},
    )
    assert payload["url"] == "https://cdn/product.jpg"


def test_group_cover_falls_back_only_when_one_product_has_media(monkeypatch):
    products = [
        {"id": "p1", "assets": [{"url": "https://cdn/p1.jpg"}]},
        {"id": "p2", "assets": []},
    ]
    assert menu._select_group_cover([], products)["url"] == "https://cdn/p1.jpg"
    products[1]["assets"] = [{"url": "https://cdn/p2.jpg"}]
    assert menu._select_group_cover([], products) is None
    assert menu._select_group_cover([{"url": "https://cdn/group.jpg"}], products)["url"] == "https://cdn/group.jpg"
