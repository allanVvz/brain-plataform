"""Enrich the Baita menu graph with Sofia copy, FAQ, briefing and embeds.

The menu app consumes only graph-approved context. This seed creates a stable
test fixture for the main catalog products without inventing a products table:
product -> copy, product -> FAQ, FAQ -> Embedded/RAG, collection -> briefing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = API_DIR.parent
for path in (API_DIR, ROOT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from utils.tls import configure_trust_store

configure_trust_store()

from services import supabase_client
from scripts.seed_baita_cardapio_assets import CARDAPIO_CAMPAIGN_SLUG

SOURCE = "sofia_baita_cardapio_context_v1"


def _client():
    return supabase_client.get_client()


def _meta(row: dict | None) -> dict:
    return (row or {}).get("metadata") or {}


def _slug(value: str) -> str:
    return supabase_client._slugify(value)


def _persona(persona_slug: str) -> dict:
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise RuntimeError(f"Persona not found: {persona_slug}")
    return persona


def _node(persona_id: str, node_type: str, slug: str) -> dict | None:
    return (
        _client()
        .table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", node_type)
        .eq("slug", slug)
        .limit(1)
        .execute()
        .data
        or [None]
    )[0]


def _upsert_node(
    persona_id: str,
    node_type: str,
    slug: str,
    title: str,
    summary: str,
    tags: list[str],
    metadata: dict,
    status: str = "validated",
) -> dict:
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": node_type,
        "slug": slug,
        "title": title,
        "summary": summary,
        "tags": tags,
        "metadata": metadata,
        "status": status,
    })
    if not node:
        raise RuntimeError(f"Could not upsert {node_type}:{slug}")
    return node


def _edge(source: dict, target: dict, relation_type: str, persona_id: str, *, weight: float = 0.8, metadata: dict | None = None) -> dict | None:
    return supabase_client.upsert_knowledge_edge(
        source["id"],
        target["id"],
        relation_type,
        persona_id=persona_id,
        weight=weight,
        metadata={
            "active": True,
            "created_from": SOURCE,
            **(metadata or {}),
        },
    )


def _products(persona_id: str, collection_slug: str) -> list[dict]:
    rows = (
        _client()
        .table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", "product")
        .eq("metadata->>collection_slug", collection_slug)
        .neq("status", "archived")
        .limit(1000)
        .execute()
        .data
        or []
    )
    return sorted(
        rows,
        key=lambda row: (
            str(_meta(row).get("category_slug") or ""),
            int(_meta(row).get("position") or 0),
            row.get("title") or "",
        ),
    )


def _categories_by_slug(persona_id: str, collection_slug: str) -> dict[str, dict]:
    rows = (
        _client()
        .table("knowledge_nodes")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("node_type", "category")
        .eq("metadata->>collection_slug", collection_slug)
        .neq("status", "archived")
        .limit(500)
        .execute()
        .data
        or []
    )
    return {row["slug"]: row for row in rows}


def _ensure_collection_briefing(persona_id: str, collection: dict) -> dict:
    briefing = _upsert_node(
        persona_id,
        "briefing",
        "briefing-cardapio-baita-sofia",
        "Briefing Sofia - Cardapio Baita",
        "Briefing operacional para o cardapio vivo Baita: hierarquia, tom, assets, copy e FAQ.",
        ["baita", "briefing", "cardapio", "sofia"],
        {
            "persona_slug": "baita-conveniencia",
            "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
            "briefing_scope": "collection",
            "tone": "premium, direto, conveniente, noturno e jovem",
            "rules": [
                "Toda categoria deve nascer do grafo e de nodes product/entity.",
                "Assets so entram no cardapio quando aprovados e conectados a Gallery.",
                "FAQ elegivel para RAG deve estar conectado ao node Embedded.",
                "Produtos podem ser exibidos sem FAQ, mas FAQ conectado ao Embedded deve ir para a API.",
            ],
            "created_from": SOURCE,
        },
    )
    _edge(collection, briefing, "collection_has_briefing", persona_id, weight=0.9, metadata={"primary_tree": True})
    return briefing


def _copy_text(product: dict, category: dict | None) -> tuple[str, str]:
    title = product.get("title") or product.get("slug") or "Produto"
    price = _meta(product).get("price_display") or ""
    category_title = (category or {}).get("title") or _meta(product).get("category_slug") or "cardapio"
    headline = f"{title} no cardapio Baita"
    body = f"{title} esta em {category_title}. Use esta copy para apresentar preco, categoria e disponibilidade no cardapio digital."
    if price:
        body += f" Preco atual: R$ {price}."
    return headline, body


def _faq_text(product: dict, category: dict | None) -> tuple[str, str]:
    title = product.get("title") or product.get("slug") or "produto"
    price = _meta(product).get("price_display") or "consultar no balcao"
    category_title = (category or {}).get("title") or _meta(product).get("category_slug") or "cardapio"
    question = f"Qual o preco de {title}?"
    answer = (
        f"{title} esta cadastrado em {category_title} no cardapio Baita. "
        f"O preco cadastrado para este teste e R$ {price}. "
        "A disponibilidade pode variar conforme estoque e validacao da equipe."
    )
    return question, answer


def enrich(limit: int = 220, persona_slug: str = "baita-conveniencia", collection_slug: str = CARDAPIO_CAMPAIGN_SLUG) -> dict:
    persona = _persona(persona_slug)
    persona_id = persona["id"]
    collection = _node(persona_id, "product_collection", collection_slug)
    if not collection:
        raise RuntimeError(f"Collection not found: {collection_slug}")
    embedded = supabase_client.ensure_embedded_node(persona_id)
    if not embedded:
        raise RuntimeError("Embedded node not available")
    briefing = _ensure_collection_briefing(persona_id, collection)
    categories = _categories_by_slug(persona_id, collection_slug)
    products = _products(persona_id, collection_slug)
    selected = products[:limit]

    copy_count = 0
    faq_count = 0
    embedded_count = 0
    for product in selected:
        product_meta = _meta(product)
        category = categories.get(str(product_meta.get("category_slug") or ""))
        headline, body = _copy_text(product, category)
        copy = _upsert_node(
            persona_id,
            "copy",
            f"copy-cardapio-{product['slug']}",
            headline,
            body,
            ["baita", "copy", "cardapio", product["slug"]],
            {
                "persona_slug": persona_slug,
                "collection_slug": collection_slug,
                "product_slug": product["slug"],
                "category_slug": product_meta.get("category_slug"),
                "slot": "cardapio_product_summary",
                "headline": headline,
                "body": body,
                "cta": "Ver no cardapio",
                "generated_by": "Sofia",
                "created_from": SOURCE,
            },
        )
        _edge(product, copy, "product_has_copy", persona_id, weight=0.82)
        _edge(briefing, copy, "supports_copy", persona_id, weight=0.55, metadata={"primary_tree": False})
        copy_count += 1

        question, answer = _faq_text(product, category)
        faq = _upsert_node(
            persona_id,
            "faq",
            f"faq-cardapio-{product['slug']}",
            question,
            answer,
            ["baita", "faq", "cardapio", "rag", product["slug"]],
            {
                "persona_slug": persona_slug,
                "collection_slug": collection_slug,
                "product_slug": product["slug"],
                "category_slug": product_meta.get("category_slug"),
                "question": question,
                "answer": answer,
                "is_rag_eligible": True,
                "rag_status": "embedded",
                "generated_by": "Sofia",
                "created_from": SOURCE,
            },
        )
        _edge(product, faq, "product_has_faq", persona_id, weight=0.82)
        _edge(copy, faq, "copy_has_faq", persona_id, weight=0.55, metadata={"primary_tree": False})
        _edge(faq, embedded, "faq_has_embed", persona_id, weight=0.85, metadata={"rag_eligible": True, "status": "embedded"})
        faq_count += 1
        embedded_count += 1

    return {
        "ok": True,
        "persona_slug": persona_slug,
        "collection_slug": collection_slug,
        "products_total": len(products),
        "products_enriched": len(selected),
        "copy_nodes": copy_count,
        "faq_nodes": faq_count,
        "faq_embed_edges": embedded_count,
        "briefing": briefing.get("slug"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=220)
    parser.add_argument("--persona-slug", default="baita-conveniencia")
    args = parser.parse_args()
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(API_DIR / ".env", override=False)
    print(json.dumps(enrich(limit=args.limit, persona_slug=args.persona_slug), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
