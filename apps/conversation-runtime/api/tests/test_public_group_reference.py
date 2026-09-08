from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_agent_runtime_v3


def _document():
    nodes = [
        {"id": "retail", "node_type": "audience", "slug": "retail", "title": "Retail", "data": {}},
        {"id": "campaign", "node_type": "campaign", "slug": "vitrine", "title": "Vitrine", "data": {"public_site": {"reference_prefix": "vitrine", "branch_node_id": "retail"}}},
        {"id": "group", "node_type": "product_group", "slug": "vestidos", "title": "Vestidos", "data": {}},
        {"id": "product", "node_type": "product", "slug": "dress", "title": "Dress", "data": {}},
        {"id": "offer", "node_type": "offer", "slug": "dress-retail", "title": "Offer", "data": {}},
        {"id": "asset", "node_type": "asset", "slug": "dress-photo", "title": "Photo", "status": "validated", "data": {"asset_function": "vitrine", "blob": {"registry_id": "registry", "status": "approved"}}},
    ]
    return {
        "node_by_id": {node["id"]: node for node in nodes},
        "nodes": nodes, "branch_anchors": ["retail"],
        "branch_contracts": {"retail": {"closure_node_ids": [node["id"] for node in nodes]}},
        "coordinates": {"retail": {"path_checksum": "sha256:path"}},
        "edges": [
            {"source": "campaign", "target": "group", "relation_type": "contains"},
            {"source": "group", "target": "product", "relation_type": "contains"},
            {"source": "offer", "target": "product", "relation_type": "about_product"},
            {"source": "product", "target": "asset", "relation_type": "uses_asset"},
        ],
    }


def test_canonical_vitrine_reference_seeds_exact_group_products_offer_and_asset():
    resolved = graph_agent_runtime_v3._public_group_reference(
        _document(), [{"message_id": "msg-1", "role": "user", "content": "Quero ver Vestidos [vitrine:vestidos]"}],
        message_id="msg-1", trace_id=None,
    )
    assert resolved["branch_node_id"] == "retail"
    assert resolved["group_node_id"] == "group"
    assert set(resolved["evidence_node_ids"]) == {"group", "product", "offer", "asset"}


def test_unknown_or_unbound_reference_is_ignored():
    document = _document()
    document["node_by_id"]["campaign"]["data"] = {}
    assert graph_agent_runtime_v3._public_group_reference(
        document, [{"message_id": "msg-1", "role": "user", "content": "[vitrine:vestidos]"}],
        message_id="msg-1", trace_id=None,
    ) is None
