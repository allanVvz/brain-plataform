# -*- coding: utf-8 -*-
"""Graph data endpoint — returns ReactFlow-compatible nodes and edges.

The payload is decorated with semantic level/importance/tier/weight pulled
from knowledge_node_type_registry + knowledge_relation_type_registry
(migration 009) so the frontend can render a layered, hierarchical graph
without re-deriving the ontology in JS.
"""

import logging
from collections import deque
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional

from services import auth_service, supabase_client

router = APIRouter(prefix="/knowledge", tags=["graph"])
logger = logging.getLogger("ai_brain.graph")


class GraphEdgeCreateBody(BaseModel):
    source_node_id: str
    target_node_id: str
    relation_type: str = "manual"
    persona_id: Optional[str] = None
    weight: float = 1.0
    metadata: dict = {}


def _raw_graph_node_id(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("gn:"):
        return raw[3:]
    return raw


def _resolve_graph_node_ref(value: str, persona_id: Optional[str] = None) -> Optional[dict]:
    raw = (value or "").strip()
    if raw.startswith("gn:"):
        return supabase_client.get_knowledge_node(raw[3:])
    if raw.startswith("persona:"):
        return supabase_client.ensure_persona_knowledge_node(raw.split(":", 1)[1])
    if raw and len(raw) == 36 and raw.count("-") == 4:
        return supabase_client.get_knowledge_node(raw)
    if raw == "gallery" and persona_id:
        return supabase_client.ensure_gallery_node(persona_id)
    if raw.startswith("embedded:"):
        return supabase_client.ensure_embedded_node(raw.split(":", 1)[1])
    if raw == "embedded" and persona_id:
        return supabase_client.ensure_embedded_node(persona_id)
    return None


@router.post("/graph-edges")
def create_graph_edge(body: GraphEdgeCreateBody, request: Request):
    source_node = _resolve_graph_node_ref(body.source_node_id, body.persona_id)
    target_node = _resolve_graph_node_ref(body.target_node_id, body.persona_id)
    if not source_node or not target_node:
        raise HTTPException(400, "source_node_id and target_node_id are required")
    relation_type = (body.relation_type or "manual").strip() or "manual"
    if target_node.get("node_type") == "gallery":
        relation_type = "gallery_asset"
    if relation_type == "gallery_asset" and "gallery" not in {source_node.get("node_type"), target_node.get("node_type")}:
        raise HTTPException(400, "gallery_asset edges must involve a Gallery node")
    source_id = source_node["id"]
    target_id = target_node["id"]
    if source_id == target_id:
        raise HTTPException(400, "Self connections are not allowed")
    edge_persona_id = body.persona_id or source_node.get("persona_id") or target_node.get("persona_id")
    if edge_persona_id:
        auth_service.assert_persona_access(request, persona_id=edge_persona_id)
    metadata = {
        **(body.metadata or {}),
        "created_from": (body.metadata or {}).get("created_from") or "graph_ui",
        "direction": (body.metadata or {}).get("direction") or "source_to_target",
    }
    if "primary_tree" not in metadata:
        metadata["primary_tree"] = relation_type == "manual"
    try:
        edge = supabase_client.upsert_knowledge_edge(
            source_node_id=source_id,
            target_node_id=target_id,
            relation_type=relation_type,
            persona_id=edge_persona_id,
            weight=body.weight,
            metadata=metadata,
        )
        if edge and relation_type == "gallery_asset":
            gallery_content_node = target_node if source_node.get("node_type") == "gallery" else source_node
            supabase_client.sync_gallery_asset_node(gallery_content_node, edge)
        if edge and target_node.get("node_type") == "embedded":
            supabase_client.sync_embedded_kb_node(source_node, edge)
    except Exception as exc:
        raise HTTPException(502, f"Could not create graph edge: {exc}") from exc
    if not edge:
        raise HTTPException(400, "Graph edge was not created")
    return {"ok": True, "edge": edge}


@router.delete("/graph-edges/{edge_id}")
def delete_graph_edge(edge_id: str, request: Request):
    raw_edge_id = edge_id[3:] if edge_id.startswith("ge:") else edge_id
    edge = supabase_client.get_knowledge_edge(raw_edge_id)
    if edge and edge.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=edge.get("persona_id"))
    try:
        ok = supabase_client.delete_knowledge_edge(raw_edge_id)
    except Exception as exc:
        logger.exception("Could not delete graph edge", extra={"edge_id": edge_id, "raw_edge_id": raw_edge_id})
        raise HTTPException(502, f"Could not delete graph edge: {exc}") from exc
    if not ok:
        logger.warning("Graph edge not found for delete", extra={"edge_id": edge_id, "raw_edge_id": raw_edge_id})
        raise HTTPException(404, "Graph edge not found")
    logger.info("Graph edge soft-deleted", extra={"edge_id": edge_id, "raw_edge_id": raw_edge_id})
    return {"ok": True, "edge_id": raw_edge_id}


