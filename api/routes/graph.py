# -*- coding: utf-8 -*-
"""Graph data endpoint — returns ReactFlow-compatible nodes and edges.

The payload is decorated with semantic level/importance/tier/weight pulled
from knowledge_node_type_registry + knowledge_relation_type_registry
(migration 009) so the frontend can render a layered, hierarchical graph
without re-deriving the ontology in JS.
"""

from collections import deque
from fastapi import APIRouter, Query
from typing import Optional

from services import supabase_client

router = APIRouter(prefix="/knowledge", tags=["graph"])

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
_STRUCTURAL_RELATIONS: set[str] = {"belongs_to_persona", "derived_from", "contains"}
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


@router.get("/graph-data")
def get_graph_data(
    persona_slug: Optional[str] = Query(None),
    focus: Optional[str] = Query(None, description="<node_type>:<slug> or node_id"),
    max_depth: int = Query(3, ge=1, le=6, description="BFS depth from focus (or persona root)"),
    include_tags: bool = Query(False),
    include_mentions: bool = Query(False),
    include_technical: bool = Query(False, description="Include knowledge_items + kb_entries duplicate sources"),
    mode: str = Query("layered", description="layered|semantic_tree|graph (frontend hint only)"),
):
    personas = supabase_client.get_personas()
    if persona_slug:
        personas = [p for p in personas if p["slug"] == persona_slug]

    persona_map = {p["id"]: p for p in personas}
    persona_id_set = set(persona_map.keys())

    single_persona_id: Optional[str] = None
    if persona_slug and len(personas) == 1:
        single_persona_id = personas[0]["id"]

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

    surviving_ids = {n["id"] for n in sem_nodes}
    sem_edges = [
        e for e in sem_edges
        if e.get("source_node_id") in surviving_ids and e.get("target_node_id") in surviving_ids
    ]

    # ── Optional: focus subgraph (BFS) ──────────────────────────────────
    focus_node = _resolve_focus(focus, single_persona_id) if focus else None
    focus_path: list[dict] = []
    if focus_node:
        nodes_by_id_raw = {n["id"]: n for n in sem_nodes}
        if focus_node["id"] not in nodes_by_id_raw:
            # Add it back if it was filtered out by include_*
            sem_nodes.append(focus_node)
            nodes_by_id_raw[focus_node["id"]] = focus_node
        reachable, distance_map, predecessor = _bfs_focus_subgraph(
            focus_node["id"], sem_nodes, sem_edges, max_depth=max_depth,
        )
        sem_nodes = [n for n in sem_nodes if n["id"] in reachable]
        sem_edges = [
            e for e in sem_edges
            if e.get("source_node_id") in reachable and e.get("target_node_id") in reachable
        ]
        # Find persona root id for path resolution
        persona_root_id: Optional[str] = None
        for n in sem_nodes:
            if n.get("node_type") == "persona" and (n.get("persona_id") in persona_id_set or n.get("slug") == "self"):
                persona_root_id = n["id"]
                break
        nodes_by_id = {n["id"]: n for n in sem_nodes}
        focus_path = _build_focus_path(focus_node["id"], persona_root_id, nodes_by_id, predecessor)
    else:
        distance_map = {}

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
                "level": 0,
                "importance": 1.0,
                "color": nt_by_type.get("persona", {}).get("color", "#7c6fff"),
                "icon": nt_by_type.get("persona", {}).get("icon", "user"),
                "is_auxiliary": False,
                "validated": True,
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

    for n in sem_nodes:
        ntype = (n.get("node_type") or "kb").lower()
        meta = n.get("metadata") or {}
        tags = n.get("tags") or []
        nid = f"gn:{n['id']}"

        registry_row = nt_by_type.get(ntype, {})
        # importance: prefer per-row override (009 added column to knowledge_nodes), else registry default
        importance = n.get("importance")
        if importance is None:
            importance = registry_row.get("default_importance", 0.50)
        level = n.get("level")
        if level is None:
            level = registry_row.get("default_level", 50)
        confidence = n.get("confidence")
        is_auxiliary = ntype in _AUXILIARY_NODE_TYPES or (level or 0) >= 90

        # Map semantic node_type → ReactFlow nodeClass for legacy color/shape.
        node_class = {
            "persona": "persona",
            "product": "validated", "campaign": "validated", "brand": "validated",
            "entity": "validated", "asset": "validated", "faq": "validated",
            "copy": "validated", "briefing": "validated", "rule": "validated",
            "tone": "validated", "audience": "validated",
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
            "source": f"gn:{e['source_node_id']}",
            "target": f"gn:{e['target_node_id']}",
            "type": "smoothstep",
            "data": {
                "relation_type": rt,
                "tier": tier,
                "weight": weight,
                "directional": directional,
                "in_focus_path": in_path,
                "label": registry_rel.get("label"),
            },
        })
        semantic_edges_count += 1

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
