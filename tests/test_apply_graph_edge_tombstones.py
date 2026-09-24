from api.scripts.apply_graph_edge_tombstones import plan_tombstones


def test_plan_tombstones_matches_exact_persona_edge_and_is_idempotent() -> None:
    bundle = {
        "metadata": {"visual_media_reconciliation": {
            "soft_disabled_edge_count": 1,
            "soft_disabled_edges": [{
                "id": "edge:old-image",
                "source": "product:ppf",
                "target": "asset:portrait",
                "relation_type": "uses_asset",
                "removal_reason": "false_direct_evidence",
            }],
        }},
    }
    nodes = [
        {"id": "product-row", "metadata": {"graph_json_node_id": "product:ppf"}},
        {"id": "asset-row", "metadata": {"graph_json_node_id": "asset:portrait"}},
    ]
    edge = {
        "id": "edge-row", "source_node_id": "product-row", "target_node_id": "asset-row",
        "relation_type": "uses_asset", "metadata": {"active": True, "graph_json_edge_id": "edge:old-image"},
    }

    planned = plan_tombstones(bundle, nodes, [edge])
    assert planned[0]["status"] == "active"

    edge["metadata"]["active"] = False
    planned = plan_tombstones(bundle, nodes, [edge])
    assert planned[0]["status"] == "already_inactive"
