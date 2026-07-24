from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from services import graph_json_v2_backfill, graph_json_v2_validator  # noqa: E402


def _persona(slug: str = "baita-conveniencia") -> dict:
    return {"id": "p1", "slug": slug, "name": "Baita Conveniência", "active": True}


def test_backfill_normalizes_legacy_tree_and_duplicate_persona(monkeypatch):
    rows = [
        {"id": "legacy-root", "node_type": "persona", "slug": "self", "title": "Persona", "status": "validated"},
        {"id": "brand-1", "node_type": "brand", "slug": "baita", "title": "Baita", "status": "pending_validation"},
        {"id": "group-1", "node_type": "product_group", "slug": "cervejas", "title": "Cervejas", "status": "pending_validation"},
        {"id": "product-1", "node_type": "product", "slug": "ipa", "title": "IPA", "status": "pending_validation"},
        {"id": "gallery-1", "node_type": "gallery", "slug": "gallery-default", "title": "Gallery", "status": "active"},
        {"id": "asset-1", "node_type": "asset", "slug": "ipa-image", "title": "Imagem IPA", "status": "validated", "metadata": {"parent_node_id": "product-1"}},
    ]
    edges = [
        {
            "id": "legacy-persona-group",
            "source_node_id": "legacy-root",
            "target_node_id": "group-1",
            "relation_type": "belongs_to_persona",
            "metadata": {"active": True, "primary_tree": True},
        },
        {
            "id": "legacy-group-product",
            "source_node_id": "group-1",
            "target_node_id": "product-1",
            "relation_type": "category_has_product",
            "metadata": {"active": True, "primary_tree": True},
        },
    ]
    monkeypatch.setattr(graph_json_v2_backfill.supabase_client, "get_persona", lambda slug: _persona(slug))
    monkeypatch.setattr(
        graph_json_v2_backfill.supabase_client,
        "list_all_knowledge_graph",
        lambda persona_id, limit_nodes=5000: (rows, edges),
    )

    graph, report = graph_json_v2_backfill.build_from_derived_graph("baita-conveniencia")

    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid is True, errors
    assert report["valid"] is True
    assert len([node for node in graph.nodes if node.node_type == "persona"]) == 1
    assert next(node for node in graph.nodes if node.node_type == "persona").slug == "baita-conveniencia"
    product = next(node for node in graph.nodes if node.node_type == "product")
    parent = next(node for node in graph.nodes if node.id == product.parent_id)
    assert parent.node_type == "product_group"
    assert any(node.node_type == "audience" for node in graph.nodes)
    asset = next(node for node in graph.nodes if node.node_type == "asset")
    assert next(node for node in graph.nodes if node.id == asset.parent_id).node_type == "product"
    assert any(
        edge.source == asset.id and edge.relation == "gallery_asset" and edge.primary_tree is False
        for edge in graph.edges
    )


def test_backfill_empty_persona_publishes_valid_root(monkeypatch):
    monkeypatch.setattr(graph_json_v2_backfill.supabase_client, "get_persona", lambda slug: _persona(slug))
    monkeypatch.setattr(
        graph_json_v2_backfill.supabase_client,
        "list_all_knowledge_graph",
        lambda persona_id, limit_nodes=5000: ([], []),
    )
    monkeypatch.setattr(graph_json_v2_backfill.graph_json_v2_store, "load_current", lambda slug: None)
    saved: list[tuple] = []
    monkeypatch.setattr(
        graph_json_v2_backfill.graph_json_v2_store,
        "save_version",
        lambda slug, version, graph, **kwargs: saved.append((slug, version, graph, kwargs)) or "abc123",
    )
    monkeypatch.setattr(
        graph_json_v2_backfill.graph_json_importer,
        "import_graph_json",
        lambda **kwargs: {"ok": True, "nodes_imported": 1, "edges_imported": 0},
    )

    result = graph_json_v2_backfill.publish_backfill("tock-fatal")

    assert result["ok"] is True
    assert result["version"] == 1
    assert result["canonical_nodes"] == 1
    assert saved and saved[0][0:2] == ("tock-fatal", 1)
