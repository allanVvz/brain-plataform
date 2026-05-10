from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from services import knowledge_graph, supabase_client


STRUCTURAL_RELATIONS = {
    "belongs_to_persona",
    "contains",
    "part_of_campaign",
    "about_product",
    "offers_product",
    "briefed_by",
    "answers_question",
    "supports_copy",
    "uses_asset",
    "manual",
}


def _slugify(value: str) -> str:
    return knowledge_graph._slugify(value or "")


def _active_edge(edge: dict) -> bool:
    return (edge.get("metadata") or {}).get("active") is not False


def _is_structural(edge: dict) -> bool:
    meta = edge.get("metadata") or {}
    relation = (edge.get("relation_type") or "").lower()
    return _active_edge(edge) and meta.get("primary_tree") is True and relation in STRUCTURAL_RELATIONS


def _node_context(node: Optional[dict]) -> dict:
    if not node:
        return {}
    meta = node.get("metadata") or {}
    return {
        "id": node.get("id"),
        "node_type": node.get("node_type"),
        "slug": node.get("slug"),
        "title": node.get("title"),
        "summary": node.get("summary"),
        "tags": node.get("tags") or [],
        "metadata": meta,
    }


def _first_by_type(chain: list[dict], node_type: str) -> Optional[dict]:
    for node in chain:
        if (node.get("node_type") or "").lower() == node_type:
            return node
    return None


def _faq_parts(node: dict, item: Optional[dict]) -> tuple[str, str]:
    meta = node.get("metadata") or {}
    question = meta.get("question") or node.get("title") or ""
    answer = meta.get("answer") or ""
    text = (item or {}).get("content") or node.get("summary") or ""
    pairs = knowledge_graph._extract_faq_pairs(text)
    if pairs:
        question = question or pairs[0][0]
        answer = answer or pairs[0][1]
    if not answer:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 2 and "?" in lines[0]:
            question = question or lines[0]
            answer = " ".join(lines[1:])
    return question.strip(), answer.strip()


def _text_context(node: Optional[dict]) -> str:
    if not node:
        return ""
    return str(node.get("summary") or node.get("title") or "").strip()


def _metadata_list(*values) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(str(v).strip() for v in value if str(v).strip())
        elif isinstance(value, str) and value.strip():
            out.append(value.strip())
    return list(dict.fromkeys(out))


def _build_hierarchy(source_node: dict) -> tuple[list[dict], list[dict]]:
    persona_id = source_node.get("persona_id")
    nodes, edges = supabase_client.list_all_knowledge_graph(persona_id=persona_id, limit_nodes=2500)
    nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    persona_node_ids = {n.get("id") for n in nodes if (n.get("node_type") or "").lower() == "persona"}
    auxiliary_types = {"tag", "mention", "embedded", "gallery"}
    parent_by_child: dict[str, tuple[str, dict]] = {}
    for edge in edges:
        if not _is_structural(edge):
            continue
        src = edge.get("source_node_id")
        tgt = edge.get("target_node_id")
        if not src or not tgt:
            continue
        src_node = nodes_by_id.get(src) or {}
        tgt_node = nodes_by_id.get(tgt) or {}
        src_type = (src_node.get("node_type") or "").lower()
        tgt_type = (tgt_node.get("node_type") or "").lower()
        if src_type in auxiliary_types or tgt_type in auxiliary_types:
            continue
        if tgt in persona_node_ids:
            continue
        if src == tgt:
            continue
        if tgt not in parent_by_child:
            parent_by_child[tgt] = (src, edge)

    # Metadata resolved by apply_plan_hierarchy is a strong fallback for legacy
    # rows where persona fallback edges are still active or plan edges were
    # accidentally soft-deleted.
    for node in nodes:
        node_id = node.get("id")
        meta = node.get("metadata") or {}
        parent_id = meta.get("resolved_parent_node_id") or meta.get("parent_node_id")
        if not node_id or not parent_id or parent_id == node_id:
            continue
        parent = nodes_by_id.get(parent_id)
        if not parent:
            continue
        if (node.get("node_type") or "").lower() in auxiliary_types:
            continue
        if (parent.get("node_type") or "").lower() in auxiliary_types:
            continue
        parent_by_child[node_id] = (parent_id, {
            "id": None,
            "source_node_id": parent_id,
            "target_node_id": node_id,
            "relation_type": "resolved_parent",
            "metadata": {"primary_tree": True, "active": True, "created_from": "resolved_parent_node_id"},
        })

    source_id = source_node.get("id")
    chain_reversed: list[dict] = []
    path_edges_reversed: list[dict] = []
    seen: set[str] = set()
    current_id = source_id
    while current_id and current_id not in seen:
        seen.add(current_id)
        node = nodes_by_id.get(current_id) or (source_node if current_id == source_id else None)
        if not node:
            break
        if (node.get("node_type") or "").lower() in auxiliary_types:
            break
        chain_reversed.append(node)
        parent = parent_by_child.get(current_id)
        if not parent:
            break
        parent_id, edge = parent
        if parent_id in seen:
            break
        path_edges_reversed.append(edge)
        current_id = parent_id

    chain = list(reversed(chain_reversed))
    path_edges = list(reversed(path_edges_reversed))
    if not chain or chain[-1].get("id") != source_id:
        chain.append(source_node)
    persona_positions = [idx for idx, node in enumerate(chain) if (node.get("node_type") or "").lower() == "persona"]
    if len(persona_positions) > 1 or (persona_positions and persona_positions[0] != 0):
        raise RuntimeError("Invalid hierarchy cycle: persona appears outside root position")
    return chain, path_edges


