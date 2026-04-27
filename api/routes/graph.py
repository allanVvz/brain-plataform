# -*- coding: utf-8 -*-
"""Graph data endpoint — returns ReactFlow-compatible nodes and edges."""

from fastapi import APIRouter, Query
from typing import Optional
from services import supabase_client

router = APIRouter(prefix="/knowledge", tags=["graph"])

_STATUS_COLOR = {
    "approved": "validated",
    "embedded": "validated",
    "pending": "pending",
    "needs_persona": "pending",
    "needs_category": "pending",
    "rejected": "rejected",
}


@router.get("/graph-data")
def get_graph_data(persona_slug: Optional[str] = Query(None)):
    personas = supabase_client.get_personas()
    if persona_slug:
        personas = [p for p in personas if p["slug"] == persona_slug]

    # Build persona_id → persona lookup
    persona_map = {p["id"]: p for p in personas}
    persona_id_set = set(persona_map.keys())

    # Fetch all knowledge items (up to 500)
    items = supabase_client.get_knowledge_items(limit=500, offset=0)

    nodes: list[dict] = []
    edges: list[dict] = []

    # Persona root nodes
    for i, p in enumerate(personas):
        nodes.append({
            "id": f"persona:{p['id']}",
            "type": "personaNode",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": p.get("name", p["slug"]),
                "slug": p["slug"],
                "description": p.get("description", ""),
                "nodeClass": "persona",
            },
        })

    # Knowledge item nodes + edges
    for item in items:
        persona_id = item.get("persona_id")
        status = item.get("status", "pending")
        node_class = _STATUS_COLOR.get(status, "pending")
        content_type = item.get("content_type", "other")
        file_type = (item.get("file_type") or "").lower()

        nodes.append({
            "id": f"ki:{item['id']}",
            "type": "knowledgeNode",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": item.get("title") or content_type,
                "status": status,
                "content_type": content_type,
                "file_type": file_type,
                "file_path": item.get("file_path"),
                "content_preview": (item.get("content") or "")[:200],
                "nodeClass": node_class,
                "item_id": item["id"],
            },
        })

        if persona_id and persona_id in persona_id_set:
            edges.append({
                "id": f"e:{persona_id}-{item['id']}",
                "source": f"persona:{persona_id}",
                "target": f"ki:{item['id']}",
                "type": "smoothstep",
            })
        else:
            # Orphan — connect to a virtual "unassigned" node
            edges.append({
                "id": f"e:unassigned-{item['id']}",
                "source": "orphan",
                "target": f"ki:{item['id']}",
                "type": "smoothstep",
            })

    # Add orphan root node if needed
    has_orphans = any(e["source"] == "orphan" for e in edges)
    if has_orphans:
        nodes.insert(0, {
            "id": "orphan",
            "type": "personaNode",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "Sem Persona",
                "slug": "_orphan",
                "description": "Itens ainda não atribuídos",
                "nodeClass": "orphan",
            },
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total_personas": len(personas),
            "total_items": len(items),
        },
    }
