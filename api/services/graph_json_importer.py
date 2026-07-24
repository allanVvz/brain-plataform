from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from schemas.graph_json_v2 import Edge, GraphJson, Node
from services import graph_json_v2_validator, supabase_client
from services.vault_sync import VAULT_PATH as CONFIGURED_VAULT_PATH


VAULT_PATH = Path(CONFIGURED_VAULT_PATH)


RELATION_BY_PAIR: dict[tuple[str, str], str] = {
    ("persona", "brand"): "belongs_to_persona",
    ("brand", "briefing"): "contains",
    ("brand", "campaign"): "part_of_campaign",
    ("campaign", "briefing"): "contains",
    ("briefing", "campaign"): "part_of_campaign",
    ("campaign", "audience"): "targets_audience",
    ("briefing", "audience"): "targets_audience",
    ("audience", "product_group"): "audience_has_product_group",
    ("product_group", "product"): "product_group_has_product",
    ("product_group", "offer"): "contains",
    ("product", "offer"): "contains",
    ("product_group", "copy"): "supports_copy",
    ("product", "copy"): "supports_copy",
    ("offer", "copy"): "supports_copy",
    ("campaign", "rule"): "contains",
    ("briefing", "rule"): "contains",
    ("brand", "rule"): "contains",
    ("rule", "faq"): "answers_question",
    ("copy", "faq"): "answers_question",
    ("product", "faq"): "answers_question",
    ("product_group", "faq"): "answers_question",
    ("faq", "embedded"): "visible_to_agent",
    ("gallery", "asset"): "gallery_asset",
}


def _slug(value: str) -> str:
    text = (value or "").strip().lower()
    out: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    return "".join(out).strip("-") or "node"


def _content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _node_markdown(node: Node) -> str:
    data = node.data or {}
    markdown = str(data.get("markdown") or data.get("content") or "").strip()
    if markdown:
        return markdown
    title = node.label or node.slug
    summary = str(data.get("summary") or "").strip()
    return f"# {title}\n\n{summary}".strip()


def _file_path(graph: GraphJson, node: Node) -> str:
    data = node.data or {}
    if data.get("file_path"):
        return str(data["file_path"])
    folder = {
        "brand": "01_BRAND",
        "campaign": "02_CAMPAIGN",
        "briefing": "03_BRIEFING",
        "audience": "04_AUDIENCE",
        "product_group": "05_PRODUCT_GROUP",
        "product": "06_PRODUCT",
        "offer": "07_OFFER",
        "copy": "08_COPY",
        "rule": "09_RULE",
        "faq": "10_FAQ",
        "asset": "11_ASSET",
    }.get(node.node_type, "99_OTHER")
    return f"{graph.persona_slug}/{folder}/{node.slug}.md"


def _write_vault_file(relative_path: str, content: str) -> Path:
    path = VAULT_PATH / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _node_status(node: Node) -> str:
    status = str((node.data or {}).get("validation_status") or (node.data or {}).get("status") or "pending").lower()
    if status in {"validated", "approved", "active", "ativo"}:
        return "validated"
    return "pending"


def _item_status(node: Node) -> str:
    status = str((node.data or {}).get("validation_status") or (node.data or {}).get("status") or "pending").lower()
    if status in {"validated", "approved", "active", "ativo"}:
        # knowledge_items has its own legacy enum and does not accept the
        # graph-node status ``validated``.  Keep the graph node validated, but
        # materialize the source item as ``approved`` (the closest allowed
        # canonical state).
        return "approved"
    return "pending"


def _node_metadata(graph: GraphJson, node: Node, relative_path: str, content: str, session_id: str | None) -> dict[str, Any]:
    data = dict(node.data or {})
    data.update(
        {
            "graph_json_id": graph.graph_id,
            "graph_json_node_id": node.id,
            "graph_json_import": True,
            "schema_version": graph.schema_version,
            "slug": node.slug,
            "file_path": relative_path,
            "content_hash": _content_hash(content),
        }
    )
    if session_id:
        data["session_id"] = session_id
    if node.parent_id:
        data["graph_json_parent_id"] = node.parent_id
    return data


def _default_relation(parent_type: str, child_type: str) -> str:
    return RELATION_BY_PAIR.get((parent_type, child_type), "contains")


