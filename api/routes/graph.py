# -*- coding: utf-8 -*-
"""Graph data endpoint — returns ReactFlow-compatible nodes and edges."""

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


@router.get("/graph-data")
def get_graph_data(persona_slug: Optional[str] = Query(None)):
    personas = supabase_client.get_personas()
    if persona_slug:
        personas = [p for p in personas if p["slug"] == persona_slug]

    persona_map = {p["id"]: p for p in personas}
    persona_id_set = set(persona_map.keys())

    # When filtered to a single persona, pass its id to avoid fetching everything
    single_persona_id: str | None = None
    if persona_slug and len(personas) == 1:
        single_persona_id = personas[0]["id"]

    ki_items   = supabase_client.get_knowledge_items(persona_id=single_persona_id, limit=500, offset=0)
    kb_entries = supabase_client.get_kb_entries(persona_id=single_persona_id, status="")   # all statuses

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()

    # ── Persona root nodes ─────────────────────────────────────────
    for p in personas:
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

    # ── knowledge_items nodes ──────────────────────────────────────
    for item in ki_items:
        nid = f"ki:{item['id']}"
        seen_ids.add(nid)
        persona_id = item.get("persona_id")
        node_class = _KI_STATUS.get(item.get("status", ""), "pending")
        content_type = item.get("content_type", "other")
        file_type = (item.get("file_type") or "").lower()

        nodes.append({
            "id": nid,
            "type": "knowledgeNode",
            "position": {"x": 0, "y": 0},
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
            },
        })

        if persona_id and persona_id in persona_id_set:
            edges.append({
                "id": f"e:ki-{persona_id}-{item['id']}",
                "source": f"persona:{persona_id}",
                "target": nid,
                "type": "smoothstep",
            })
        else:
            edges.append({
                "id": f"e:ki-orphan-{item['id']}",
                "source": "orphan",
                "target": nid,
                "type": "smoothstep",
            })

    # ── kb_entries nodes (vault-synced active KB) ──────────────────
    for entry in kb_entries:
        nid = f"kb:{entry['id']}"
        persona_id = entry.get("persona_id")

        # Skip if this persona is filtered out
        if persona_slug and (not persona_id or persona_id not in persona_id_set):
            continue

        node_class = _KB_STATUS.get(entry.get("status", ""), "pending")
        tipo = entry.get("tipo") or "kb"
        title = entry.get("titulo") or entry.get("produto") or entry.get("intencao") or tipo

        nodes.append({
            "id": nid,
            "type": "knowledgeNode",
            "position": {"x": 0, "y": 0},
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
            },
        })

        if persona_id and persona_id in persona_id_set:
            edges.append({
                "id": f"e:kb-{persona_id}-{entry['id']}",
                "source": f"persona:{persona_id}",
                "target": nid,
                "type": "smoothstep",
            })
        else:
            edges.append({
                "id": f"e:kb-orphan-{entry['id']}",
                "source": "orphan",
                "target": nid,
                "type": "smoothstep",
            })

    # ── Orphan root node (if any unassigned items exist) ──────────
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

    total_items = len(ki_items) + len(kb_entries)

    # ── Semantic graph (knowledge_nodes/edges from migration 008) ─────────
    # Aditivo: se a tabela estiver vazia ou ausente, o grafo antigo segue
    # idêntico. Quando houver dados, anexamos nodes "gn:" e edges "ge:".
    semantic_nodes_count = 0
    semantic_edges_count = 0
    try:
        sem_nodes, sem_edges = supabase_client.list_all_knowledge_graph(
            persona_id=single_persona_id, limit_nodes=1500,
        )
    except Exception:
        sem_nodes, sem_edges = [], []

    if sem_nodes:
        # Index by id for edge mapping.
        sem_node_ids = {n["id"]: n for n in sem_nodes}
        for n in sem_nodes:
            ntype = (n.get("node_type") or "kb").lower()
            meta = n.get("metadata") or {}
            tags = n.get("tags") or []
            persona_id = n.get("persona_id")
            # Map semantic node_type → ReactFlow nodeClass for color/shape.
            node_class = {
                "persona": "persona",
                "product": "validated",
                "campaign": "validated",
                "brand": "validated",
                "entity": "validated",
                "asset": "validated",
                "faq": "validated",
                "copy": "validated",
                "briefing": "validated",
                "rule": "validated",
                "tone": "validated",
                "audience": "validated",
                "mention": "pending",
                "tag": "pending",
                "knowledge_item": "pending",
                "kb_entry": "validated",
            }.get(ntype, "pending")

            nid = f"gn:{n['id']}"
            nodes.append({
                "id": nid,
                "type": "knowledgeNode",
                "position": {"x": 0, "y": 0},
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
                    # New optional fields per spec:
                    "node_type": ntype,
                    "asset_type": meta.get("asset_type"),
                    "asset_function": meta.get("asset_function"),
                    "campaign": (n.get("slug") if ntype == "campaign" else None),
                    "product":  (n.get("slug") if ntype == "product"  else None),
                },
            })
            semantic_nodes_count += 1

            # Hang the node from its persona root when applicable.
            if persona_id and persona_id in persona_id_set and ntype != "persona":
                edges.append({
                    "id": f"ge:p{persona_id}-{n['id']}",
                    "source": f"persona:{persona_id}",
                    "target": nid,
                    "type": "smoothstep",
                    "data": {"relation_type": "belongs_to_persona"},
                })

        # Wire semantic edges between semantic nodes.
        for e in sem_edges:
            src = sem_node_ids.get(e.get("source_node_id"))
            tgt = sem_node_ids.get(e.get("target_node_id"))
            if not src or not tgt:
                continue
            edges.append({
                "id": f"ge:{e['id']}",
                "source": f"gn:{e['source_node_id']}",
                "target": f"gn:{e['target_node_id']}",
                "type": "smoothstep",
                "data": {"relation_type": e.get("relation_type")},
            })
            semantic_edges_count += 1

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
        },
    }
