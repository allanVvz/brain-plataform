# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.graphHierarchyAssertions import run_all_validators

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "vzlupas-products-9.json"


def _node(node_id: str, node_type: str, approved: bool = False) -> dict:
    return {"id": node_id, "type": node_type, "approved": approved}


def _edge(edge_id: str, src: str, tgt: str, edge_type: str = "main", active: bool = True) -> dict:
    return {"id": edge_id, "source": src, "target": tgt, "edge_type": edge_type, "active": active}


def _build_valid_graph() -> tuple[dict, list[str]]:
    products = json.loads(FIXTURE.read_text(encoding="utf-8"))

    nodes = [
        _node("persona-vzlupas", "persona"),
        _node("brand-vzlupas", "brand"),
        _node("briefing-vzlupas", "briefing"),
        _node("campaign-vzlupas", "campaign"),
        _node("audience-vzlupas", "audience"),
        _node("pg-clipon", "product_group"),
        _node("pg-grau", "product_group"),
        _node("pg-sol", "product_group"),
        _node("embed-vzlupas", "embed"),
    ]
    edges = [
        _edge("e1", "persona-vzlupas", "brand-vzlupas"),
        _edge("e2", "brand-vzlupas", "briefing-vzlupas"),
        _edge("e3", "briefing-vzlupas", "campaign-vzlupas"),
        _edge("e4", "campaign-vzlupas", "audience-vzlupas"),
        _edge("e5", "audience-vzlupas", "pg-clipon"),
        _edge("e6", "audience-vzlupas", "pg-grau"),
        _edge("e7", "audience-vzlupas", "pg-sol"),
    ]

    group_for_idx = {0: "pg-clipon", 1: "pg-clipon", 2: "pg-clipon", 3: "pg-grau", 4: "pg-grau", 5: "pg-grau", 6: "pg-sol", 7: "pg-sol", 8: "pg-sol"}
    tree_edge_ids = [e["id"] for e in edges]

    for i, prod in enumerate(products):
        p_id = f"product-{prod['slug']}"
        faq1 = f"faq-{prod['slug']}-1"
        faq2 = f"faq-{prod['slug']}-2"
        nodes.extend([
            _node(p_id, "product"),
            _node(faq1, "faq", approved=True),
            _node(faq2, "faq", approved=True),
        ])
        edges.extend([
            _edge(f"ep-{i}", group_for_idx[i], p_id),
            _edge(f"ef1-{i}", p_id, faq1),
            _edge(f"ef2-{i}", p_id, faq2),
            _edge(f"ee1-{i}", faq1, "embed-vzlupas"),
            _edge(f"ee2-{i}", faq2, "embed-vzlupas", edge_type="reference"),
        ])
        tree_edge_ids.extend([f"ep-{i}", f"ef1-{i}", f"ef2-{i}", f"ee1-{i}"])

    # Graph view can include references.
    edges.append(_edge("ref-brand-campaign", "brand-vzlupas", "campaign-vzlupas", edge_type="reference"))
    return ({"nodes": nodes, "edges": edges}, tree_edge_ids)


def test_vzlupas_catalog_to_hierarchical_graph_e2e() -> None:
    graph, tree = _build_valid_graph()
    ok, errors = run_all_validators(graph, tree)
    assert ok, errors


def test_valid_minimal_graph() -> None:
    graph = {
        "nodes": [_node("p", "persona"), _node("b", "brand")],
        "edges": [_edge("e", "p", "b")],
    }
    ok, errors = run_all_validators(graph, ["e"])
    assert ok, errors


def test_valid_campaign_graph() -> None:
    graph = {
        "nodes": [_node("p", "persona"), _node("b", "brand"), _node("br", "briefing"), _node("c", "campaign")],
        "edges": [_edge("e1", "p", "b"), _edge("e2", "b", "br"), _edge("e3", "br", "c")],
    }
    ok, errors = run_all_validators(graph, ["e1", "e2", "e3"])
    assert ok, errors


def test_valid_product_faq_embed_graph() -> None:
    graph = {
        "nodes": [_node("p", "persona"), _node("b", "brand"), _node("br", "briefing"), _node("c", "campaign"), _node("a", "audience"), _node("pg", "product_group"), _node("pr", "product"), _node("f1", "faq", True), _node("f2", "faq", True), _node("em", "embed")],
        "edges": [_edge("e1", "p", "b"), _edge("e2", "b", "br"), _edge("e3", "br", "c"), _edge("e4", "c", "a"), _edge("e5", "a", "pg"), _edge("e6", "pg", "pr"), _edge("e7", "pr", "f1"), _edge("e8", "pr", "f2"), _edge("e9", "f1", "em")],
    }
    ok, errors = run_all_validators(graph, ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9"])
    assert ok, errors


def test_valid_catalog_product_import_graph() -> None:
    graph, tree = _build_valid_graph()
    ok, errors = run_all_validators(graph, tree)
    assert ok, errors


def test_invalid_product_direct_embed_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["edges"].append(_edge("bad", "product-vz-clipon-aviator", "embed-vzlupas"))
    ok, _ = run_all_validators(graph, tree + ["bad"])
    assert not ok


def test_invalid_unapproved_faq_embed_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["nodes"].append(_node("faq-unapproved", "faq", approved=False))
    graph["edges"].append(_edge("bad", "product-vz-sol-redondo", "faq-unapproved"))
    graph["edges"].append(_edge("bad2", "faq-unapproved", "embed-vzlupas"))
    ok, _ = run_all_validators(graph, tree + ["bad", "bad2"])
    assert not ok


def test_invalid_backward_edge_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["edges"].append(_edge("bad", "audience-vzlupas", "campaign-vzlupas"))
    ok, _ = run_all_validators(graph, tree + ["bad"])
    assert not ok


def test_invalid_cycle_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["edges"].append(_edge("bad", "product-vz-clipon-aviator", "pg-clipon"))
    ok, _ = run_all_validators(graph, tree + ["bad"])
    assert not ok


def test_invalid_gallery_embed_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["nodes"].append(_node("gallery-1", "gallery"))
    graph["edges"].append(_edge("bad", "gallery-1", "embed-vzlupas"))
    ok, _ = run_all_validators(graph, tree + ["bad"])
    assert not ok


def test_invalid_catalog_direct_embed_graph() -> None:
    graph, tree = _build_valid_graph()
    graph["nodes"].append(_node("asset-1", "asset"))
    graph["edges"].append(_edge("bad", "asset-1", "embed-vzlupas"))
    ok, _ = run_all_validators(graph, tree + ["bad"])
    assert not ok


def test_screenshot_like_current_graph_is_represented_and_invalid() -> None:
    graph, tree = _build_valid_graph()
    # Simulates the recurring broken screenshot: product->embed and reference edge leaked in tree.
    graph["edges"].append(_edge("bad1", "product-vz-grau-metal", "embed-vzlupas"))
    graph["edges"].append(_edge("ref1", "campaign-vzlupas", "embed-vzlupas", edge_type="reference"))
    ok, _ = run_all_validators(graph, tree + ["bad1", "ref1"])
    assert not ok


def test_corrected_screenshot_like_graph_is_represented_and_valid() -> None:
    graph, tree = _build_valid_graph()
    ok, errors = run_all_validators(graph, tree)
    assert ok, errors
