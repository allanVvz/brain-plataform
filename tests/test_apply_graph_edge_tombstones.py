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


def test_plan_tombstones_accepts_same_stable_edge_already_retargeted() -> None:
    bundle = {
        "metadata": {"visual_media_reconciliation": {
            "soft_disabled_edge_count": 1,
            "soft_disabled_edges": [{
                "id": "edge:group-cover:repair-paint",
                "source": "group:repair-paint",
                "target": "asset:process",
                "relation_type": "category_has_asset",
                "removal_reason": "replace_representative_cover",
            }],
        }},
        "edges": [{
            "id": "edge:group-cover:repair-paint",
            "source": "group:repair-paint",
            "target": "asset:repair-paint-representative-v1",
            "relation_type": "category_has_asset",
        }],
    }
    nodes = [
        {"id": "group-row", "metadata": {"graph_json_node_id": "group:repair-paint"}},
        {"id": "old-asset-row", "metadata": {"graph_json_node_id": "asset:process"}},
        {"id": "new-asset-row", "metadata": {"graph_json_node_id": "asset:repair-paint-representative-v1"}},
    ]
    replacement = {
        "id": "edge-row", "source_node_id": "group-row", "target_node_id": "new-asset-row",
        "relation_type": "category_has_asset",
        "metadata": {"active": True, "graph_json_edge_id": "edge:group-cover:repair-paint"},
    }

    planned = plan_tombstones(bundle, nodes, [replacement])

    assert planned[0]["status"] == "already_replaced"