@router.delete("/graph-nodes/{node_id}")
def delete_graph_node(node_id: str, request: Request):
    raw_node_id = _raw_graph_node_id(node_id)
    node = supabase_client.get_knowledge_node(raw_node_id)
    if node and node.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=node.get("persona_id"))
    try:
        ok = supabase_client.delete_knowledge_node(raw_node_id)
    except Exception as exc:
        raise HTTPException(502, f"Could not delete graph node: {exc}") from exc
    if not ok:
        raise HTTPException(404, "Graph node not found")
    return {"ok": True, "node_id": raw_node_id}

# knowledge_items statuses → nodeClass
_KI_STATUS: dict[str, str] = {
    "approved":       "validated",
    "embedded":       "validated",
    "pending":        "pending",
    "needs_persona":  "pending",
    "needs_category": "pending",
    "rejected":       "rejected",
}

# kb_entries statuses → nodeClass
_KB_STATUS: dict[str, str] = {
    "ATIVO":   "validated",
    "INATIVO": "rejected",
}

# Auxiliary node_types: hidden by default in the UI, but data is preserved.
_AUXILIARY_NODE_TYPES: set[str] = {"tag", "mention"}
_TECHNICAL_NODE_TYPES: set[str] = {"knowledge_item", "kb_entry"}

# Edge tier overrides — relations whose tier is fixed regardless of weight.
_STRUCTURAL_RELATIONS: set[str] = {
    "belongs_to_persona",
    "contains",
    "part_of_campaign",
    "about_product",
    "briefed_by",
    "answers_question",
    "supports_copy",
    "uses_asset",
    "manual",
    "gallery_asset",
}
_AUXILIARY_RELATIONS: set[str] = {"has_tag", "mentions", "same_topic_as", "visible_to_agent"}
_CURATION_RELATIONS: set[str] = {"duplicate_of"}


def _classify_relation_tier(relation_type: str, weight: float) -> str:
    """Map relation_type + default_weight → tier {strong|structural|auxiliary|curation}."""
    rt = (relation_type or "").lower()
    if rt in _CURATION_RELATIONS:
        return "curation"
    if rt in _STRUCTURAL_RELATIONS:
        return "structural"
    if rt in _AUXILIARY_RELATIONS:
        return "auxiliary"
    if weight is not None and weight >= 0.70:
        return "strong"
    return "auxiliary"


def _resolve_focus(focus: str, persona_id: Optional[str]) -> Optional[dict]:
    """Resolve a `focus` query param into the matching knowledge_node row.

    Accepts either:
      - "<node_type>:<slug>" (preferred — matches what _link_target generates)
      - a bare UUID (knowledge_nodes.id)
    """
    if not focus:
        return None
    client = supabase_client.get_client()
    try:
        if ":" in focus:
            node_type, slug = focus.split(":", 1)
            q = client.table("knowledge_nodes").select("*").eq("node_type", node_type.strip()).eq("slug", slug.strip())
            if persona_id:
                q = q.eq("persona_id", persona_id)
            rows = q.limit(1).execute().data or []
            return rows[0] if rows else None
        # Bare UUID lookup
        q = client.table("knowledge_nodes").select("*").eq("id", focus).limit(1)
        rows = q.execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _bfs_focus_subgraph(
    focus_node_id: str,
    all_nodes: list[dict],
    all_edges: list[dict],
    max_depth: int,
) -> tuple[set[str], dict[str, int], dict[str, tuple[str, str, str]]]:
    """BFS from focus_node_id through the directed graph (treated as undirected
    for navigation), returning:
      - reachable: set of node_ids within max_depth hops
      - distance: node_id -> hops from focus
      - predecessor: node_id -> (parent_id, relation_type, direction "in"|"out")
    """
    node_ids = {n["id"] for n in all_nodes if n.get("id")}
    if focus_node_id not in node_ids:
        return set(), {}, {}

    adj: dict[str, list[tuple[str, str, str]]] = {}
    for e in all_edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        rel = e.get("relation_type") or "related"
        if not src or not tgt:
            continue
        adj.setdefault(src, []).append((tgt, rel, "out"))
        adj.setdefault(tgt, []).append((src, rel, "in"))

    distance: dict[str, int] = {focus_node_id: 0}
    predecessor: dict[str, tuple[str, str, str]] = {}
    queue: deque[str] = deque([focus_node_id])
    while queue:
        nid = queue.popleft()
        d = distance[nid]
        if d >= max_depth:
            continue
        for (nb, rel, direction) in adj.get(nid, []):
            if nb in distance or nb not in node_ids:
                continue
            distance[nb] = d + 1
            predecessor[nb] = (nid, rel, direction)
            queue.append(nb)
    return set(distance.keys()), distance, predecessor


