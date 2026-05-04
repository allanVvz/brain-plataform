# -*- coding: utf-8 -*-
"""
Database-first KB intake pipeline for RAG-ready knowledge.

This is intentionally deterministic for the first version: it creates a raw
intake row, classifies common FAQ-shaped text, extracts basic structured facts,
creates a canonical RAG entry + chunk, and mirrors the entry into the existing
semantic graph.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from services import knowledge_graph, supabase_client


CONTENT_LEVELS = {
    "brand": 20,
    "campaign": 30,
    "product": 40,
    "briefing": 50,
    "tone": 60,
    "rule": 65,
    "copy": 70,
    "faq": 75,
    "asset": 80,
    "entity": 10,
    "general_note": 90,
}

ALLOWED_CONTENT_TYPES = set(CONTENT_LEVELS)


def _slugify(value: str) -> str:
    return knowledge_graph._slugify(value)


def _fold(value: str) -> str:
    return knowledge_graph._fold(value)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value or ""))


def _normalize_tags(tags) -> list[str]:
    return knowledge_graph._normalize_tags(tags)


def _resolve_persona(persona_id: Optional[str] = None, persona_slug: Optional[str] = None) -> dict:
    if persona_slug:
        persona = supabase_client.get_persona(persona_slug)
        if not persona:
            raise ValueError(f"Persona not found: {persona_slug}")
        return persona
    if persona_id:
        # get_persona resolves by slug only; use the private resolver to accept IDs.
        resolved = supabase_client._resolve_persona_id(persona_id)
        if not resolved:
            raise ValueError(f"Persona not found: {persona_id}")
        return {"id": resolved, "slug": persona_id, "name": persona_id}
    raise ValueError("persona_id or persona_slug is required")


def _extract_faq(text: str) -> tuple[Optional[str], Optional[str]]:
    pairs = knowledge_graph._extract_faq_pairs(text)
    if pairs:
        return pairs[0]

    cleaned = (text or "").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) >= 2 and "?" in lines[0]:
        return lines[0], " ".join(lines[1:])

    match = re.match(r"(?P<q>[^?\n]{8,}\?)\s*(?P<a>.+)", cleaned, flags=re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group("q")).strip(), re.sub(r"\s+", " ", match.group("a")).strip()

    return None, None


def _extract_price(text: str) -> Optional[dict]:
    price_re = re.compile(
        r"R\$\s*(?P<amount>\d{1,6}(?:[.,]\d{2})?)"
        r"(?:\s*(?:por|/)\s*(?P<unit>[A-Za-zÀ-ÿ0-9_-]+))?",
        flags=re.IGNORECASE,
    )
    match = price_re.search(text or "")
    if not match:
        percent = re.search(r"(?P<amount>\d{1,3})\s*%", text or "")
        if not percent:
            return None
        display = percent.group(0)
        return {
            "amount": int(percent.group("amount")),
            "currency": "PERCENT",
            "unit": "percentual",
            "display": display,
        }

    raw_amount = match.group("amount").replace(".", "").replace(",", ".")
    amount = float(raw_amount)
    if amount.is_integer():
        amount = int(amount)
    unit = match.group("unit")
    display = f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if unit:
        display = f"{display} por {unit}"
    return {
        "amount": amount,
        "currency": "BRL",
        "unit": unit,
        "display": display,
    }


def _product_candidates(persona_id: str) -> list[dict]:
    try:
        return supabase_client.list_knowledge_nodes_by_type(["product"], persona_id=persona_id, limit=500)
    except Exception:
        return []


def _detect_products(text: str, persona_id: str, explicit_products: Optional[list[str]] = None) -> list[dict]:
    out: dict[str, dict] = {}
    for product in explicit_products or []:
        slug = _slugify(str(product))
        out[slug] = {"slug": slug, "title": str(product), "source": "explicit"}

    folded_text = _fold(text or "")
    compact_text = _compact(text or "")
    for node in _product_candidates(persona_id):
        slug = node.get("slug") or ""
        title = node.get("title") or slug
        meta = node.get("metadata") or {}
        values = [slug, title, *(node.get("tags") or [])]
        for key in ("aliases", "synonyms"):
            if isinstance(meta.get(key), list):
                values.extend(str(v) for v in meta[key])
        matched = False
        for value in values:
            folded = _fold(str(value))
            compact = _compact(str(value))
            if not folded:
                continue
            if folded in folded_text or (len(compact) >= 5 and compact in compact_text):
                matched = True
                break
        if matched:
            out[slug] = {"slug": slug, "title": title, "source": "graph"}

    return list(out.values())


def classify_intake(
    *,
    text: str,
    persona_id: str,
    title: Optional[str] = None,
    content_type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> dict:
    meta = dict(metadata or {})
    question, answer = _extract_faq(text)
    requested_type = (content_type or "").strip().lower()
    inferred_type = requested_type or ("faq" if question and answer else "general_note")
    if inferred_type == "other" or inferred_type not in ALLOWED_CONTENT_TYPES:
        inferred_type = "general_note"
    normalized_tags = sorted(set(_normalize_tags(tags or []) + _normalize_tags(meta.get("tags"))))
    products = _detect_products(
        " ".join([title or "", text or "", " ".join(normalized_tags)]),
        persona_id,
        explicit_products=meta.get("products") or ([meta["product"]] if meta.get("product") else None),
    )
    product_slugs = [p["slug"] for p in products if p.get("slug")]

    price = _extract_price(text)
    if price:
        meta.setdefault("price", price)
        normalized_tags.append("preco")

    if inferred_type == "faq":
        entry_title = title or question or "FAQ"
        content = f"Pergunta: {question}\nResposta: {answer}"
        summary = answer[:300] if answer else text[:300]
    else:
        entry_title = title or (text.strip().splitlines()[0][:90] if text.strip() else "Conhecimento")
        content = text.strip()
        summary = text.strip()[:300]

    slug = _slugify(meta.get("slug") or entry_title)[:100]
    canonical_key = f"{inferred_type}:{slug}"

    return {
        "content_type": inferred_type,
        "semantic_level": CONTENT_LEVELS.get(inferred_type, 90),
        "title": entry_title,
        "question": question,
        "answer": answer,
        "content": content,
        "summary": summary,
        "canonical_key": canonical_key,
        "slug": slug,
        "tags": sorted(set(normalized_tags + product_slugs + [inferred_type])),
        "products": product_slugs,
        "campaigns": meta.get("campaigns") or ([meta["campaign"]] if meta.get("campaign") else []),
        "entities": meta.get("entities") or [],
        "metadata": meta,
        "confidence": 0.82 if inferred_type == "faq" else 0.55,
        "importance": 0.65 if inferred_type == "faq" else 0.5,
    }


def process_intake(
    *,
    raw_text: str,
    persona_id: Optional[str] = None,
    persona_slug: Optional[str] = None,
    source: str = "manual",
    source_ref: Optional[str] = None,
    title: Optional[str] = None,
    content_type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
    submitted_by: Optional[str] = None,
    validate: bool = False,
) -> dict:
    persona = _resolve_persona(persona_id=persona_id, persona_slug=persona_slug)
    resolved_persona_id = persona["id"]

    intake = supabase_client.insert_knowledge_intake_message({
        "persona_id": resolved_persona_id,
        "source": source,
        "source_ref": source_ref,
        "raw_text": raw_text,
        "raw_payload": {
            "title": title,
            "content_type": content_type,
            "tags": tags or [],
            "metadata": metadata or {},
        },
        "submitted_by": submitted_by,
        "status": "received",
    })

    try:
        classified = classify_intake(
            text=raw_text,
            persona_id=resolved_persona_id,
            title=title,
            content_type=content_type,
            tags=tags,
            metadata=metadata,
        )
        status = "validated" if validate else "pending_validation"
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = supabase_client.upsert_knowledge_rag_entry({
            "persona_id": resolved_persona_id,
            "intake_id": intake.get("id"),
            "content_type": classified["content_type"],
            "semantic_level": classified["semantic_level"],
            "title": classified["title"],
            "question": classified["question"],
            "answer": classified["answer"],
            "content": classified["content"],
            "summary": classified["summary"],
            "canonical_key": classified["canonical_key"],
            "slug": classified["slug"],
            "status": status,
            "tags": classified["tags"],
            "entities": classified["entities"],
            "products": classified["products"],
            "campaigns": classified["campaigns"],
            "metadata": classified["metadata"],
            "confidence": classified["confidence"],
            "importance": classified["importance"],
            "validated_at": now_iso if validate else None,
        })

        chunks = supabase_client.replace_knowledge_rag_chunks(
            entry["id"],
            resolved_persona_id,
            [{
                "chunk_index": 0,
                "chunk_text": classified["content"],
                "chunk_summary": classified["summary"],
                "metadata": {
                    "content_type": classified["content_type"],
                    "canonical_key": classified["canonical_key"],
                    "embedding_status": "pending",
                },
            }],
        )

        mirror = knowledge_graph.bootstrap_from_item(
            {
                "id": entry.get("id"),
                "persona_id": resolved_persona_id,
                "content_type": classified["content_type"],
                "title": classified["title"],
                "content": classified["content"],
                "tags": classified["tags"],
                "metadata": classified["metadata"],
                "status": status,
            },
            frontmatter={
                **classified["metadata"],
                "slug": classified["slug"],
                "product": classified["products"],
                "campaigns": classified["campaigns"],
                "tags": classified["tags"],
            },
            body=classified["content"],
            persona_id=resolved_persona_id,
            source_table="knowledge_rag_entries",
        )

        supabase_client.update_knowledge_intake_message(
            intake["id"],
            {"status": "rag_created", "processed_at": now_iso},
        )

        return {
            "intake": {**intake, "status": "rag_created", "processed_at": now_iso},
            "classification": classified,
            "rag_entry": entry,
            "chunks": chunks,
            "graph_node": mirror,
        }
    except Exception as exc:
        if intake.get("id"):
            supabase_client.update_knowledge_intake_message(
                intake["id"],
                {
                    "status": "error",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:1000],
                },
            )
        raise