# content_type (Sofia Criar plan) -> canonical graph node_type. Non-canonical
# types (tone/entity/competitor/prompt/maker_material/other) are NOT part of the
# graph law chain and are dropped from the canonical tree.
_PLAN_TYPE_ALIASES: dict[str, str] = {
    "product_collection": "product_group",
    "publico": "audience",
    "rules": "rule",
}
_CANONICAL_NODE_TYPES: set[str] = {
    "persona", "brand", "briefing", "campaign", "audience",
    "product_group", "product", "offer", "copy", "rule", "faq",
    "embedded", "asset", "gallery",
}
_PERSONA_PARENTS: set[str] = {"", "self", "persona", "root", "global"}


def _canon_plan_type(content_type: str | None) -> str | None:
    t = (content_type or "").strip().lower()
    t = _PLAN_TYPE_ALIASES.get(t, t)
    return t if t in _CANONICAL_NODE_TYPES else None


def _parent_slug_of(entry: dict, links_by_target: dict[str, str]) -> str:
    meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    raw = str(meta.get("parent_slug") or "").strip().lower()
    if raw:
        return raw
    slug = str(entry.get("slug") or "").strip().lower()
    return links_by_target.get(slug, "")


def normalized_plan_to_graph_json(
    plan: dict[str, Any],
    session: dict[str, Any] | None = None,
    *,
    tenant: str = "qa",
    graph_id: str | None = None,
) -> GraphJson:
    """Pure conversion: Sofia Criar `normalized_plan` -> canonical GraphJson.

    Does NOT persist. The single canonical document the importer/validator and the
    front-end all consume. Non-canonical content_types are dropped from the tree.
    The result is meant to be validated by `graph_json_v2_validator.validate_graph_json`
    before any persistence (the importer calls the validator itself).
    """
    plan = plan or {}
    session = session or {}
    persona_slug = str(
        plan.get("persona_slug") or session.get("persona_slug") or ""
    ).strip().lower()
    persona_id = f"node:persona:{persona_slug}"
    persona_label = str(
        session.get("persona_name") or plan.get("persona_name") or persona_slug
    ).strip() or persona_slug

    nodes: list[Node] = [
        Node(
            id=persona_id,
            node_type="persona",
            slug=persona_slug,
            label=persona_label,
            parent_id=None,
            data={"source": "sofia_criar", "status": "validated"},
        )
    ]

    entries = [e for e in (plan.get("entries") or []) if isinstance(e, dict)]
    links_by_target: dict[str, str] = {}
    for link in plan.get("links") or []:
        if not isinstance(link, dict):
            continue
        tgt = str(link.get("target_slug") or "").strip().lower()
        src = str(link.get("source_slug") or "").strip().lower()
        if tgt and src and tgt not in links_by_target:
            links_by_target[tgt] = src

    # Pass 1: assign canonical node ids (dedupe by node_type+slug).
    resolved: list[dict[str, Any]] = []
    slug_to_id: dict[str, str] = {}
    seen_ids: set[str] = set()
    for entry in entries:
        node_type = _canon_plan_type(entry.get("content_type"))
        if not node_type or node_type == "persona":
            continue
        slug = _slug(str(entry.get("slug") or entry.get("title") or node_type))
        node_id = f"node:{node_type}:{slug}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        slug_to_id[slug] = node_id
        orig_slug = str(entry.get("slug") or "").strip().lower()
        if orig_slug:
            slug_to_id[orig_slug] = node_id
        resolved.append({"entry": entry, "node_type": node_type, "slug": slug, "id": node_id})

    # Pass 2: parent resolution.
    parent_id_by_node: dict[str, str] = {}
    for item in resolved:
        parent_slug = _parent_slug_of(item["entry"], links_by_target)
        if parent_slug in _PERSONA_PARENTS:
            parent_id_by_node[item["id"]] = persona_id
        else:
            parent_id_by_node[item["id"]] = slug_to_id.get(parent_slug, persona_id)

    nodes_by_id: dict[str, Node] = {}

    def _branch_path(node_id: str) -> list[dict[str, str]]:
        chain: list[dict[str, str]] = []
        cur = node_id
        guard = 0
        while cur and guard < 64:
            guard += 1
            node = nodes_by_id.get(cur)
            if node is None:
                break
            chain.insert(0, {"node_type": node.node_type, "slug": node.slug, "label": node.label})
            cur = node.parent_id or ""
        return chain

    # Pass 3: build nodes (persona first so branch_path can walk it).
    nodes_by_id[persona_id] = nodes[0]
    for item in resolved:
        entry = item["entry"]
        node_type = item["node_type"]
        meta = dict(entry.get("metadata") or {})
        content = str(entry.get("content") or "").strip()
        data: dict[str, Any] = {
            **meta,
            "source": meta.get("source") or entry.get("source") or "sofia_criar",
            "status": str(entry.get("status") or meta.get("status") or "pending_validation"),
            "summary": (content[:400] if content else meta.get("summary")),
            "tags": entry.get("tags") or meta.get("tags") or [node_type],
        }
        if content:
            data["markdown"] = content
        node = Node(
            id=item["id"],
            node_type=node_type,
            slug=item["slug"],
            label=str(entry.get("title") or item["slug"]),
            parent_id=parent_id_by_node[item["id"]],
            data=data,
        )
        nodes_by_id[item["id"]] = node
        nodes.append(node)

    # Pass 4: enrich FAQ nodes with the inherited-context fields the validator requires.
    for item in resolved:
        if item["node_type"] != "faq":
            continue
        node = nodes_by_id[item["id"]]
        parent_id = node.parent_id or persona_id
        parent = nodes_by_id.get(parent_id)
        node.data.setdefault("source_node_id", parent_id)
        node.data.setdefault("source_node_type", parent.node_type if parent else "persona")
        node.data.setdefault("branch_path", _branch_path(parent_id))
        meta = item["entry"].get("metadata") or {}
        if meta.get("markdown_document") is True or meta.get("generate_via") == "branch":
            node.data["markdown_document"] = True
            node.data.setdefault("markdown", str(item["entry"].get("content") or node.label))
            node.data["question_count"] = int(meta.get("question_count") or 1) or 1

    # Pass 5: primary edges mirror parent_id.
    edges: list[Edge] = []
    for idx, item in enumerate(resolved):
        node = nodes_by_id[item["id"]]
        parent_id = node.parent_id or persona_id
        parent = nodes_by_id.get(parent_id)
        relation = _default_relation(parent.node_type if parent else "persona", node.node_type)
        edges.append(
            Edge(
                id=f"edge:{idx + 1}",
                source=parent_id,
                target=node.id,
                relation=relation,
                primary_tree=True,
                metadata={"created_from": "normalized_plan_to_graph_json"},
            )
        )

    return GraphJson(
        schema_version="2.0",
        graph_id=graph_id or f"{persona_slug}-criar",
        tenant=tenant,
        persona_slug=persona_slug,
        status="draft",
        nodes=nodes,
        edges=edges,
    )


