"""Pure graph-contract preflight used by the runtime QA surface."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _contract_node(node_id: str, node_type: str, approved: bool = False) -> dict:
    return {"id": node_id, "type": node_type, "approved": approved}


def _contract_edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str = "main",
    active: bool = True,
) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "edge_type": edge_type,
        "active": active,
    }


def _build_vzlupas_contract_graph() -> tuple[dict, list[str]]:
    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "vzlupas-products-9.json"
    products = json.loads(fixture.read_text(encoding="utf-8"))
    nodes = [
        _contract_node("persona-vzlupas", "persona"),
        _contract_node("brand-vzlupas", "brand"),
        _contract_node("briefing-vzlupas", "briefing"),
        _contract_node("campaign-vzlupas", "campaign"),
        _contract_node("audience-vzlupas", "audience"),
        _contract_node("pg-clipon", "product_group"),
        _contract_node("pg-grau", "product_group"),
        _contract_node("pg-sol", "product_group"),
        _contract_node("embed-vzlupas", "embed"),
    ]
    edges = [
        _contract_edge("e1", "persona-vzlupas", "brand-vzlupas"),
        _contract_edge("e2", "brand-vzlupas", "briefing-vzlupas"),
        _contract_edge("e3", "briefing-vzlupas", "campaign-vzlupas"),
        _contract_edge("e4", "campaign-vzlupas", "audience-vzlupas"),
        _contract_edge("e5", "audience-vzlupas", "pg-clipon"),
        _contract_edge("e6", "audience-vzlupas", "pg-grau"),
        _contract_edge("e7", "audience-vzlupas", "pg-sol"),
    ]
    group_for_idx = {
        0: "pg-clipon", 1: "pg-clipon", 2: "pg-clipon",
        3: "pg-grau", 4: "pg-grau", 5: "pg-grau",
        6: "pg-sol", 7: "pg-sol", 8: "pg-sol",
    }
    tree_edge_ids = [edge["id"] for edge in edges]
    for index, product in enumerate(products):
        product_id = f"product-{product['slug']}"
        faq_one = f"faq-{product['slug']}-1"
        faq_two = f"faq-{product['slug']}-2"
        nodes.extend([
            _contract_node(product_id, "product"),
            _contract_node(faq_one, "faq", approved=True),
            _contract_node(faq_two, "faq", approved=True),
        ])
        edges.extend([
            _contract_edge(f"ep-{index}", group_for_idx[index], product_id),
            _contract_edge(f"ef1-{index}", product_id, faq_one),
            _contract_edge(f"ef2-{index}", product_id, faq_two),
            _contract_edge(f"ee1-{index}", faq_one, "embed-vzlupas"),
            _contract_edge(f"ee2-{index}", faq_two, "embed-vzlupas", edge_type="reference"),
        ])
        tree_edge_ids.extend([
            f"ep-{index}", f"ef1-{index}", f"ef2-{index}", f"ee1-{index}",
        ])
    edges.append(
        _contract_edge(
            "ref-brand-campaign",
            "brand-vzlupas",
            "campaign-vzlupas",
            edge_type="reference",
        )
    )
    return {"nodes": nodes, "edges": edges}, tree_edge_ids


def _validate(graph: dict, tree_edge_ids: list[str]) -> tuple[bool, list[dict], list[str]]:
    nodes = {node.get("id"): node for node in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    main_edges = [edge for edge in edges if edge.get("edge_type", "main") == "main"]
    active_edges = [edge for edge in edges if edge.get("active", True)]
    level = {
        "persona": 0, "brand": 1, "briefing": 2, "campaign": 3,
        "audience": 4, "product_group": 5, "product": 6, "offer": 7,
        "copy": 8, "faq": 9, "embed": 10,
    }
    main_next = {
        "persona": {"brand"}, "brand": {"briefing"}, "briefing": {"campaign"},
        "campaign": {"audience"}, "audience": {"product_group"},
        "product_group": {"product"}, "product": {"offer", "faq", "copy"},
        "offer": {"copy", "faq"}, "copy": {"faq"}, "faq": {"embed"},
    }
    checks: list[dict] = []
    errors: list[str] = []

    invalid_main = []
    for edge in main_edges:
        source_type = str((nodes.get(edge.get("source")) or {}).get("type") or "")
        target_type = str((nodes.get(edge.get("target")) or {}).get("type") or "")
        if target_type not in main_next.get(source_type, set()):
            invalid_main.append(f"{source_type}->{target_type}:{edge.get('id')}")
    checks.append({"name": "main_hierarchy", "ok": not invalid_main, "errors": invalid_main})
    errors.extend(invalid_main)

    forbidden = []
    for edge in active_edges:
        source = nodes.get(edge.get("source")) or {}
        target = nodes.get(edge.get("target")) or {}
        source_type = str(source.get("type") or "")
        target_type = str(target.get("type") or "")
        if target_type == "embed" and source_type != "faq":
            forbidden.append(f"EMBED_SOURCE_NOT_FAQ:{edge.get('id')}")
        if source_type == "faq" and target_type == "embed" and not bool(source.get("approved", False)):
            forbidden.append(f"FAQ_NOT_APPROVED_FOR_EMBED:{edge.get('id')}")
    checks.append({"name": "embed_gate", "ok": not forbidden, "errors": forbidden})
    errors.extend(forbidden)

    tree_errors = []
    edge_by_id = {edge.get("id"): edge for edge in edges}
    for edge_id in tree_edge_ids:
        edge = edge_by_id.get(edge_id)
        if not edge:
            tree_errors.append(f"missing_tree_edge:{edge_id}")
        elif edge.get("edge_type", "main") != "main":
            tree_errors.append(f"tree_not_main:{edge_id}")
    checks.append({"name": "tree_main_only", "ok": not tree_errors, "errors": tree_errors})
    errors.extend(tree_errors)

    depth_errors = []
    for edge in main_edges:
        source_type = str((nodes.get(edge.get("source")) or {}).get("type") or "")
        target_type = str((nodes.get(edge.get("target")) or {}).get("type") or "")
        if level.get(target_type, 999) <= level.get(source_type, -1):
            depth_errors.append(f"non_increasing_depth:{edge.get('id')}")
    checks.append({"name": "layout_depth", "ok": not depth_errors, "errors": depth_errors})
    errors.extend(depth_errors)
    return not errors, checks, errors


def run_vzlupas_preflight(graph: dict | None, tree_edge_ids: list[str] | None) -> dict:
    default_graph, default_tree = _build_vzlupas_contract_graph()
    candidate = graph or default_graph
    candidate_tree = tree_edge_ids or default_tree
    ok, checks, errors = _validate(candidate, candidate_tree)
    return {
        "ok": ok,
        "contract": {
            "name": "vzlupas_catalog_to_hierarchical_graph",
            "version": "2026-05-25",
            "rules": [
                "invalid graph edges are rejected before persistence",
                "direct product->embed is impossible",
                "unapproved faq->embed is impossible",
                "tree view includes only main edges",
            ],
        },
        "graph_summary": {
            "node_count": len(candidate.get("nodes", [])),
            "edge_count": len(candidate.get("edges", [])),
            "tree_edge_count": len(candidate_tree),
        },
        "checks": checks,
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
