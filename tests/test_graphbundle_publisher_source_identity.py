from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_API = ROOT / "apps" / "control-plane" / "api"
sys.path.insert(0, str(CONTROL_API))

from services import graph_bundle_publisher  # noqa: E402


def test_materialization_replaces_historical_slug_on_an_immutable_projection() -> None:
    """The approved bundle's semantic slug, not an import fallback, reaches runtime."""
    source = (CONTROL_API / "services" / "graph_bundle_publisher.py").read_text(
        encoding="utf-8"
    )
    assert '"slug": node["slug"]' in source


def test_source_scope_prefers_immutable_projection_id_over_historical_slug() -> None:
    projection_id = "39129cc8-9a94-4824-8306-989ffc81eabe"
    normalized = {
        "nodes": [
            {
                "id": "asset:tock-fatal-body-estampado",
                "projection_node_id": projection_id,
                "node_type": "asset",
                "slug": "asset-registry-historical-slug",
            }
        ],
        "edges": [],
    }
    source_rows = [
        {
            "id": projection_id,
            "node_type": "asset",
            "slug": "tock-fatal-body-estampado",
            "status": "validated",
            "metadata": {"graph_json_node_id": "asset:tock-fatal-body-estampado"},
        }
    ]

    graph_bundle_publisher._preflight_source_scope(normalized, source_rows, [])


def test_source_scope_still_rejects_an_unplanned_projection() -> None:
    normalized = {
        "nodes": [
            {
                "id": "persona:target",
                "projection_node_id": "00000000-0000-0000-0000-000000000001",
                "node_type": "persona",
                "slug": "target",
            }
        ],
        "edges": [],
    }
    source_rows = [
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "node_type": "asset",
            "slug": "unexpected",
            "status": "validated",
        }
    ]

    try:
        graph_bundle_publisher._preflight_source_scope(normalized, source_rows, [])
    except graph_bundle_publisher.GraphBundlePublishError as exc:
        assert str(exc) == "source_graph_has_unplanned_nodes:asset:unexpected"
    else:
        raise AssertionError("unplanned projection must remain blocked")


def test_source_scope_compares_edges_by_projection_ids_not_graph_aliases() -> None:
    persona_id = "00000000-0000-0000-0000-000000000001"
    asset_id = "39129cc8-9a94-4824-8306-989ffc81eabe"
    normalized = {
        "nodes": [
            {"id": "persona:target", "projection_node_id": persona_id, "node_type": "persona", "slug": "target"},
            {"id": "asset:canonical", "projection_node_id": asset_id, "node_type": "asset", "slug": "registry-slug"},
        ],
        "edges": [
            {"source": "persona:target", "target": "asset:canonical", "relation_type": "uses_asset"}
        ],
    }
    source_rows = [
        {"id": persona_id, "node_type": "persona", "slug": "target", "status": "validated"},
        {"id": asset_id, "node_type": "asset", "slug": "historical-slug", "status": "validated", "metadata": {"graph_json_node_id": "node:asset:old-alias"}},
    ]
    source_edges = [
        {"source_node_id": persona_id, "target_node_id": asset_id, "relation_type": "uses_asset", "metadata": {"active": True}}
    ]

    graph_bundle_publisher._preflight_source_scope(normalized, source_rows, source_edges)