def _build_focus_path(
    focus_node_id: str,
    persona_node_id: Optional[str],
    nodes_by_id: dict[str, dict],
    predecessor: dict[str, tuple[str, str, str]],
) -> list[dict]:
    """Build a breadcrumb persona → ... → focus.

    The BFS is rooted at focus, so `predecessor[X] = (Y, rel, dir)` tells us
    that during the search we discovered X from Y. Walking predecessors from
    persona therefore gives [persona, ..., focus]. The relation/direction
    on each step describes the edge from the *next* node to the previous in
    the BFS direction; we re-orient it so the breadcrumb reads forward
    persona → focus.
    """
    if not persona_node_id or persona_node_id == focus_node_id:
        # Trivial path: only the focus node itself.
        node = nodes_by_id.get(focus_node_id, {})
        return [{
            "node_id": focus_node_id,
            "slug": node.get("slug"),
            "title": node.get("title"),
            "node_type": node.get("node_type"),
            "relation_type": None,
            "direction": None,
        }]
    if persona_node_id not in predecessor:
        # Persona wasn't reached by BFS — return just the focus node.
        node = nodes_by_id.get(focus_node_id, {})
        return [{
            "node_id": focus_node_id,
            "slug": node.get("slug"),
            "title": node.get("title"),
            "node_type": node.get("node_type"),
            "relation_type": None,
            "direction": None,
        }]

    # Walk persona → ... → focus via the BFS predecessor chain.
    raw: list[tuple[str, Optional[str], Optional[str]]] = []
    cur: Optional[str] = persona_node_id
    guard = 0
    seen: set[str] = set()
    while cur is not None and guard < 32 and cur not in seen:
        seen.add(cur)
        rel: Optional[str] = None
        direction: Optional[str] = None
        if cur in predecessor:
            _, rel, direction = predecessor[cur]
        raw.append((cur, rel, direction))
        if cur == focus_node_id:
            break
        nxt = predecessor.get(cur, (None,))[0]
        cur = nxt
        guard += 1

    chain: list[dict] = []
    for nid, rel, direction in raw:
        node = nodes_by_id.get(nid, {})
        chain.append({
            "node_id": nid,
            "slug": node.get("slug"),
            "title": node.get("title"),
            "node_type": node.get("node_type"),
            "relation_type": rel,
            "direction": direction,
        })
    return chain


