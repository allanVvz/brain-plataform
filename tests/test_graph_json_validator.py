from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services.graph_json_v2_validator import validate_graph_json


def _valid_graph() -> GraphJson:
    return GraphJson.model_validate(
        {
            "schema_version": "2.0",
            "graph_id": "g1",
            "tenant": "qa",
            "persona_slug": "allanvvz",
            "brand_slug": "vz-lupas",
            "status": "draft",
            "nodes": [
                {"id": "n1", "node_type": "persona", "slug": "allanvvz", "label": "Allan"},
                {"id": "n2", "node_type": "brand", "slug": "vz-lupas", "label": "VZ", "parent_id": "n1"},
                {"id": "n3", "node_type": "briefing", "slug": "brief", "label": "Brief", "parent_id": "n2"},
                {"id": "n4", "node_type": "campaign", "slug": "camp", "label": "Camp", "parent_id": "n3"},
                {"id": "n5", "node_type": "audience", "slug": "aud", "label": "Aud", "parent_id": "n4"},
                {"id": "n6", "node_type": "product_group", "slug": "grp", "label": "Group", "parent_id": "n5"},
                {"id": "n7", "node_type": "product", "slug": "prod", "label": "Prod", "parent_id": "n6"},
                {"id": "n8", "node_type": "faq", "slug": "faq", "label": "FAQ", "parent_id": "n7"},
                {"id": "n9", "node_type": "embedded", "slug": "emb", "label": "Emb", "parent_id": "n8"},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "main"},
                {"id": "e2", "source": "n2", "target": "n3", "relation": "main"},
                {"id": "e3", "source": "n3", "target": "n4", "relation": "main"},
                {"id": "e4", "source": "n4", "target": "n5", "relation": "main"},
                {"id": "e5", "source": "n5", "target": "n6", "relation": "main"},
                {"id": "e6", "source": "n6", "target": "n7", "relation": "main"},
                {"id": "e7", "source": "n7", "target": "n8", "relation": "main"},
                {"id": "e8", "source": "n8", "target": "n9", "relation": "main"},
            ],
        }
    )


def test_validate_graph_json_accepts_valid_graph():
    graph = _valid_graph()
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is True
    assert errors == []


def test_validate_graph_json_rejects_schema_version_mismatch():
    graph = _valid_graph()
    graph.schema_version = "1.0"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("schema_version must be 2.0" in err for err in errors)


def test_validate_graph_json_rejects_persona_ownership_mismatch():
    graph = _valid_graph()
    graph.persona_slug = "other-persona"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("persona ownership mismatch" in err for err in errors)


def test_validate_graph_json_rejects_canonical_chain_break():
    graph = _valid_graph()
    # FAQ must hang from product; attach to audience to violate canonical chain.
    for node in graph.nodes:
        if node.id == "n8":
            node.parent_id = "n5"
            break
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("expected one of" in err for err in errors)


def test_validate_graph_json_rejects_orphan_node():
    graph = _valid_graph()
    for node in graph.nodes:
        if node.id == "n7":
            node.parent_id = None
            break
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("orphan node" in err for err in errors)


def test_validate_graph_json_rejects_missing_edge_integrity():
    graph = _valid_graph()
    graph.edges[0].target = "missing-node"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("target missing-node missing" in err for err in errors)


def test_validate_graph_json_rejects_faq_before_embed_violation():
    graph = _valid_graph()
    # embedded must hang from faq, not directly from product.
    for node in graph.nodes:
        if node.id == "n9":
            node.parent_id = "n7"
            break
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("expected one of" in err for err in errors)
