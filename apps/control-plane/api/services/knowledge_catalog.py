"""Read-only Golden Dataset projection from the active GraphBundle v3."""
from __future__ import annotations

from collections import Counter
from typing import Any

from services import supabase_client


CATEGORY_ORDER = (
    ("faqs", "FAQs", {"faq"}),
    ("rules_tone", "Regras e Tom", {"rule", "tone"}),
    ("products", "Produtos e Grupos", {"product", "product_group"}),
    ("campaigns", "Campanhas e Públicos", {"campaign", "audience"}),
    ("brand_briefing", "Marca e Briefing", {"persona", "brand", "briefing"}),
    ("copies", "Copies", {"copy"}),
    ("assets", "Assets", {"asset"}),
)


def _node_path(document: dict[str, Any], node: dict[str, Any]) -> list[dict[str, str]]:
    by_id = document.get("node_by_id") or {
        str(item.get("id")): item for item in document.get("nodes") or []
    }
    coordinate = (document.get("coordinates") or {}).get(str(node.get("id"))) or {}
    ids = coordinate.get("path_node_ids") or [node.get("id")]
    return [
        {
            "id": str(item.get("id") or ""),
            "type": str(item.get("node_type") or ""),
            "slug": str(item.get("slug") or ""),
            "title": str(item.get("title") or item.get("slug") or ""),
        }
        for node_id in ids
        if isinstance((item := by_id.get(str(node_id))), dict)
    ]


def project_publication(publication: dict[str, Any], *, persona_name: str | None = None) -> dict[str, Any]:
    if publication.get("status") != "active":
        raise ValueError("active_graph_publication_v3_required")
    document = publication.get("document_json") or {}
    if document.get("schema_version") != "3.0":
        raise ValueError("active_graph_publication_v3_required")
    nodes = [item for item in document.get("nodes") or [] if isinstance(item, dict)]
    edges = [item for item in document.get("edges") or [] if isinstance(item, dict)]
    embedded = next(
        (node for node in nodes if str(node.get("node_type") or "").lower() in {"embed", "embedded"}),
        None,
    )
    embedded_id = str((embedded or {}).get("id") or "")
    embedded_faq_ids = {
        str(edge.get("source") or "") for edge in edges
        if edge.get("target") == embedded_id
        and edge.get("relation_type") == "publishes_to"
        and (edge.get("metadata") or {}).get("active", True) is not False
    }
    documents: list[dict[str, Any]] = []
    for node in nodes:
        if str(node.get("node_type") or "").lower() in {"embed", "embedded", "gallery"}:
            continue
        data = node.get("data") or {}
        path = _node_path(document, node)
        node_type = str(node.get("node_type") or "")
        documents.append({
            "id": str(node.get("id") or ""),
            "projection_node_id": node.get("projection_node_id"),
            "node_type": node_type,
            "slug": str(node.get("slug") or ""),
            "title": str(node.get("title") or ""),
            "markdown": str(data.get("answer") or data.get("content") or node.get("summary") or ""),
            "status": str(node.get("status") or "pending_validation"),
            "source": data.get("source") or "pending_source",
            "path": path,
            "path_label": " › ".join(item["title"] for item in path),
            "faq_count": 1 if node_type == "faq" else 0,
            "embedded": str(node.get("id") or "") in embedded_faq_ids,
            "metadata": {
                "graph_node_id": str(node.get("id") or ""),
                "publication_id": publication.get("id"),
                "publication_checksum": publication.get("checksum"),
            },
        })
    categories = [
        {
            "key": key, "label": label,
            "count": len(rows := [row for row in documents if row["node_type"] in node_types]),
            "items": rows,
        }
        for key, label, node_types in CATEGORY_ORDER
    ]
    persona = document.get("persona") or {}
    return {
        "persona": {
            "id": persona.get("id"), "slug": persona.get("slug"),
            "name": persona_name or persona.get("name") or persona.get("slug"),
        },
        "graph": {
            "id": publication.get("id"), "publication_id": publication.get("id"),
            "version": publication.get("version"), "checksum": publication.get("checksum"),
            "status": "active", "node_count": len(nodes), "edge_count": len(edges),
            "document_count": len(documents),
        },
        "categories": categories,
        "documents": documents,
        "status_counts": dict(Counter(row["status"] for row in documents)),
        "embedded": {
            "node_id": embedded_id or None,
            "status": str((embedded or {}).get("status") or "missing"),
            "faq_count": len(embedded_faq_ids),
            "faq_node_ids": sorted(embedded_faq_ids),
        },
    }


def load_catalog(
    *, persona_slug: str, persona_id: str | None = None,
    persona_name: str | None = None,
) -> dict[str, Any] | None:
    if not persona_id:
        persona = supabase_client.get_persona(persona_slug)
        persona_id = str((persona or {}).get("id") or "")
    if not persona_id:
        return None
    publication = supabase_client.get_active_graph_publication(persona_id)
    if not publication or publication.get("status") != "active":
        return None
    return project_publication(publication, persona_name=persona_name)