def _has_type_in_persona(nodes: list[dict], node_type: str) -> bool:
    return any((node.get("node_type") or "").lower() == node_type for node in nodes)


def _validate_faq_context(
    *,
    source_node: dict,
    chain: list[dict],
    question: str,
    answer: str,
    product: Optional[dict],
    briefing: Optional[dict],
    audience: Optional[dict],
) -> None:
    if not question or not answer:
        raise RuntimeError("FAQ approved, but question/answer is incomplete")
    if not product:
        raise RuntimeError("FAQ approved, but product context is missing")
    persona_id = source_node.get("persona_id")
    try:
        nodes, _ = supabase_client.list_all_knowledge_graph(persona_id=persona_id, limit_nodes=2500)
    except Exception:
        nodes = []
    has_briefing = _has_type_in_persona(nodes, "briefing")
    has_audience = _has_type_in_persona(nodes, "audience")
    if has_briefing and not briefing:
        raise RuntimeError("FAQ approved, but briefing context exists in graph and was not resolved")
    if has_audience and not audience:
        raise RuntimeError("FAQ approved, but audience context exists in graph and was not resolved")


def _hierarchy_path(chain: list[dict]) -> list[dict]:
    return [
        {
            "node_id": node.get("id"),
            "node_type": node.get("node_type"),
            "slug": node.get("slug"),
            "title": node.get("title"),
        }
        for node in chain
    ]


def _canonical_key(persona: dict, content_type: str, chain: list[dict], slug: str) -> str:
    persona_slug = _slugify(persona.get("slug") or persona.get("name") or "persona")
    hierarchy = [
        _slugify(node.get("slug") or node.get("title") or "")
        for node in chain
        if (node.get("node_type") or "").lower() not in {"persona", content_type}
    ]
    hierarchy = [part for part in hierarchy if part and part != "self"]
    parts = [persona_slug, content_type, *hierarchy, slug]
    return "/".join(part for part in parts if part)


def _approved_markdown(
    *,
    title: str,
    content_type: str,
    hierarchy_summary: str,
    brand: Optional[dict],
    briefing: Optional[dict],
    campaign: Optional[dict],
    audience: Optional[dict],
    product: Optional[dict],
    question: str,
    answer: str,
    source_text: str,
) -> str:
    lines = [f"# {title}", "", f"Tipo: {content_type}", f"Hierarquia: {hierarchy_summary}"]
    for label, node in [
        ("Marca", brand),
        ("Briefing", briefing),
        ("Campanha", campaign),
        ("Publico", audience),
        ("Produto", product),
    ]:
        value = _text_context(node)
        if value:
            lines.append(f"{label}: {value}")
    if content_type == "faq":
        lines.extend(["", f"Pergunta: {question}", f"Resposta aprovada: {answer}"])
    elif source_text:
        lines.extend(["", source_text.strip()])
    return "\n".join(lines).strip()


