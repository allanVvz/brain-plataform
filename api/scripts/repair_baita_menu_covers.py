"""Repair Baita menu category covers and product category routing.

This is intentionally idempotent and narrow:
- Lagunitas asset covers Cervejas Premium.
- Patagonia Daytime asset covers Classicas Cervejas.
- Yergermeter/Jagermeister asset covers Top Shelf Destilados Premium.
- Product category slugs are driven by product node metadata.
"""
from __future__ import annotations

import json
import re
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
from scripts.seed_baita_cardapio_assets import CARDAPIO_CAMPAIGN_SLUG, _edge
from scripts.seed_baita_full_menu import parse_menu_items

SOURCE = "repair_baita_menu_covers"

PREMIUM_BEER_PATTERNS = (
    "BLUE MOON",
    "CORONA",
    "ESTRELLA GALICIA",
    "GOOSE ISLAND",
    "HOCUS POCUS",
    "LAGUNITAS",
    "PATAGONIA",
    "ROLETA RUSSA",
    "THEREZOPOLIS",
    "THEREZÓPOLIS",
)


def _slugify(value: str) -> str:
    return supabase_client._slugify(value)


def _client():
    return supabase_client.get_client()


def _persona(slug: str) -> dict:
    persona = supabase_client.get_persona(slug)
    if not persona:
        raise RuntimeError(f"Persona not found: {slug}")
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


def _upsert_node(persona_id: str, node_type: str, slug: str, title: str, summary: str, metadata: dict, tags: list[str]) -> dict:
    row = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": node_type,
        "slug": slug,
        "title": title,
        "summary": summary,
        "tags": tags,
        "metadata": metadata,
        "status": "validated",
    })
    if not row:
        raise RuntimeError(f"Could not upsert {node_type}:{slug}")
    return row


def _update_node(node: dict, *, slug: str | None = None, title: str | None = None, summary: str | None = None, metadata: dict | None = None) -> dict:
    payload: dict = {"status": "validated"}
    if slug:
        payload["slug"] = slug
    if title:
        payload["title"] = title
    if summary:
        payload["summary"] = summary
    if metadata is not None:
        payload["metadata"] = {**(node.get("metadata") or {}), **metadata}
    updated = _client().table("knowledge_nodes").update(payload).eq("id", node["id"]).execute().data
    return (updated or [{**node, **payload}])[0]


def _ensure_category(persona_id: str, slug: str, title: str, eyebrow: str, position: int, summary: str) -> dict:
    metadata = {
        "persona_slug": "baita-conveniencia",
        "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
        "position": position,
        "sort_order": position,
        "eyebrow": eyebrow,
        "visible": True,
        "created_from": SOURCE,
    }
    category = _upsert_node(
        persona_id,
        "category",
        slug,
        title,
        summary,
        metadata,
        ["baita", "category", slug],
    )
    _upsert_node(
        persona_id,
        "entity",
        f"categoria-{slug}",
        title,
        f"Entidade da categoria {title.replace(chr(10), ' ')}.",
        {
            "persona_slug": "baita-conveniencia",
            "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
            "category_slug": slug,
            "entity_role": "category_group",
            "created_from": SOURCE,
        },
        ["baita", "entity", "category_entity", slug],
    )
    return category