def _compute_primary_depths(nodes: list[dict], edges: list[dict]) -> tuple[dict[str, int], dict[str, str]]:
    """Return node depth and parent map from the current structural graph."""
    node_ids = {n["id"] for n in nodes if n.get("id")}
    persona_ids = {n["id"] for n in nodes if n.get("node_type") == "persona"}
    structural = _STRUCTURAL_RELATIONS | {"manual", "contains", "parent_of", "belongs_to", "part_of"}
    parent_by_child: dict[str, str] = {}
    parent_priority_by_child: dict[str, int] = {}
    for edge in edges:
        src = edge.get("source_node_id")
        tgt = edge.get("target_node_id")
        if not src or not tgt or src not in node_ids or tgt not in node_ids:
            continue
        relation = (edge.get("relation_type") or "").lower()
        meta = edge.get("metadata") or {}
        if relation not in structural and not meta.get("primary_tree"):
            continue
        priority = 0
        if meta.get("primary_tree"):
            priority += 10
        if relation == "manual":
            priority += 100
        if tgt not in parent_by_child or priority >= parent_priority_by_child.get(tgt, -1):
            parent_by_child[tgt] = src
            parent_priority_by_child[tgt] = priority

    children_by_parent: dict[str, list[str]] = {}
    for child_id, parent_id in parent_by_child.items():
        children_by_parent.setdefault(parent_id, []).append(child_id)

    depth: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in persona_ids)
    while queue:
        node_id, d = queue.popleft()
        if node_id in depth and depth[node_id] <= d:
            continue
        depth[node_id] = d
        for child_id in children_by_parent.get(node_id, []):
            queue.append((child_id, d + 1))

    # Any disconnected semantic node gets a depth after the deepest connected node.
    fallback_depth = (max(depth.values()) + 1) if depth else 1
    for node_id in node_ids:
        depth.setdefault(node_id, fallback_depth)
    return depth, parent_by_child


def _focus_path_from_parents(
    focus_node_id: str,
    parent_by_child: dict[str, str],
    nodes_by_id: dict[str, dict],
) -> list[dict]:
    chain_ids: list[str] = []
    seen: set[str] = set()
    current: Optional[str] = focus_node_id
    while current and current not in seen and len(chain_ids) < 64:
        seen.add(current)
        chain_ids.append(current)
        current = parent_by_child.get(current)
    chain_ids.reverse()
    out: list[dict] = []
    for node_id in chain_ids:
        node = nodes_by_id.get(node_id, {})
        out.append({
            "node_id": node_id,
            "slug": node.get("slug"),
            "title": node.get("title"),
            "node_type": node.get("node_type"),
            "relation_type": None,
            "direction": None,
        })
    return out