def _faq_chunk_text(
    *,
    brand: Optional[dict],
    briefing: Optional[dict],
    campaign: Optional[dict],
    audience: Optional[dict],
    product: Optional[dict],
    question: str,
    answer: str,
    rules: list[str],
    tone: str,
) -> str:
    lines = [
        f"Marca: {_text_context(brand) or 'Nao informado.'}",
        f"Briefing: {_text_context(briefing) or 'Nao informado.'}",
        f"Publico: {_text_context(audience) or 'Nao informado.'}",
        f"Produto: {_text_context(product) or 'Nao informado.'}",
    ]
    campaign_text = _text_context(campaign)
    if campaign_text:
        lines.append(f"Campanha: {campaign_text}")
    lines.extend([
        f"Pergunta: {question}",
        f"Resposta aprovada: {answer}",
        f"Regras: {' '.join(rules) if rules else 'Nao informado.'}",
        f"Tom: {tone or 'Nao informado.'}",
    ])
    return "\n".join(lines)


def _source_item_for_node(node: dict) -> Optional[dict]:
    if node.get("source_table") == "knowledge_items" and node.get("source_id"):
        try:
            return supabase_client.get_knowledge_item(str(node.get("source_id")))
        except Exception:
            return None
    return None


def publish_approved_node(
    source_node_id: str,
    *,
    approved_by: Optional[str] = None,
    require_rag_for_faq: bool = True,
) -> dict:
    """Create the canonical approved snapshot and RAG rows for an approved node."""
    source_node = supabase_client.get_knowledge_node(source_node_id)
    if not source_node:
        raise ValueError("Source knowledge node not found")
    if (source_node.get("node_type") or "").lower() == "mention":
        raise ValueError("Mention nodes cannot be published as approved canonical knowledge")
    persona_id = source_node.get("persona_id")
    if not persona_id:
        raise ValueError("Source knowledge node must have persona_id")
    persona = supabase_client.get_persona_by_id(persona_id) or {"id": persona_id, "slug": persona_id}
    source_item = _source_item_for_node(source_node)
    content_type = (source_node.get("node_type") or (source_item or {}).get("content_type") or "general_note").lower()
    title = source_node.get("title") or (source_item or {}).get("title") or content_type
    slug = _slugify(source_node.get("slug") or title)
    source_text = (source_item or {}).get("content") or source_node.get("summary") or ""
    question, answer = _faq_parts(source_node, source_item) if content_type == "faq" else ("", "")
    if content_type == "faq" and not answer:
        answer = source_text.strip()

    chain, path_edges = _build_hierarchy(source_node)
    if chain and chain[0].get("node_type") != "persona":
        persona_root = knowledge_graph._ensure_persona_root(persona_id)
        if persona_root:
            chain.insert(0, persona_root)
    root_node = chain[0] if chain else source_node
    parent_node = chain[-2] if len(chain) >= 2 else None
    brand = _first_by_type(chain, "brand")
    briefing = _first_by_type(chain, "briefing")
    campaign = _first_by_type(chain, "campaign")
    audience = _first_by_type(chain, "audience")
    product = _first_by_type(chain, "product")
    faq = source_node if content_type == "faq" else _first_by_type(chain, "faq")
    if content_type == "faq":
        _validate_faq_context(
            source_node=source_node,
            chain=chain,
            question=question,
            answer=answer,
            product=product,
            briefing=briefing,
            audience=audience,
        )

    source_meta = source_node.get("metadata") or {}
    rules = _metadata_list(source_meta.get("rules"), source_meta.get("restrictions"))
    tone = str(source_meta.get("tone") or source_meta.get("voice") or "").strip()
    hierarchy_path = _hierarchy_path(chain)
    hierarchy_summary = " -> ".join(
        f"{step.get('node_type')}:{step.get('slug') or step.get('title')}"
        for step in hierarchy_path
    )
    canonical_key = _canonical_key(persona, content_type, chain, slug)
    approved_summary = answer[:500] if content_type == "faq" and answer else (source_node.get("summary") or source_text or title)[:500]
    approved_markdown = _approved_markdown(
        title=title,
        content_type=content_type,
        hierarchy_summary=hierarchy_summary,
        brand=brand,
        briefing=briefing,
        campaign=campaign,
        audience=audience,
        product=product,
        question=question,
        answer=answer,
        source_text=source_text,
    )
    content_hash = hashlib.sha256(approved_markdown.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()

    snapshot = supabase_client.upsert_approved_knowledge_snapshot({
        "persona_id": persona_id,
        "root_node_id": root_node.get("id"),
        "source_node_id": source_node.get("id"),
        "source_table": source_node.get("source_table") or "knowledge_nodes",
        "source_id": source_node.get("source_id") or source_node.get("id"),
        "artifact_id": source_node.get("artifact_id") or source_meta.get("artifact_id"),
        "content_type": content_type,
        "title": title,
        "slug": slug,
        "canonical_key": canonical_key,
        "content_hash": content_hash,
        "hierarchy_path": hierarchy_path,
        "hierarchy_summary": hierarchy_summary,
        "approved_summary": approved_summary,
        "approved_markdown": approved_markdown,
        "parent_context": _node_context(parent_node),
        "brand_context": _node_context(brand),
        "briefing_context": _node_context(briefing),
        "campaign_context": _node_context(campaign),
        "audience_context": _node_context(audience),
        "product_context": _node_context(product),
        "faq_context": {
            **_node_context(faq),
            "question": question,
            "answer": answer,
        } if faq else {},
        "status": "approved",
        "approved_by": approved_by,
        "approved_at": now_iso,
        "metadata": {
            "source": "graph_approval",
            "source_node_id": source_node.get("id"),
            "source_knowledge_item_id": (source_item or {}).get("id"),
            "n8n_ready": content_type == "faq",
        },
    })
    if not snapshot or not snapshot.get("id"):
        raise RuntimeError("Approved snapshot was not created")

    rag_entry = None
    chunks: list[dict] = []
    rag_links: list[dict] = []
    embedded_edge = None
    if content_type == "faq":
        chunk_text = _faq_chunk_text(
            brand=brand,
            briefing=briefing,
            campaign=campaign,
            audience=audience,
            product=product,
            question=question,
            answer=answer,
            rules=rules,
            tone=tone,
        )
        rag_entry = supabase_client.upsert_knowledge_rag_entry({
            "persona_id": persona_id,
            "artifact_id": source_node.get("artifact_id") or source_meta.get("artifact_id"),
            "content_type": "faq",
            "semantic_level": int(source_node.get("level") or 75),
            "title": title,
            "question": question,
            "answer": answer,
            "content": approved_markdown,
            "summary": approved_summary,
            "canonical_key": canonical_key,
            "slug": slug,
            "status": "active",
            "tags": sorted(set((source_node.get("tags") or []) + ["faq", "approved", "n8n-ready"])),
            "entities": [],
            "products": [product.get("slug")] if product else [],
            "campaigns": [campaign.get("slug")] if campaign else [],
            "metadata": {
                **source_meta,
                "source": "approved_knowledge_snapshots",
                "approved_snapshot_id": snapshot.get("id"),
                "source_node_id": source_node.get("id"),
                "source_knowledge_item_id": (source_item or {}).get("id"),
                "hierarchy_path": hierarchy_path,
                "status": "active",
                "rag_index": source_meta.get("rag_index") or "default",
            },
            "confidence": float(source_node.get("confidence") or 0.85),
            "importance": float(source_node.get("importance") or 0.75),
            "validated_at": now_iso,
        })
        if not rag_entry or not rag_entry.get("id"):
            raise RuntimeError("RAG entry was not created for approved FAQ")
        chunks = supabase_client.replace_knowledge_rag_chunks(
            rag_entry["id"],
            persona_id,
            [{
                "chunk_index": 0,
                "chunk_text": chunk_text,
                "chunk_summary": approved_summary[:280],
                "metadata": {
                    "persona_slug": persona.get("slug"),
                    "content_type": "faq",
                    "source": "approved_knowledge_snapshots",
                    "source_node_id": source_node.get("id"),
                    "approved_snapshot_id": snapshot.get("id"),
                    "rag_entry_id": rag_entry.get("id"),
                    "hierarchy_path": [step.get("node_type") for step in hierarchy_path],
                    "product": (product or {}).get("slug"),
                    "audience": (audience or {}).get("slug"),
                    "campaign": (campaign or {}).get("slug"),
                    "status": "active",
                    "question": question,
                    "answer": answer,
                },
            }],
        )
        if require_rag_for_faq and not chunks:
            raise RuntimeError("FAQ approved, but no RAG chunk was created")
        snapshot = supabase_client.update_approved_knowledge_snapshot(
            snapshot["id"],
            {
                "rag_entry_id": rag_entry.get("id"),
                "status": "active",
                "metadata": {
                    **(snapshot.get("metadata") or {}),
                    "rag_entry_id": rag_entry.get("id"),
                    "rag_chunk_ids": [chunk.get("id") for chunk in chunks if chunk.get("id")],
                    "n8n_ready": True,
                },
                "updated_at": now_iso,
            },
        ) or snapshot
        embedded_node = supabase_client.ensure_embedded_node(persona_id)
        if embedded_node and embedded_node.get("id"):
            embedded_edge = supabase_client.upsert_knowledge_edge(
                source_node_id=source_node["id"],
                target_node_id=embedded_node["id"],
                relation_type="manual",
                persona_id=persona_id,
                weight=1.0,
                metadata={
                    "primary_tree": False,
                    "active": True,
                    "visual_hidden": False,
                    "created_from": "approved_snapshot_publication",
                    "approved_snapshot_id": snapshot.get("id"),
                    "rag_entry_id": rag_entry.get("id"),
                },
            )

    node_meta = {
        **source_meta,
        "approved_snapshot_id": snapshot.get("id"),
        "knowledge_rag_entry_id": (rag_entry or {}).get("id"),
        "knowledge_rag_chunk_ids": [chunk.get("id") for chunk in chunks if chunk.get("id")],
        "snapshot_status": snapshot.get("status"),
        "n8n_ready": bool(chunks) if content_type == "faq" else False,
    }
    supabase_client.update_knowledge_node(source_node["id"], {"metadata": node_meta, "status": "validated"})
    if source_item and source_item.get("id"):
        supabase_client.update_knowledge_item(source_item["id"], {
            "metadata": {
                **(source_item.get("metadata") or {}),
                "approved_snapshot_id": snapshot.get("id"),
                "knowledge_rag_entry_id": (rag_entry or {}).get("id"),
                "knowledge_rag_chunk_ids": [chunk.get("id") for chunk in chunks if chunk.get("id")],
            }
        })

    return {
        "success": True,
        "approved_snapshot_id": snapshot.get("id"),
        "source_node_id": source_node.get("id"),
        "knowledge_node_ids": [node.get("id") for node in chain if node.get("id")],
        "knowledge_edge_ids": [edge.get("id") for edge in path_edges if edge.get("id")] + ([embedded_edge.get("id")] if embedded_edge and embedded_edge.get("id") else []),
        "embedded_edge_id": (embedded_edge or {}).get("id"),
        "rag_entry_id": (rag_entry or {}).get("id"),
        "rag_chunk_ids": [chunk.get("id") for chunk in chunks if chunk.get("id")],
        "rag_link_ids": [link.get("id") for link in rag_links if link.get("id")],
        "status": "active" if content_type == "faq" else "approved",
        "graph_materialized": bool(source_node.get("id")),
        "content_type": content_type,
        "canonical_key": canonical_key,
    }
