"""Canonical chain validator for graph_json v2 — BRA-75 MVP.

Enforces a subset of the rules from
`ai-brain/docs/architecture/graph-json-canonical-architecture.md` §6 sufficient
for the MVP: chain integrity, persona-children rule, no-orphan, no-cycle,
edge-consistency, no duplicate slug per node_type within scope.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from api.schemas.graph_json_v2 import GraphJson  # type: ignore
else:
    try:
        from schemas.graph_json_v2 import GraphJson  # when invoked from api/ as cwd
    except ModuleNotFoundError:  # pragma: no cover
        from api.schemas.graph_json_v2 import GraphJson


# Allowed parent node_types per child node_type (canonical chain).
CANONICAL_PARENT: dict[str, tuple[str, ...]] = {
    "brand": ("persona",),
    "campaign": ("brand", "briefing"),
    "briefing": ("brand", "campaign"),
    "audience": ("campaign", "briefing"),
    "product_group": ("audience",),
    "product": ("product_group", "audience"),
    "offer": ("product", "product_group"),
    "copy": ("product", "product_group", "offer"),
    "rule": ("campaign", "briefing", "brand", "persona"),
    "faq": ("copy", "product", "product_group", "audience", "briefing", "campaign", "brand", "persona", "rule"),
    "embedded": ("faq",),
    "asset": ("product", "product_group", "campaign", "brand", "gallery"),
}

# Types that may attach to persona as a protected branch outside the main chain.
PROTECTED_PERSONA_CHILDREN: set[str] = {"gallery"}


FAQ_APPROVED_STATUSES: set[str] = {"approved", "validated", "embedded", "active", "ativo"}


def _has_cycle(start_id: str, nodes_by_id: dict[str, "object"]) -> bool:
    seen: set[str] = set()
    current = start_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        node = nodes_by_id.get(current)
        if node is None:
            return False
        current = getattr(node, "parent_id", None) or ""
    return False


def _has_descendant_type(node_id: str, node_type: str, nodes_by_id: dict[str, "object"]) -> bool:
    for node in nodes_by_id.values():
        if getattr(node, "parent_id", None) != node_id:
            continue
        if getattr(node, "node_type", None) == node_type:
            return True
        if _has_descendant_type(getattr(node, "id", ""), node_type, nodes_by_id):
            return True
    return False


def _node_data(node: "object") -> dict:
    data = getattr(node, "data", None)
    return data if isinstance(data, dict) else {}


def _status_of(node: "object") -> str:
    data = _node_data(node)
    return str(data.get("validation_status") or data.get("status") or "").strip().lower()


def _is_primary(edge: "object") -> bool:
    return getattr(edge, "primary_tree", True) is True


def validate_graph_json(graph: "GraphJson") -> tuple[bool, list[str]]:
    """Return (is_valid, errors) for the canonical chain rules in scope for MVP."""
    errors: list[str] = []
    nodes_by_id = {n.id: n for n in graph.nodes}

    # 0. Schema version lock for v2 contract.
    if graph.schema_version != "2.0":
        errors.append(f"schema_version must be 2.0, got {graph.schema_version}")

    # 0.1 Persona ownership: exactly one persona node, matching payload persona_slug.
    persona_nodes = [n for n in graph.nodes if n.node_type == "persona"]
    if len(persona_nodes) != 1:
        errors.append(f"graph must contain exactly one persona node, got {len(persona_nodes)}")
    elif persona_nodes[0].slug != graph.persona_slug:
        errors.append(
            f"persona ownership mismatch: node slug={persona_nodes[0].slug} payload persona_slug={graph.persona_slug}"
        )

    # 1. No duplicate (node_type, slug) within scope.
    seen: set[tuple[str, str]] = set()
    for node in graph.nodes:
        key = (node.node_type, node.slug)
        if key in seen:
            errors.append(f"duplicate node (type={node.node_type}, slug={node.slug})")
        seen.add(key)

    # 2. Persona has no parent_id.
    # 3. Every non-persona node has a parent reachable in this document.
    # 4. Parent type respects canonical chain.
    for node in graph.nodes:
        if node.node_type == "persona":
            if node.parent_id:
                errors.append(f"persona node {node.id} must not have parent_id")
            continue

        if not node.parent_id:
            errors.append(f"orphan node: {node.id} (type={node.node_type})")
            continue

        parent = nodes_by_id.get(node.parent_id)
        if parent is None:
            errors.append(f"node {node.id} parent_id={node.parent_id} not found in document")
            continue

        if node.node_type in PROTECTED_PERSONA_CHILDREN:
            if parent.node_type != "persona":
                errors.append(
                    f"protected node {node.id} (type={node.node_type}) must hang off persona"
                )
            continue

        allowed = CANONICAL_PARENT.get(node.node_type)
        if allowed is None:
            errors.append(f"unknown node_type {node.node_type} on node {node.id}")
            continue

        if parent.node_type not in allowed:
            errors.append(
                f"node {node.id} (type={node.node_type}) has parent type {parent.node_type}, "
                f"expected one of {allowed}"
            )
        elif node.node_type == "faq" and parent.node_type == "product_group":
            data = _node_data(node)
            general_group_faq = data.get("grouped_faq") is True or data.get("scope") in {"product_group", "general"}
            if _has_descendant_type(parent.id, "product", nodes_by_id) and not general_group_faq:
                errors.append(
                    f"node {node.id} (type=faq) cannot hang from product_group {parent.id} "
                    "while a product exists below that product_group"
                )
        elif node.node_type == "embedded" and _status_of(parent) not in FAQ_APPROVED_STATUSES:
            errors.append(f"pending FAQ cannot connect to embedded: {parent.id}")

        if node.node_type == "faq":
            data = _node_data(node)
            if not data.get("branch_path"):
                errors.append(f"faq node {node.id} must include data.branch_path")
            if not data.get("source_node_id"):
                errors.append(f"faq node {node.id} must include data.source_node_id")
            if not data.get("source_node_type"):
                errors.append(f"faq node {node.id} must include data.source_node_type")
            if data.get("markdown_document") is True:
                if not str(data.get("markdown") or "").strip():
                    errors.append(f"grouped faq node {node.id} must include data.markdown")
                if int(data.get("question_count") or 0) < 1:
                    errors.append(f"grouped faq node {node.id} must include data.question_count >= 1")

    # 5. No cycle reachable through parent_id chain.
    for node in graph.nodes:
        if _has_cycle(node.id, nodes_by_id):
            errors.append(f"cycle detected starting at {node.id}")
            break

    # 6. Edge source/target must exist and primary edges must mirror parent_id.
    primary_parent_edges: dict[str, str] = {}
    for edge in graph.edges:
        if edge.source not in nodes_by_id:
            errors.append(f"edge {edge.id} source {edge.source} missing")
        if edge.target not in nodes_by_id:
            errors.append(f"edge {edge.id} target {edge.target} missing")
        if edge.source == edge.target:
            errors.append(f"edge {edge.id} self-loop is not allowed")
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source and target and getattr(target, "node_type", None) == "embedded" and getattr(source, "node_type", None) != "faq":
            errors.append(f"embedded edge {edge.id} source must be FAQ, got {getattr(source, 'node_type', None)}")
        if source and target and _is_primary(edge):
            expected_parent = getattr(target, "parent_id", None)
            if expected_parent and edge.source != expected_parent:
                errors.append(f"primary edge {edge.id} does not match target parent_id")
            previous = primary_parent_edges.get(edge.target)
            if previous and previous != edge.source:
                errors.append(f"node {edge.target} has multiple primary parents")
            primary_parent_edges[edge.target] = edge.source

    for node in graph.nodes:
        if node.node_type == "persona":
            continue
        if not node.parent_id:
            continue
        if node.id not in primary_parent_edges:
            errors.append(f"node {node.id} has no primary edge from its parent")

    return (not errors, errors)