@router.get("/graph-data")
def get_graph_data(
    request: Request,
    persona_slug: Optional[str] = Query(None),
    focus: Optional[str] = Query(None, description="<node_type>:<slug> or node_id"),
    max_depth: int = Query(3, ge=1, le=6, description="BFS depth from focus (or persona root)"),
    include_tags: bool = Query(False),
    include_mentions: bool = Query(False),
    include_technical: bool = Query(False, description="Include knowledge_items + kb_entries duplicate sources"),
    include_embedded: bool = Query(True, description="Include synthetic RAG embedded node and validated links"),
    mode: str = Query("layered", description="layered|semantic_tree|graph (frontend hint only)"),
):
    personas = supabase_client.get_personas()
    user = auth_service.current_user(request)
    access = auth_service.allowed_access(request)
    personas = auth_service.filter_personas_for_user(user, personas, access)
    if persona_slug:
        personas = [p for p in personas if p["slug"] == persona_slug]
        if not personas:
            raise HTTPException(403, "Acesso negado para esta persona.")

    persona_map = {p["id"]: p for p in personas}
    persona_id_set = set(persona_map.keys())

    single_persona_id: Optional[str] = None
    if persona_slug and len(personas) == 1:
        single_persona_id = personas[0]["id"]
    for p in personas:
        try:
            supabase_client.ensure_gallery_node(p["id"])
            supabase_client.ensure_embedded_node(p["id"])
        except Exception:
            logger.exception("Could not ensure protected graph nodes", extra={"persona_id": p.get("id")})

    # ── Registries (cached) ─────────────────────────────────────────────
    node_type_registry = supabase_client.get_node_type_registry()
    relation_type_registry = supabase_client.get_relation_type_registry()
    nt_by_type = {r["node_type"]: r for r in node_type_registry}
    rt_by_type = {r["relation_type"]: r for r in relation_type_registry}

    # ── Source: semantic graph (knowledge_nodes/edges) is the truth ─────
    try:
        sem_nodes, sem_edges = supabase_client.list_all_knowledge_graph(
            persona_id=single_persona_id, limit_nodes=1500,
        )
    except Exception:
        sem_nodes, sem_edges = [], []

    # Apply visibility filters early (still keeps data in DB).
    if not include_tags:
        sem_nodes = [n for n in sem_nodes if n.get("node_type") != "tag"]
    if not include_mentions:
        sem_nodes = [n for n in sem_nodes if n.get("node_type") != "mention"]
    sem_nodes = [n for n in sem_nodes if n.get("status") != "archived"]

    surviving_ids = {n["id"] for n in sem_nodes}
    sem_edges = [
        e for e in sem_edges
        if e.get("source_node_id") in surviving_ids and e.get("target_node_id") in surviving_ids
    ]
    graph_depths, parent_by_child = _compute_primary_depths(sem_nodes, sem_edges)

    # ── Optional: focus subgraph (BFS) ──────────────────────────────────
    focus_node = _resolve_focus(focus, single_persona_id) if focus else None
    focus_path: list[dict] = []
    if focus_node:
        nodes_by_id_raw = {n["id"]: n for n in sem_nodes}
        if focus_node["id"] not in nodes_by_id_raw:
            # Add it back if it was filtered out by include_*
            sem_nodes.append(focus_node)
            nodes_by_id_raw[focus_node["id"]] = focus_node
        structural_focus_path = _focus_path_from_parents(focus_node["id"], parent_by_child, nodes_by_id_raw)
        reachable, distance_map, predecessor = _bfs_focus_subgraph(
            focus_node["id"], sem_nodes, sem_edges, max_depth=max_depth,
        )
        reachable.update(step["node_id"] for step in structural_focus_path if step.get("node_id"))
        sem_nodes = [n for n in sem_nodes if n["id"] in reachable]
        sem_edges = [
            e for e in sem_edges
            if e.get("source_node_id") in reachable and e.get("target_node_id") in reachable
        ]
        focus_path = structural_focus_path
        if len(focus_path) <= 1:
            persona_root_id: Optional[str] = None
            for n in sem_nodes:
                if n.get("node_type") == "persona" and (n.get("persona_id") in persona_id_set or n.get("slug") == "self"):
                    persona_root_id = n["id"]
                    break
            nodes_by_id = {n["id"]: n for n in sem_nodes}
            focus_path = _build_focus_path(focus_node["id"], persona_root_id, nodes_by_id, predecessor)
    else:
        distance_map = {}

    current_depths, _ = _compute_primary_depths(sem_nodes, sem_edges)
    max_current_depth = max((d for d in current_depths.values() if d > 0), default=1)

    def current_level_for(node_id: str, node_type: str) -> int:
        if node_type == "persona":
            return 0
        if node_type == "gallery":
            return 112
        if node_type == "embedded":
            return 120
        depth = max(1, current_depths.get(node_id, max_current_depth))
        step = 99 / max(1, max_current_depth)
        return max(1, int(round(100 - depth * step)))

    # ── Build response payload ──────────────────────────────────────────
    nodes: list[dict] = []
    edges: list[dict] = []

    # Persona root nodes — only when not focus-scoped, or when focus reached
    # the persona. (If focus excluded the persona, we still want to show it.)
    persona_node_ids_emitted: set[str] = set()
    sem_persona_ids = {n.get("persona_id") for n in sem_nodes if n.get("node_type") == "persona"}
    for p in personas:
        # If we're scoped to focus and persona didn't survive BFS, skip.
        if focus_node and p["id"] not in {n.get("persona_id") for n in sem_nodes}:
            continue
        nodes.append({
            "id": f"persona:{p['id']}",
            "type": "personaNode",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": p.get("name", p["slug"]),
                "slug": p["slug"],
                "description": p.get("description", ""),
                "nodeClass": "persona",
                "node_type": "persona",
                "persona_id": p["id"],
                "persona_slug": p.get("slug"),
                "level": 0,
                "importance": 1.0,
                "color": nt_by_type.get("persona", {}).get("color", "#7c6fff"),
                "icon": nt_by_type.get("persona", {}).get("icon", "user"),
                "is_auxiliary": False,
                "validated": True,
                "in_focus_path": any(
                    step.get("node_type") == "persona" and step.get("node_id") in {
                        n.get("id") for n in sem_nodes if n.get("node_type") == "persona" and n.get("persona_id") == p["id"]
                    }
                    for step in focus_path
                ),
            },
        })
        persona_node_ids_emitted.add(p["id"])

    # ── Optional technical sources (ki:/kb:) ────────────────────────────
    ki_items: list[dict] = []
    kb_entries: list[dict] = []
    if include_technical:
        try:
            ki_items = supabase_client.get_knowledge_items(persona_id=single_persona_id, limit=500, offset=0) or []
        except Exception:
            ki_items = []
        try:
            kb_entries = supabase_client.get_kb_entries(persona_id=single_persona_id, status="") or []
        except Exception:
            kb_entries = []

        for item in ki_items:
            nid = f"ki:{item['id']}"
            persona_id = item.get("persona_id")
            node_class = _KI_STATUS.get(item.get("status", ""), "pending")
            content_type = item.get("content_type", "other")
            file_type = (item.get("file_type") or "").lower()
            nodes.append({
                "id": nid, "type": "knowledgeNode", "position": {"x": 0, "y": 0},
                "data": {
                    "label": item.get("title") or content_type,
                    "status": item.get("status", "pending"),
                    "content_type": content_type,
                    "file_type": file_type,
                    "file_path": item.get("file_path"),
                    "content_preview": (item.get("content") or "")[:200],
                    "nodeClass": node_class,
                    "item_id": item["id"],
                    "source": "queue",
                    "tags": item.get("tags") or [],
                    "node_type": "knowledge_item",
                    "level": nt_by_type.get("knowledge_item", {}).get("default_level", 95),
                    "importance": nt_by_type.get("knowledge_item", {}).get("default_importance", 0.40),
                    "color": nt_by_type.get("knowledge_item", {}).get("color", "#94a3b8"),
                    "icon": nt_by_type.get("knowledge_item", {}).get("icon", "inbox"),
                    "is_auxiliary": True,
                    "validated": node_class == "validated",
                },
            })
            if persona_id and persona_id in persona_node_ids_emitted:
                edges.append({
                    "id": f"e:ki-{persona_id}-{item['id']}",
                    "source": f"persona:{persona_id}", "target": nid, "type": "smoothstep",
                    "data": {"relation_type": "belongs_to_persona", "tier": "structural", "weight": 1.0, "directional": True},
                })

        for entry in kb_entries:
            nid = f"kb:{entry['id']}"
            persona_id = entry.get("persona_id")
            if persona_slug and (not persona_id or persona_id not in persona_id_set):
                continue
            node_class = _KB_STATUS.get(entry.get("status", ""), "pending")
            tipo = entry.get("tipo") or "kb"
            title = entry.get("titulo") or entry.get("produto") or entry.get("intencao") or tipo
            nodes.append({
                "id": nid, "type": "knowledgeNode", "position": {"x": 0, "y": 0},
                "data": {
                    "label": title,
                    "status": entry.get("status", "ATIVO"),
                    "content_type": tipo,
                    "file_type": "",
                    "file_path": entry.get("link"),
                    "content_preview": (entry.get("conteudo") or "")[:200],
                    "nodeClass": node_class,
                    "item_id": entry["id"],
                    "source": "vault",
                    "tags": entry.get("tags") or [],
                    "node_type": "kb_entry",
                    "level": nt_by_type.get("kb_entry", {}).get("default_level", 95),
                    "importance": nt_by_type.get("kb_entry", {}).get("default_importance", 0.50),
                    "color": nt_by_type.get("kb_entry", {}).get("color", "#94a3b8"),
                    "icon": nt_by_type.get("kb_entry", {}).get("icon", "database"),
                    "is_auxiliary": True,
                    "validated": node_class == "validated",
                },
            })
            if persona_id and persona_id in persona_node_ids_emitted:
                edges.append({
                    "id": f"e:kb-{persona_id}-{entry['id']}",
                    "source": f"persona:{persona_id}", "target": nid, "type": "smoothstep",
                    "data": {"relation_type": "belongs_to_persona", "tier": "structural", "weight": 1.0, "directional": True},
                })

    # ── Semantic graph (the actual knowledge nodes/edges) ───────────────
    semantic_nodes_count = 0
    semantic_edges_count = 0
    sem_node_ids = {n["id"]: n for n in sem_nodes}
    semantic_persona_aliases: dict[str, str] = {}
    semantic_embedded_aliases: dict[str, str] = {}

    for n in sem_nodes:
        ntype = (n.get("node_type") or "").lower()
        if ntype == "embedded":
            pid = n.get("persona_id") or single_persona_id
            if pid and pid in persona_node_ids_emitted:
                semantic_embedded_aliases[n["id"]] = f"embedded:{pid}"
            continue
        if ntype != "persona":
            continue
        pid = n.get("persona_id") or single_persona_id
        if pid and pid in persona_node_ids_emitted:
            semantic_persona_aliases[n["id"]] = f"persona:{pid}"

    for n in sem_nodes:
        ntype = (n.get("node_type") or "kb").lower()
        if ntype == "persona":
            # The UI already emits a stable persona root card with the real
            # filtered entity name. Skip semantic duplicates like "Persona".
            continue
        if ntype == "embedded":
            # The UI emits a stable Embedded destination card per persona.
            # Semantic embedded nodes are aliases for persisted edges only.
            continue
        meta = n.get("metadata") or {}
        tags = n.get("tags") or []
        nid = f"gn:{n['id']}"

        registry_row = nt_by_type.get(ntype, {})
        level = current_level_for(n["id"], ntype)
        importance = max(0.01, min(1.0, level / 99))
        confidence = n.get("confidence")
        is_auxiliary = ntype in _AUXILIARY_NODE_TYPES or (level or 0) >= 90

        # Map semantic node_type → ReactFlow nodeClass for legacy color/shape.
        node_class = {
            "persona": "persona",
            "product": "validated", "campaign": "validated", "brand": "validated",
            "entity": "validated", "asset": "validated", "faq": "validated",
            "copy": "validated", "briefing": "validated", "rule": "validated",
            "tone": "validated", "audience": "validated",
            "gallery": "validated", "embedded": "validated",
            "mention": "pending", "tag": "pending",
            "knowledge_item": "pending", "kb_entry": "validated",
        }.get(ntype, "pending")

        # focus highlights
        is_focus = bool(focus_node and n.get("id") == focus_node.get("id"))
        in_focus_path = any(step.get("node_id") == n.get("id") for step in focus_path)
        graph_distance = distance_map.get(n.get("id")) if focus_node else None

        nodes.append({
            "id": nid, "type": "knowledgeNode", "position": {"x": 0, "y": 0},
            "data": {
                "label": n.get("title") or n.get("slug") or ntype,
                "status": n.get("status") or "active",
                "content_type": ntype,
                "file_type": "",
                "file_path": meta.get("file_path"),
                "content_preview": (n.get("summary") or "")[:200],
                "nodeClass": node_class,
                "item_id": n.get("source_id") or n["id"],
                "source": "graph",
                "source_table": n.get("source_table"),
                "source_id": n.get("source_id"),
                "persona_id": n.get("persona_id"),
                "tags": tags,
                # Semantic decoration ────────
                "node_type": ntype,
                "slug": n.get("slug"),
                "level": level,
                "importance": importance,
                "confidence": confidence,
                "color": registry_row.get("color"),
                "icon": registry_row.get("icon"),
                "is_auxiliary": is_auxiliary,
                "validated": node_class == "validated",
                "is_focus": is_focus,
                "in_focus_path": in_focus_path,
                "graph_distance": graph_distance,
                "protected": bool(meta.get("protected") or ntype in {"persona", "embedded", "gallery"}),
                "metadata": meta,
                # Pass through legacy fields for backwards-compat with sidebar
                "asset_type": meta.get("asset_type"),
                "asset_function": meta.get("asset_function"),
                "campaign": (n.get("slug") if ntype == "campaign" else None),
                "product":  (n.get("slug") if ntype == "product"  else None),
            },
        })
        semantic_nodes_count += 1

    # Wire semantic edges between semantic nodes.
    focus_path_pairs: set[tuple[str, str]] = set()
    if len(focus_path) >= 2:
        for prev, nxt in zip(focus_path, focus_path[1:]):
            a, b = prev.get("node_id"), nxt.get("node_id")
            if a and b:
                focus_path_pairs.add((a, b))
                focus_path_pairs.add((b, a))

    for e in sem_edges:
        src = sem_node_ids.get(e.get("source_node_id"))
        tgt = sem_node_ids.get(e.get("target_node_id"))
        if not src or not tgt:
            continue
        source_id = (
            semantic_persona_aliases.get(e.get("source_node_id"))
            or semantic_embedded_aliases.get(e.get("source_node_id"))
            or f"gn:{e['source_node_id']}"
        )
        target_id = (
            semantic_persona_aliases.get(e.get("target_node_id"))
            or semantic_embedded_aliases.get(e.get("target_node_id"))
            or f"gn:{e['target_node_id']}"
        )
        if source_id == target_id:
            continue
        rt = (e.get("relation_type") or "related").lower()
        registry_rel = rt_by_type.get(rt, {})
        weight = e.get("weight")
        if weight is None:
            weight = registry_rel.get("default_weight", 0.50)
        directional = registry_rel.get("directional", True)
        tier = _classify_relation_tier(rt, weight)
        in_path = (e.get("source_node_id"), e.get("target_node_id")) in focus_path_pairs

        edges.append({
            "id": f"ge:{e['id']}",
            "source": source_id,
            "target": target_id,
            "type": "smoothstep",
            "data": {
                "relation_type": rt,
                "tier": tier,
                "weight": weight,
                "directional": directional,
                "in_focus_path": in_path,
                "label": registry_rel.get("label"),
                "original_edge_id": f"ge:{e['id']}",
                "deletable": True,
                "metadata": e.get("metadata") or {},
                "primary_tree": bool((e.get("metadata") or {}).get("primary_tree")),
                "gallery_edge": rt == "gallery_asset",
            },
        })
        semantic_edges_count += 1

    if include_embedded:
        embedded_persona_ids = [
            p["id"]
            for p in personas
            if p.get("id") in persona_node_ids_emitted
        ]
        for persona_id in embedded_persona_ids:
            embedded_id = f"embedded:{persona_id}"
            nodes.append({
                "id": embedded_id,
                "type": "knowledgeNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "Embedded",
                    "status": "active",
                    "content_type": "rag",
                    "content_preview": "Fonte de conhecimento enviada ao RAG do modelo.",
                    "nodeClass": "validated",
                    "source": "synthetic",
                    "tags": ["rag", "embedded", "default"],
                    "node_type": "embedded",
                    "slug": "embedded-default",
                    "level": 120,
                    "importance": 0.78,
                    "confidence": 1,
                    "color": "#ffffff",
                    "icon": "database",
                    "is_auxiliary": False,
                    "validated": True,
                    "persona_id": persona_id,
                    "rag_index": "default",
                },
            })

    # ── Orphan root for ki:/kb: items without persona ────────────────
    has_orphans = any(e.get("source") == "orphan" for e in edges)
    if has_orphans:
        nodes.insert(0, {
            "id": "orphan", "type": "personaNode", "position": {"x": 0, "y": 0},
            "data": {
                "label": "Sem Persona", "slug": "_orphan",
                "description": "Itens ainda não atribuídos",
                "nodeClass": "orphan",
                "node_type": "persona", "level": 0, "importance": 0.5,
                "color": "#475569", "icon": "user", "is_auxiliary": False,
                "validated": False,
            },
        })

    total_items = len(ki_items) + len(kb_entries)

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total_personas": len(personas),
            "total_items": total_items,
            "ki_items": len(ki_items),
            "kb_entries": len(kb_entries),
            "semantic_nodes": semantic_nodes_count,
            "semantic_edges": semantic_edges_count,
            "focus": (
                {
                    "node_id": focus_node["id"],
                    "node_type": focus_node.get("node_type"),
                    "slug": focus_node.get("slug"),
                    "title": focus_node.get("title"),
                }
                if focus_node else None
            ),
            "focus_path": focus_path,
            "applied_filters": {
                "max_depth": max_depth,
                "include_tags": include_tags,
                "include_mentions": include_mentions,
                "include_technical": include_technical,
                "include_embedded": include_embedded,
                "mode": mode,
                "persona_slug": persona_slug,
            },
            "registry": {
                "node_types": [
                    {
                        "node_type": r["node_type"],
                        "label": r.get("label"),
                        "level": r.get("default_level"),
                        "importance": r.get("default_importance"),
                        "color": r.get("color"),
                        "icon": r.get("icon"),
                        "sort_order": r.get("sort_order"),
                    }
                    for r in node_type_registry
                ],
                "relations": [
                    {
                        "relation_type": r["relation_type"],
                        "label": r.get("label"),
                        "inverse_label": r.get("inverse_label"),
                        "weight": r.get("default_weight"),
                        "directional": r.get("directional"),
                        "tier": _classify_relation_tier(r["relation_type"], r.get("default_weight") or 0),
                        "sort_order": r.get("sort_order"),
                    }
                    for r in relation_type_registry
                ],
            },
        },
    }