def import_graph_json(*, graph_json: GraphJson, source: str = "graph_json.import", session_id: str | None = None) -> dict[str, Any]:
    is_valid, errors = graph_json_v2_validator.validate_graph_json(graph_json)
    if not is_valid:
        return {"ok": False, "error_code": "GRAPH_JSON_INVALID", "errors": errors}

    persona = supabase_client.get_persona(graph_json.persona_slug)
    if not persona:
        return {"ok": False, "error_code": "PERSONA_NOT_FOUND", "errors": [f"Persona not found: {graph_json.persona_slug}"]}
    persona_id = persona["id"]
    source_row = supabase_client.get_or_create_manual_source()

    graph_nodes_by_doc_id: dict[str, dict] = {}
    item_ids: list[str] = []
    written_files: list[str] = []

    for node in graph_json.nodes:
        metadata = dict(node.data or {})
        if node.node_type == "persona":
            graph_node = supabase_client.upsert_knowledge_node(
                {
                    "persona_id": persona_id,
                    "node_type": "persona",
                    "slug": node.slug,
                    "title": node.label,
                    "summary": metadata.get("summary"),
                    "tags": metadata.get("tags") or ["persona"],
                    "metadata": _node_metadata(graph_json, node, "", "", session_id),
                    "status": "validated",
                }
            )
            if graph_node:
                graph_nodes_by_doc_id[node.id] = graph_node
            continue

        if node.node_type in {"embedded", "gallery"}:
            graph_node = supabase_client.upsert_knowledge_node(
                {
                    "persona_id": persona_id,
                    "node_type": node.node_type,
                    "slug": node.slug,
                    "title": node.label,
                    "summary": metadata.get("summary"),
                    "tags": metadata.get("tags") or [node.node_type],
                    "metadata": _node_metadata(graph_json, node, "", "", session_id),
                    "status": _node_status(node),
                }
            )
            if graph_node:
                graph_nodes_by_doc_id[node.id] = graph_node
            continue

        content = _node_markdown(node)
        relative_path = _file_path(graph_json, node)
        _write_vault_file(relative_path, content)
        written_files.append(relative_path)
        item_payload = {
            "persona_id": persona_id,
            "source_id": source_row.get("id"),
            "status": _item_status(node),
            "content_type": node.node_type,
            "title": node.label,
            "content": content[:8000],
            "metadata": _node_metadata(graph_json, node, relative_path, content, session_id),
            "file_path": supabase_client.normalize_file_path(relative_path),
            "file_type": "md",
            "tags": metadata.get("tags") or [node.node_type],
            "agent_visibility": metadata.get("agent_visibility") or ["SDR", "Closer", "Classifier"],
            "content_hash": _content_hash(content),
            "canonical_key": f"{graph_json.persona_slug}:{node.node_type}:{node.slug}",
            "canonical_hash": _content_hash(f"{graph_json.persona_slug}:{node.node_type}:{node.slug}:{content}"),
        }
        existing = supabase_client.get_knowledge_item_by_path(item_payload["file_path"])
        if existing and existing.get("id"):
            supabase_client.update_knowledge_item(existing["id"], item_payload)
            item = {**existing, **item_payload}
        else:
            item = supabase_client.insert_knowledge_item(item_payload)
        if not item or not item.get("id"):
            raise RuntimeError(f"knowledge_item import returned no id for {relative_path}")
        item_ids.append(item["id"])
        graph_node = supabase_client.upsert_knowledge_node(
            {
                "persona_id": persona_id,
                "source_table": "knowledge_items",
                "source_id": item["id"],
                "node_type": node.node_type,
                "slug": node.slug,
                "title": node.label,
                "summary": content[:400],
                "tags": item_payload["tags"],
                "metadata": {**item_payload["metadata"], "knowledge_item_id": item["id"]},
                "status": _node_status(node),
            }
        )
        if not graph_node or not graph_node.get("id"):
            raise RuntimeError(f"knowledge_node import returned no id for {node.id}")
        graph_nodes_by_doc_id[node.id] = graph_node
        supabase_client.update_knowledge_item(item["id"], {"metadata": {**item_payload["metadata"], "knowledge_node_id": graph_node["id"]}})

    edge_ids: list[str] = []
    for edge in graph_json.edges:
        if edge.primary_tree is not True:
            continue
        source_node = graph_nodes_by_doc_id.get(edge.source)
        target_node = graph_nodes_by_doc_id.get(edge.target)
        if not source_node or not target_node:
            raise RuntimeError(f"primary edge {edge.id} references non-imported node")
        relation = edge.relation if edge.relation and edge.relation != "main" else _default_relation(source_node.get("node_type"), target_node.get("node_type"))
        imported = supabase_client.upsert_knowledge_edge(
            source_node["id"],
            target_node["id"],
            relation,
            persona_id=persona_id,
            metadata={
                **(edge.metadata or {}),
                "primary_tree": True,
                "active": True,
                "graph_json_id": graph_json.graph_id,
                "graph_json_edge_id": edge.id,
                "created_from": source,
            },
        )
        if not imported or not imported.get("id"):
            raise RuntimeError(f"knowledge_edge import returned no id for {edge.id}")
        edge_ids.append(imported["id"])

    supabase_client.insert_event(
        {
            "event_type": "graph_json_imported",
            "entity_type": "graph_document",
            "entity_id": graph_json.graph_id,
            "persona_id": persona_id,
            "level": "info",
            "source": source,
            "payload": {
                "persona_slug": graph_json.persona_slug,
                "graph_id": graph_json.graph_id,
                "node_count": len(graph_json.nodes),
                "edge_count": len(graph_json.edges),
                "knowledge_item_ids": item_ids,
                "knowledge_edge_ids": edge_ids,
            },
        },
        source=source,
    )

    return {
        "ok": True,
        "graph_id": graph_json.graph_id,
        "persona_slug": graph_json.persona_slug,
        "nodes_imported": len(graph_nodes_by_doc_id),
        "edges_imported": len(edge_ids),
        "knowledge_item_ids": item_ids,
        "knowledge_node_ids": [node["id"] for node in graph_nodes_by_doc_id.values() if node.get("id")],
        "knowledge_edge_ids": edge_ids,
        "written_files": written_files,
    }