def _asset_by_filename(persona_id: str, filename_part: str) -> dict:
    rows = (
        _client()
        .table("assets")
        .select("*")
        .eq("persona_id", persona_id)
        .ilike("original_filename", f"%{filename_part}%")
        .limit(10)
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError(f"Asset not found: {filename_part}")
    return rows[0]


def _ensure_approved_asset(persona_id: str, filename_part: str) -> tuple[dict, dict]:
    asset = _asset_by_filename(persona_id, filename_part)
    metadata = {
        **(asset.get("metadata") or {}),
        "validation_status": "approved",
        "approved": True,
        "created_from": SOURCE,
    }
    asset = (
        _client()
        .table("assets")
        .update({"metadata": metadata, "status": "ready"})
        .eq("id", asset["id"])
        .execute()
        .data
        or [asset]
    )[0]
    asset_node_id = asset.get("knowledge_node_id")
    if not asset_node_id:
        raise RuntimeError(f"Asset has no knowledge_node_id: {asset.get('original_filename')}")
    asset_node = (
        _client()
        .table("knowledge_nodes")
        .select("*")
        .eq("id", asset_node_id)
        .maybe_single()
        .execute()
        .data
    )
    if not asset_node:
        raise RuntimeError(f"Asset node not found: {asset_node_id}")
    asset_node = _update_node(
        asset_node,
        title=asset_node.get("title") or asset.get("original_filename"),
        metadata={
            "validation_status": "approved",
            "approved": True,
            "asset_id": asset["id"],
            "url": asset.get("url"),
            "created_from": SOURCE,
        },
    )
    gallery = supabase_client.ensure_gallery_node(persona_id)
    if not gallery:
        raise RuntimeError("Gallery node not available")
    gallery_edge = supabase_client.upsert_knowledge_edge(
        asset_node["id"],
        gallery["id"],
        "gallery_asset",
        persona_id=persona_id,
        weight=0.95,
        metadata={"status": "approved", "active": True, "created_from": SOURCE},
    )
    supabase_client.update_asset_graph_refs(
        asset["id"],
        knowledge_node_id=asset_node["id"],
        gallery_edge_id=(gallery_edge or {}).get("id"),
    )
    return asset, asset_node


def _connect_cover(persona_id: str, category: dict, asset_node: dict, asset: dict, sort_order: int = 0) -> None:
    edge = supabase_client.upsert_knowledge_edge(
        category["id"],
        asset_node["id"],
        "uses_asset",
        persona_id=persona_id,
        weight=0.95,
        metadata={
            "role": "category_cover",
            "status": "approved",
            "active": True,
            "sort_order": sort_order,
            "created_from": SOURCE,
        },
    )
    meta = {
        "cover_asset_id": asset["id"],
        "cover_asset_node_id": asset_node["id"],
        "cover_url": asset.get("url"),
        "cover_alt": category.get("title"),
        "created_from": SOURCE,
    }
    _update_node(category, metadata=meta)
    supabase_client.update_asset_graph_refs(
        asset["id"],
        knowledge_node_id=asset_node["id"],
        parent_node_id=category["id"],
        parent_edge_id=(edge or {}).get("id"),
    )


def _deprioritize_cover(persona_id: str, category_slug: str, asset_node: dict) -> None:
    category = _node(persona_id, "category", category_slug)
    if not category:
        return
    supabase_client.upsert_knowledge_edge(
        category["id"],
        asset_node["id"],
        "uses_asset",
        persona_id=persona_id,
        weight=0.2,
        metadata={
            "role": "category_cover",
            "status": "approved",
            "active": True,
            "sort_order": 99,
            "created_from": SOURCE,
        },
    )


def _repair_existing_categories(persona_id: str) -> dict[str, dict]:
    collection = _node(persona_id, "product_collection", CARDAPIO_CAMPAIGN_SLUG)
    if not collection:
        raise RuntimeError(f"Collection not found: {CARDAPIO_CAMPAIGN_SLUG}")

    premium = _ensure_category(
        persona_id,
        "cervejas-premium",
        "Cervejas Premium",
        "HERO",
        10,
        "IPAs, importadas e rotulos especiais do cardapio Baita.",
    )
    classic = _ensure_category(
        persona_id,
        "cervejas",
        "Classicas\nCervejas",
        "GELADAS",
        20,
        "Cervejas classicas, long necks, latas e opcoes para todos os roles.",
    )
    top_shelf = _node(persona_id, "category", "destilados")
    if top_shelf:
        top_shelf = _update_node(
            top_shelf,
            slug="destilados-premium",
            title="Top Shelf\nDestilados Premium",
            summary="Licores, whiskies, gins e garrafas premium.",
            metadata={
                "category_slug": "destilados-premium",
                "position": 70,
                "sort_order": 70,
                "eyebrow": "TOP SHELF",
                "visible": True,
                "created_from": SOURCE,
            },
        )
    else:
        top_shelf = _ensure_category(
            persona_id,
            "destilados-premium",
            "Top Shelf\nDestilados Premium",
            "TOP SHELF",
            70,
            "Licores, whiskies, gins e garrafas premium.",
        )

    entity = _node(persona_id, "entity", "categoria-destilados")
    if entity:
        _update_node(
            entity,
            slug="categoria-destilados-premium",
            title="Top Shelf\nDestilados Premium",
            metadata={"category_slug": "destilados-premium", "created_from": SOURCE},
        )
    else:
        _upsert_node(
            persona_id,
            "entity",
            "categoria-destilados-premium",
            "Top Shelf\nDestilados Premium",
            "Entidade da categoria Top Shelf Destilados Premium.",
            {
                "persona_slug": "baita-conveniencia",
                "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
                "category_slug": "destilados-premium",
                "entity_role": "category_group",
                "created_from": SOURCE,
            },
            ["baita", "entity", "category_entity", "destilados-premium"],
        )

    categories = {
        "cervejas-premium": premium,
        "cervejas": classic,
        "destilados-premium": top_shelf,
    }
    for slug, category in categories.items():
        _edge(collection, category, "collection_has_category", persona_id, weight=0.9, primary=True)
    return categories


def _target_category_for_product(item: dict) -> str:
    title = item["title"].upper()
    if item["category_slug"] == "cervejas" and any(pattern in title for pattern in PREMIUM_BEER_PATTERNS):
        return "cervejas-premium"
    if item["category_slug"] == "destilados":
        return "destilados-premium"
    return item["category_slug"]


def _ensure_missing_products(persona_id: str) -> int:
    items = parse_menu_items()
    existing_rows = (
        _client()
        .table("knowledge_nodes")
        .select("id,slug,title,metadata")
        .eq("persona_id", persona_id)
        .eq("node_type", "product")
        .eq("metadata->>collection_slug", CARDAPIO_CAMPAIGN_SLUG)
        .limit(1000)
        .execute()
        .data
        or []
    )
    existing = {row["slug"]: row for row in existing_rows}
    inserted_or_updated = 0
    for item in items:
        category_slug = _target_category_for_product(item)
        metadata = {
            "persona_slug": "baita-conveniencia",
            "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
            "category_slug": category_slug,
            "price_cents": item["price_cents"],
            "price_display": item["price_display"],
            "position": item["position"],
            "visible": True,
            "source": SOURCE,
            "created_from": SOURCE,
        }
        if item["slug"] in existing:
            row = existing[item["slug"]]
            current = row.get("metadata") or {}
            if current.get("category_slug") != category_slug or current.get("price_cents") != item["price_cents"]:
                _client().table("knowledge_nodes").update({
                    "title": item["title"],
                    "summary": f"{item['title']} - {item['price_display']}.",
                    "metadata": {**current, **metadata},
                    "status": "validated",
                }).eq("id", row["id"]).execute()
                inserted_or_updated += 1
            continue
        supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "product",
            "slug": item["slug"],
            "title": item["title"],
            "summary": f"{item['title']} - {item['price_display']}.",
            "tags": ["baita", "product", category_slug],
            "metadata": metadata,
            "status": "validated",
        })
        inserted_or_updated += 1
    return inserted_or_updated


