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
    "service": ("product_group", "audience"),
    "offer": ("product", "product_group"),
    "copy": ("product", "product_group", "offer"),
    "rule": ("campaign", "briefing", "brand", "persona", "product", "service"),
    "tone": ("campaign", "briefing", "brand", "persona"),
    "faq": ("copy", "product", "product_group", "audience", "briefing", "campaign", "brand", "persona", "rule"),
    "embedded": ("faq",),
    # Gallery is an output sink, never the hierarchical parent of an asset.
    # The asset belongs below the commercial node it represents and reaches
    # Gallery through a secondary ``asset -> gallery`` edge.
    "asset": ("product", "product_group", "campaign", "brand"),
}

# Types that may attach to persona as a protected branch outside the main chain.
PROTECTED_PERSONA_CHILDREN: set[str] = {"gallery"}


FAQ_APPROVED_STATUSES: set[str] = {"approved", "validated", "embedded", "active", "ativo"}

V21_KNOWLEDGE_TYPES = {
    "persona", "brand", "briefing", "campaign", "audience", "product_group",
    "product", "service", "offer", "copy", "faq", "rule", "tone", "asset",
}
V21_ACTION_TYPES = {"gallery", "embedded", "marketing_workspace"}
V21_RELATIONS = {
    "contains", "targets", "represents", "uses_asset", "supports", "answers",
    "applies_to", "derived_from", "references", "publishes_to",
}
V21_APPROVED = {"approved", "active"}


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


def _validate_appointment_policy(nodes: list["object"], errors: list[str]) -> None:
    """Require every appointment question to be authored in the graph.

    A canonical graph cannot depend on backend copy. Its persona policy owns
    the ordered required fields and the exact question for each one.
    Product-specific required fields use the same question map.
    """
    persona = next(
        (node for node in nodes if getattr(node, "node_type", None) == "persona"),
        None,
    )
    if persona is None:
        return
    data = _node_data(persona)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    business_model = str(
        data.get("business_model") or metadata.get("business_model") or ""
    ).strip().lower()
    raw_policy = data.get("appointment_policy")
    if business_model != "appointment" and not isinstance(raw_policy, dict):
        return
    if not isinstance(raw_policy, dict):
        errors.append("appointment persona requires data.appointment_policy")
        return

    required = raw_policy.get("required_fields")
    questions = raw_policy.get("field_questions")
    question_node_ids = raw_policy.get("field_question_node_ids")
    if not isinstance(required, list) or not required:
        errors.append("appointment_policy.required_fields must be a non-empty list")
        required = []
    if not isinstance(questions, dict):
        errors.append("appointment_policy.field_questions must be an object")
        questions = {}

    all_required: list[str] = []
    for field in required:
        normalized = str(field).strip()
        if not normalized:
            errors.append("appointment_policy.required_fields contains an empty field")
            continue
        if normalized not in all_required:
            all_required.append(normalized)

    for node in nodes:
        if getattr(node, "node_type", None) not in {"product", "service"}:
            continue
        node_data = _node_data(node)
        booking = node_data.get("booking")
        product_required = booking.get("required_fields") if isinstance(booking, dict) else None
        if isinstance(product_required, list):
            for field in product_required:
                normalized = str(field).strip()
                if normalized and normalized not in all_required:
                    all_required.append(normalized)
        qualification = node_data.get("qualification")
        declared_fields = qualification.get("fields") if isinstance(qualification, dict) else None
        if isinstance(declared_fields, list):
            for item in declared_fields:
                normalized = str(
                    item.get("key") if isinstance(item, dict) else item
                ).strip()
                if normalized and normalized not in all_required:
                    all_required.append(normalized)

    conditional = raw_policy.get("conditional_fields")
    if isinstance(conditional, dict):
        for field in conditional:
            normalized = str(field).strip()
            if normalized and normalized not in all_required:
                all_required.append(normalized)

    for field in all_required:
        question = questions.get(field)
        if not isinstance(question, str) or not question.strip():
            errors.append(
                f"appointment_policy.field_questions missing non-empty question for required field {field}"
            )

    # Once a graph uses executable qualification FAQs, every required field
    # must resolve to one matching FAQ node.  Legacy v2.0 documents remain
    # readable until their next v2.1 publication materializes this map.
    if question_node_ids is not None:
        if not isinstance(question_node_ids, dict):
            errors.append("appointment_policy.field_question_node_ids must be an object")
            question_node_ids = {}
        nodes_by_id = {getattr(node, "id", ""): node for node in nodes}
        for field in all_required:
            node_id = str(question_node_ids.get(field) or "").strip()
            question_node = nodes_by_id.get(node_id)
            if not node_id or question_node is None:
                errors.append(
                    f"appointment_policy.field_question_node_ids missing FAQ node for required field {field}"
                )
                continue
            if getattr(question_node, "node_type", None) != "faq":
                errors.append(f"qualification question node {node_id} must be faq")
                continue
            question_data = _node_data(question_node)
            metadata = question_data.get("metadata") if isinstance(question_data.get("metadata"), dict) else {}
            role = metadata.get("role") or question_data.get("role")
            mapped_field = metadata.get("field_key") or question_data.get("field_key")
            if role != "qualification_question" or mapped_field != field:
                errors.append(
                    f"qualification question node {node_id} does not declare field {field}"
                )


