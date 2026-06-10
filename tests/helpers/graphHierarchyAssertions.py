# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict, deque


LEVEL = {
    "persona": 0,
    "brand": 1,
    "briefing": 2,
    "campaign": 3,
    "audience": 4,
    "product_group": 5,
    "product": 6,
    "offer": 7,
    "copy": 8,
    "faq": 9,
    "embed": 10,
    "gallery": 10,
    "asset": 10,
}

MAIN_NEXT = {
    "persona": {"brand"},
    "brand": {"briefing"},
    "briefing": {"campaign"},
    "campaign": {"audience"},
    "audience": {"product_group"},
    "product_group": {"product"},
    "product": {"offer", "faq", "copy"},
    "offer": {"copy", "faq"},
    "copy": {"faq"},
    "faq": {"embed"},
}

FORBIDDEN = {
    ("product", "embed"),
    ("campaign", "embed"),
    ("copy", "embed"),
    ("asset", "embed"),
    ("gallery", "embed"),
    ("product", "brand"),
}


def _nodes_map(graph: dict) -> dict:
    return {n["id"]: n for n in graph.get("nodes", [])}


def _main_edges(graph: dict) -> list[dict]:
    return [e for e in graph.get("edges", []) if e.get("edge_type", "main") == "main"]


def _active_edges(graph: dict) -> list[dict]:
    return [e for e in graph.get("edges", []) if e.get("active", True)]


def _type(nodes: dict, node_id: str) -> str:
    return str((nodes.get(node_id) or {}).get("type") or "")


def validateMainHierarchy(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    errors = []
    for e in _main_edges(graph):
        st = _type(nodes, e["source"])
        tt = _type(nodes, e["target"])
        if tt not in MAIN_NEXT.get(st, set()):
            errors.append(f"invalid main edge {st}->{tt}: {e['source']}->{e['target']}")
    return (len(errors) == 0, errors)


def validateSingleMainParent(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    parents = defaultdict(set)
    for e in _main_edges(graph):
        parents[e["target"]].add(e["source"])
    errors = []
    for node, srcs in parents.items():
        if len(srcs) > 1 and _type(nodes, node) != "embed":
            errors.append(f"node {node} has {len(srcs)} main parents")
    return (len(errors) == 0, errors)


def validateNoCycles(graph: dict) -> tuple[bool, list[str]]:
    edges = _main_edges(graph)
    out = defaultdict(list)
    indeg = defaultdict(int)
    nodes = {n["id"] for n in graph.get("nodes", [])}
    for e in edges:
        out[e["source"]].append(e["target"])
        indeg[e["target"]] += 1
        nodes.add(e["source"])
        nodes.add(e["target"])
    q = deque([n for n in nodes if indeg[n] == 0])
    seen = 0
    while q:
        n = q.popleft()
        seen += 1
        for nxt in out[n]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if seen != len(nodes):
        return (False, ["cycle detected in main graph"])
    return (True, [])


def validateNoForbiddenEdges(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    errors = []
    for e in _active_edges(graph):
        pair = (_type(nodes, e["source"]), _type(nodes, e["target"]))
        if pair in FORBIDDEN:
            errors.append(f"forbidden edge {pair[0]}->{pair[1]}")
        if pair == ("faq", "product") and e.get("edge_type", "main") == "main":
            errors.append("forbidden main edge faq->product")
        if pair == ("audience", "campaign") and e.get("edge_type", "main") == "main":
            errors.append("forbidden main edge audience->campaign")
        if pair == ("product_group", "audience") and e.get("edge_type", "main") == "main":
            errors.append("forbidden main edge product_group->audience")
        if pair == ("faq", "embed") and not bool((nodes.get(e["source"]) or {}).get("approved", False)):
            errors.append("unapproved faq->embed")
    return (len(errors) == 0, errors)


def validateProductGroupToProductEdges(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    parent_count = defaultdict(int)
    for e in _main_edges(graph):
        if _type(nodes, e["source"]) == "product_group" and _type(nodes, e["target"]) == "product":
            parent_count[e["target"]] += 1
    errors = []
    for n in graph.get("nodes", []):
        if n.get("type") == "product" and parent_count[n["id"]] != 1:
            errors.append(f"product {n['id']} must have exactly one product_group parent")
    return (len(errors) == 0, errors)


def validateProductToFAQEdges(graph: dict, min_faq_per_product: int = 2) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    counts = defaultdict(int)
    for e in _main_edges(graph):
        st = _type(nodes, e["source"])
        tt = _type(nodes, e["target"])
        if st in {"product", "offer", "copy"} and tt == "faq":
            product_id = e["source"]
            if st != "product":
                # Walk one hop up to product when FAQ is under offer/copy.
                for p in _main_edges(graph):
                    if p["target"] == product_id and _type(nodes, p["source"]) == "product":
                        product_id = p["source"]
                        break
            counts[product_id] += 1
    errors = []
    for n in graph.get("nodes", []):
        if n.get("type") == "product" and counts[n["id"]] < min_faq_per_product:
            errors.append(f"product {n['id']} has fewer than {min_faq_per_product} FAQ nodes")
    return (len(errors) == 0, errors)


def validateFAQApprovalBeforeEmbed(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    errors = []
    for e in _active_edges(graph):
        if _type(nodes, e["source"]) == "faq" and _type(nodes, e["target"]) == "embed":
            if not bool((nodes.get(e["source"]) or {}).get("approved", False)):
                errors.append(f"faq {e['source']} is not approved before embed")
    return (len(errors) == 0, errors)


def validateTreeViewUsesOnlyMainEdges(graph: dict, tree_edges: list[str]) -> tuple[bool, list[str]]:
    by_id = {e["id"]: e for e in graph.get("edges", [])}
    errors = []
    for edge_id in tree_edges:
        edge = by_id.get(edge_id)
        if not edge:
            errors.append(f"tree edge {edge_id} not found")
            continue
        if edge.get("edge_type", "main") != "main":
            errors.append(f"tree edge {edge_id} is not main")
    return (len(errors) == 0, errors)


def validateLayoutDepth(graph: dict) -> tuple[bool, list[str]]:
    nodes = _nodes_map(graph)
    errors = []
    for e in _main_edges(graph):
        st = _type(nodes, e["source"])
        tt = _type(nodes, e["target"])
        if LEVEL.get(tt, 999) <= LEVEL.get(st, -1):
            errors.append(f"non-increasing depth {st}->{tt}")
    return (len(errors) == 0, errors)


def run_all_validators(graph: dict, tree_edges: list[str]) -> tuple[bool, list[str]]:
    validators = [
        validateMainHierarchy,
        validateSingleMainParent,
        validateNoCycles,
        validateNoForbiddenEdges,
        validateProductGroupToProductEdges,
        validateProductToFAQEdges,
        validateFAQApprovalBeforeEmbed,
        lambda g: validateTreeViewUsesOnlyMainEdges(g, tree_edges),
        validateLayoutDepth,
    ]
    errs: list[str] = []
    for fn in validators:
        ok, e = fn(graph)
        if not ok:
            errs.extend(e)
    return (len(errs) == 0, errs)