def _repair_covers(persona_id: str, categories: dict[str, dict]) -> None:
    lag_asset, lag_node = _ensure_approved_asset(persona_id, "Lagunitas")
    pat_asset, pat_node = _ensure_approved_asset(persona_id, "patagonia-Daytime")
    jag_asset, jag_node = _ensure_approved_asset(persona_id, "yergermeter")

    _connect_cover(persona_id, categories["cervejas-premium"], lag_node, lag_asset, sort_order=0)
    _connect_cover(persona_id, categories["cervejas"], pat_node, pat_asset, sort_order=0)
    _connect_cover(persona_id, categories["destilados-premium"], jag_node, jag_asset, sort_order=0)

    _deprioritize_cover(persona_id, "cervejas", lag_node)


def repair(persona_slug: str = "baita-conveniencia") -> dict:
    persona = _persona(persona_slug)
    persona_id = persona["id"]
    categories = _repair_existing_categories(persona_id)
    changed_products = _ensure_missing_products(persona_id)
    _repair_covers(persona_id, categories)

    products_count = (
        _client()
        .table("knowledge_nodes")
        .select("id", count="exact")
        .eq("persona_id", persona_id)
        .eq("node_type", "product")
        .eq("metadata->>collection_slug", CARDAPIO_CAMPAIGN_SLUG)
        .limit(1)
        .execute()
        .count
    )
    return {
        "ok": True,
        "persona_slug": persona_slug,
        "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
        "products_count": products_count,
        "changed_products": changed_products,
        "covers": {
            "cervejas-premium": "Baita-Cardapio-Lagunitas-Daytime.png",
            "cervejas": "Baita-Cardapio-patagonia-Daytime.png",
            "destilados-premium": "Baita-Cardapio-yergermeter.jpg",
        },
    }


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(API_DIR / ".env", override=False)
    print(json.dumps(repair(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