def _is_primary(edge: "object") -> bool:
    return getattr(edge, "primary_tree", True) is True


def _validate_v21(graph: "GraphJson") -> tuple[bool, list[str]]:
    """Validate the destination-scoped 2.1 contract without legacy parent rules."""
    errors: list[str] = []
    nodes_by_id = {node.id: node for node in graph.nodes}
    if len(nodes_by_id) != len(graph.nodes):
        errors.append("duplicate node id")

    personas = [node for node in graph.nodes if node.node_type == "persona"]
    if len(personas) != 1:
        errors.append(f"graph must contain exactly one persona node, got {len(personas)}")
    elif personas[0].slug != graph.persona_slug:
        errors.append(
            f"persona ownership mismatch: node slug={personas[0].slug} payload persona_slug={graph.persona_slug}"
        )

    seen_slugs: set[tuple[str, str]] = set()
    for node in graph.nodes:
        key = (node.node_type, node.slug)
        if key in seen_slugs:
            errors.append(f"duplicate node (type={node.node_type}, slug={node.slug})")
        seen_slugs.add(key)
        if node.node_class == "action":
            if node.node_type not in V21_ACTION_TYPES:
                errors.append(f"action node {node.id} has invalid node_type {node.node_type}")
            if node.action is None:
                errors.append(f"action node {node.id} requires action configuration")
        elif node.node_type not in V21_KNOWLEDGE_TYPES:
            errors.append(f"unknown node_type {node.node_type} on node {node.id}")
        if node.node_type in V21_ACTION_TYPES and node.node_class != "action":
            errors.append(f"node {node.id} type {node.node_type} must use node_class=action")
        if node.node_type not in V21_ACTION_TYPES and node.node_class != "knowledge":
            errors.append(f"node {node.id} type {node.node_type} must use node_class=knowledge")

    contains_parents: dict[str, str] = {}
    contains_children: dict[str, list[str]] = {}
    edge_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        relation = edge.relation_type or edge.relation or ""
        if edge.id in edge_ids:
            errors.append(f"duplicate edge id {edge.id}")
        edge_ids.add(edge.id)
        key = (edge.source, edge.target, relation)
        if key in edge_keys:
            errors.append(f"duplicate edge ({edge.source}, {edge.target}, {relation})")
        edge_keys.add(key)
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None:
            errors.append(f"edge {edge.id} source {edge.source} missing")
        if target is None:
            errors.append(f"edge {edge.id} target {edge.target} missing")
        if source is None or target is None:
            continue
        if source.id == target.id:
            errors.append(f"edge {edge.id} self-loop is not allowed")
        if relation not in V21_RELATIONS:
            errors.append(f"edge {edge.id} has unknown relation_type {relation}")
            continue
        if edge.lifecycle.status == "revoked":
            continue
        if relation == "contains":
            if source.node_class != "knowledge" or target.node_class != "knowledge":
                errors.append(f"contains edge {edge.id} may only connect knowledge nodes")
            if target.node_type == "persona":
                errors.append(f"persona cannot be target of contains edge {edge.id}")
            previous = contains_parents.get(target.id)
            if previous and previous != source.id:
                errors.append(f"node {target.id} has multiple contains parents")
            contains_parents[target.id] = source.id
            contains_children.setdefault(source.id, []).append(target.id)
        elif relation == "publishes_to":
            if source.node_class != "knowledge" or target.node_class != "action":
                errors.append(f"publishes_to edge {edge.id} must be knowledge -> action")
            if source.lifecycle.status not in V21_APPROVED:
                errors.append(f"publishes_to source {source.id} must be approved")
            if target.action:
                accepted = set(target.action.accepted_node_types)
                if accepted and source.node_type not in accepted:
                    errors.append(
                        f"action {target.id} does not accept node_type {source.node_type}"
                    )
                if target.action.policy.requires_approved_content and source.lifecycle.status not in V21_APPROVED:
                    errors.append(f"action {target.id} requires approved source {source.id}")
            if edge.grant is None:
                errors.append(f"publishes_to edge {edge.id} requires grant")

    persona_id = personas[0].id if len(personas) == 1 else None
    for node in graph.nodes:
        if node.node_class == "action" or node.node_type == "persona":
            continue
        if node.id not in contains_parents:
            errors.append(f"knowledge node {node.id} requires exactly one contains parent")

    # Every hierarchy path must terminate at Persona; cycles and disconnected
    # roots are both rejected by the same bounded walk.
    if persona_id:
        for node in graph.nodes:
            if node.node_class == "action" or node.id == persona_id:
                continue
            current = node.id
            visited: set[str] = set()
            while current != persona_id and current in contains_parents:
                if current in visited:
                    errors.append(f"contains cycle detected starting at {node.id}")
                    break
                visited.add(current)
                current = contains_parents[current]
            if current != persona_id and not any("cycle detected" in err and node.id in err for err in errors):
                errors.append(f"node {node.id} contains path does not reach persona")

    _validate_appointment_policy(graph.nodes, errors)
    return (not errors, errors)


