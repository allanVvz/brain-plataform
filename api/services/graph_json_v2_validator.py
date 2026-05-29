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
    "briefing": ("brand",),
    "campaign": ("briefing",),
    "audience": ("campaign",),
    "product_group": ("audience",),
    "product": ("product_group",),
    "faq": ("product",),
    "embedded": ("faq",),
}

# Types that may attach to persona as a protected branch outside the main chain.
PROTECTED_PERSONA_CHILDREN: set[str] = {"gallery"}


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

    # 5. No cycle reachable through parent_id chain.
    for node in graph.nodes:
        if _has_cycle(node.id, nodes_by_id):
            errors.append(f"cycle detected starting at {node.id}")
            break

    # 6. Edge source/target must exist.
    for edge in graph.edges:
        if edge.source not in nodes_by_id:
            errors.append(f"edge {edge.id} source {edge.source} missing")
        if edge.target not in nodes_by_id:
            errors.append(f"edge {edge.id} target {edge.target} missing")
        if edge.source == edge.target:
            errors.append(f"edge {edge.id} self-loop is not allowed")

    return (not errors, errors)
