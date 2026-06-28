from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_vzlupas_preflight_default_contract_ok():
    from routes import graph

    result = graph.graph_contract_preflight_vzlupas(graph.GraphPreflightBody())

    assert result["ok"] is True
    assert result["contract"]["name"] == "vzlupas_catalog_to_hierarchical_graph"
    assert isinstance(result["checks"], list) and result["checks"]
    assert result["errors"] == []
    assert result["graph_summary"]["node_count"] > 0
    assert result["graph_summary"]["edge_count"] > 0


def test_vzlupas_preflight_rejects_product_to_embed():
    from routes import graph

    valid_graph, tree_edges = graph._build_vzlupas_contract_graph()
    valid_graph["edges"].append(
        graph._contract_edge("bad-product-embed", "product-vz-clipon-aviator", "embed-vzlupas")
    )

    result = graph.graph_contract_preflight_vzlupas(
        graph.GraphPreflightBody(graph=valid_graph, tree_edge_ids=tree_edges + ["bad-product-embed"])
    )

    assert result["ok"] is False
    assert any("EMBED_SOURCE_NOT_FAQ" in err for err in result["errors"])