def validate_graph_json(graph: "GraphJson") -> tuple[bool, list[str]]:
    """Return (is_valid, errors) for the canonical chain rules in scope for MVP."""
    if graph.schema_version == "2.1":
        return _validate_v21(graph)
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

        # Embedded is a terminal multi-source sink.  Before the first FAQ is
        # approved it is anchored to Persona for layout only, without a visual
        # Persona -> Embedded edge.  Published FAQ -> Embedded edges remain the
        # only semantic inputs.
        if node.node_type == "embedded" and parent.node_type == "persona":
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
        if source and target and getattr(target, "node_type", None) == "embedded" and _is_primary(edge):
            errors.append(f"embedded edge {edge.id} must be secondary (primary_tree=false)")
        if source and target and getattr(target, "node_type", None) == "gallery":
            # Gallery itself hangs from Persona as a protected node.  Every
            # other incoming connection is the terminal asset -> Gallery edge.
            if getattr(source, "node_type", None) == "persona":
                if not _is_primary(edge):
                    errors.append(f"gallery root edge {edge.id} must be primary")
            else:
                if getattr(source, "node_type", None) != "asset" or getattr(edge, "relation", None) != "gallery_asset":
                    errors.append(f"gallery edge {edge.id} must be asset -> gallery with relation gallery_asset")
                if _is_primary(edge):
                    errors.append(f"gallery edge {edge.id} must be secondary (primary_tree=false)")
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
        if node.node_type == "embedded" and nodes_by_id[node.parent_id].node_type == "persona":
            continue
        if node.id not in primary_parent_edges:
            errors.append(f"node {node.id} has no primary edge from its parent")

    # Every asset surfaced by a public site must finish at Gallery.  This makes
    # the Graph JSON sufficient to decide whether a disconnected image can be
    # rendered by the landing-page projection.
    gallery_links = {
        edge.source
        for edge in graph.edges
        if not _is_primary(edge)
        and getattr(edge, "relation", None) == "gallery_asset"
        and getattr(nodes_by_id.get(edge.source), "node_type", None) == "asset"
        and getattr(nodes_by_id.get(edge.target), "node_type", None) == "gallery"
    }
    for node in graph.nodes:
        if node.node_type == "asset" and node.id not in gallery_links:
            errors.append(f"asset node {node.id} must have a secondary asset -> gallery edge")

    embedded_edges_by_faq: dict[str, list[object]] = {}
    for edge in graph.edges:
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if (
            source
            and target
            and getattr(source, "node_type", None) == "faq"
            and getattr(target, "node_type", None) == "embedded"
        ):
            embedded_edges_by_faq.setdefault(edge.source, []).append(edge)
    for node in graph.nodes:
        if node.node_type != "faq":
            continue
        links = embedded_edges_by_faq.get(node.id, [])
        if _status_of(node) in FAQ_APPROVED_STATUSES and len(links) != 1:
            errors.append(f"approved FAQ {node.id} must have exactly one FAQ -> Embedded edge")
        if _status_of(node) not in FAQ_APPROVED_STATUSES and links:
            errors.append(f"pending FAQ cannot connect to embedded: {node.id}")

    _validate_appointment_policy(graph.nodes, errors)
    return (not errors, errors)
