from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from core.landing_slots import LandingSlot, slot_for_metadata
from services import supabase_client

router = APIRouter(tags=["menu"])

_MENU_CACHE_CONTROL = "public, max-age=30, s-maxage=300, stale-while-revalidate=600"


def _meta(row: Optional[dict]) -> dict:
    return (row or {}).get("metadata") or {}


def _read_int(value, fallback: int = 0) -> int:
    try:
        if value is None or value == "":
            return fallback
        return int(value)
    except Exception:
        return fallback


def _asset_payload(
    asset: dict,
    *,
    asset_type: str = "image",
    alt: str = "",
    edge: Optional[dict] = None,
) -> dict:
    meta = asset.get("metadata") or {}
    edge_meta = (edge or {}).get("metadata") or {}
    page_binding = edge_meta.get("page_binding") or meta.get("page_binding") or {}
    slot = slot_for_metadata(edge_meta) or slot_for_metadata(meta)
    return {
        "id": str(asset.get("id") or asset.get("knowledge_node_id") or ""),
        "asset_id": asset.get("id"),
        "knowledge_node_id": asset.get("knowledge_node_id"),
        "edge_id": (edge or {}).get("id"),
        "type": asset_type,
        "url": asset.get("url") or asset.get("file_path") or meta.get("public_url") or meta.get("url") or "",
        "alt": alt or asset.get("title") or asset.get("name") or "",
        "role": edge_meta.get("role") or meta.get("asset_function") or meta.get("role"),
        "section": (
            edge_meta.get("page_section")
            or page_binding.get("section")
            or meta.get("page_section")
        ),
        "slot_key": slot.value if slot else page_binding.get("slot_key"),
        "href": meta.get("href") or meta.get("cta_url"),
        "markdown": meta.get("markdown") or meta.get("body"),
    }


def _copy_payload(node: dict) -> dict:
    meta = _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "slot": meta.get("slot") or "body",
        "body": meta.get("body") or node.get("summary") or node.get("title") or "",
    }


def _faq_payload(node: dict) -> dict:
    meta = _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "question": meta.get("question") or node.get("title") or "",
        "answer": meta.get("answer") or node.get("summary") or "",
        "is_rag_eligible": bool(meta.get("is_rag_eligible") or meta.get("rag_status") == "embedded"),
    }


def _gallery_assets_by_node(persona_id: str, cache: Optional[dict] = None) -> dict[str, dict]:
    if cache is not None and "gallery_by_node" in cache:
        return cache["gallery_by_node"]
    rows = supabase_client.list_gallery_assets(persona_id=persona_id, limit=500)
    by_node = {
        str(row.get("knowledge_node_id")): row
        for row in rows
        if row.get("knowledge_node_id") and row.get("url")
    }
    if cache is not None:
        cache["gallery_by_node"] = by_node
    return by_node


def _category_cover_assets(categories: list[dict], persona_id: str, cache: Optional[dict] = None) -> dict[str, dict]:
    category_ids = [row["id"] for row in categories if row.get("id")]
    if not category_ids:
        return {}
    gallery_by_node = _gallery_assets_by_node(persona_id, cache=cache)
    edges = supabase_client.list_edges_for_nodes(
        category_ids,
        relation_types=["uses_asset", "product_has_asset", "category_has_asset"],
        limit=5000,
    )
    out: dict[str, dict] = {}
    for edge in edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        category_id = source_id if source_id in category_ids else target_id if target_id in category_ids else None
        asset_node_id = target_id if category_id == source_id else source_id
        if not category_id or not asset_node_id:
            continue
        asset = gallery_by_node.get(str(asset_node_id))
        if not asset:
            continue
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        current_value = out.get(category_id, {}).get("_rank")
        current_rank = _read_int(current_value, 9999) if current_value is not None else 9999
        rank = _read_int(meta.get("sort_order"), 0 if meta.get("role") == "category_cover" else 10)
        if category_id not in out or rank < current_rank:
            out[category_id] = {**asset, "_rank": rank, "_edge": edge}
    return out


def _product_assets(products: list[dict], persona_id: str, cache: Optional[dict] = None) -> dict[str, list[dict]]:
    product_ids = [row["id"] for row in products if row.get("id")]
    if not product_ids:
        return {}
    gallery_by_node = _gallery_assets_by_node(persona_id, cache=cache)
    edges = supabase_client.list_edges_for_nodes(
        product_ids,
        relation_types=["product_image", "product_has_asset"],
        limit=5000,
    )
    out: dict[str, list[dict]] = {}
    for edge in edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        product_id = source_id if source_id in product_ids else target_id if target_id in product_ids else None
        asset_node_id = target_id if product_id == source_id else source_id
        asset = gallery_by_node.get(str(asset_node_id))
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        if product_id and asset:
            out.setdefault(product_id, []).append({**asset, "_edge": edge})
    return out


def _related_nodes(products: list[dict], relation_types: list[str]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    product_ids = [row["id"] for row in products if row.get("id")]
    if not product_ids:
        return {}, {}
    edges = supabase_client.list_edges_for_nodes(product_ids, relation_types=relation_types, limit=10000)
    related_ids: set[str] = set()
    product_to_related_ids: dict[str, list[str]] = {}
    for edge in edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        product_id = source_id if source_id in product_ids else target_id if target_id in product_ids else None
        if not product_id:
            continue
        related_id = target_id if product_id == source_id else source_id
        if not related_id:
            continue
        related_ids.add(related_id)
        product_to_related_ids.setdefault(product_id, []).append(related_id)
    nodes = {row["id"]: row for row in supabase_client.list_knowledge_nodes_by_ids(list(related_ids))}
    product_to_nodes = {
        product_id: [nodes[node_id] for node_id in ids if node_id in nodes]
        for product_id, ids in product_to_related_ids.items()
    }
    return product_to_nodes, nodes


def _embedded_faq_ids(faq_nodes: list[dict]) -> set[str]:
    faq_ids = [row["id"] for row in faq_nodes if row.get("id")]
    if not faq_ids:
        return set()
    edges = supabase_client.list_edges_for_nodes(faq_ids, relation_types=["faq_has_embed"], limit=10000)
    embedded_ids = {
        edge.get("target_node_id")
        for edge in edges
        if edge.get("source_node_id") in faq_ids
    } | {
        edge.get("source_node_id")
        for edge in edges
        if edge.get("target_node_id") in faq_ids
    }
    embedded_nodes = {
        row["id"]: row
        for row in supabase_client.list_knowledge_nodes_by_ids([node_id for node_id in embedded_ids if node_id])
        if row.get("node_type") == "embedded"
    }
    out: set[str] = set()
    for edge in edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        if source_id in faq_ids and target_id in embedded_nodes:
            out.add(source_id)
        if target_id in faq_ids and source_id in embedded_nodes:
            out.add(target_id)
    return out


def _collection_campaign_assets(collection: dict, persona_id: str, cache: Optional[dict] = None) -> list[dict]:
    collection_slug = collection.get("slug") or (_meta(collection).get("collection_slug"))
    try:
        campaigns = (
            supabase_client.get_client()
            .table("knowledge_nodes")
            .select("*")
            .eq("persona_id", persona_id)
            .eq("node_type", "campaign")
            .neq("status", "archived")
            .limit(200)
            .execute()
            .data or []
        )
    except Exception:
        return []
    campaigns = [row for row in campaigns if (_meta(row).get("collection_slug") or collection_slug) == collection_slug]
    campaign_ids = [row["id"] for row in campaigns if row.get("id")]
    if not campaign_ids:
        return []
    gallery_by_node = _gallery_assets_by_node(persona_id, cache=cache)
    edges = supabase_client.list_edges_for_nodes(
        campaign_ids,
        relation_types=["uses_asset", "campaign_has_asset", "supports_campaign"],
        limit=1000,
    )
    copy_edges = supabase_client.list_edges_for_nodes(campaign_ids, relation_types=["supports_copy"], limit=1000)
    copy_ids = [
        edge.get("target_node_id") if edge.get("source_node_id") in campaign_ids else edge.get("source_node_id")
        for edge in copy_edges
    ]
    copy_nodes = {
        row["id"]: row
        for row in supabase_client.list_knowledge_nodes_by_ids([node_id for node_id in copy_ids if node_id])
        if row.get("node_type") == "copy"
    }
    markdown_by_campaign: dict[str, str] = {}
    for edge in copy_edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        campaign_id = source_id if source_id in campaign_ids else target_id if target_id in campaign_ids else None
        copy_id = target_id if campaign_id == source_id else source_id
        copy_node = copy_nodes.get(str(copy_id))
        if campaign_id and copy_node:
            markdown_by_campaign[campaign_id] = (_meta(copy_node).get("body") or copy_node.get("summary") or "")
    out: list[dict] = []
    seen: set[str] = set()
    campaign_by_id = {row["id"]: row for row in campaigns}
    for edge in edges:
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        campaign_id = source_id if source_id in campaign_ids else target_id if target_id in campaign_ids else None
        asset_node_id = target_id if campaign_id == source_id else source_id
        if not campaign_id or not asset_node_id or asset_node_id in seen:
            continue
        asset = gallery_by_node.get(str(asset_node_id))
        if not asset:
            continue
        campaign_meta = _meta(campaign_by_id.get(campaign_id))
        campaign_binding = campaign_meta.get("page_binding") or {}
        edge_binding = meta.get("page_binding") or {}
        page_binding = {**campaign_binding, **edge_binding}
        asset_meta = {
            **(asset.get("metadata") or {}),
            "asset_function": meta.get("role") or (asset.get("metadata") or {}).get("asset_function") or "campaign_hero",
            "page_section": meta.get("page_section") or page_binding.get("section"),
            "page_binding": page_binding,
            "markdown": markdown_by_campaign.get(campaign_id),
        }
        payload = _asset_payload(
            {**asset, "metadata": asset_meta},
            asset_type="banner",
            alt=page_binding.get("label") or campaign_by_id.get(campaign_id, {}).get("title") or asset.get("name") or "Campanha",
            edge=edge,
        )
        out.append(payload)
        seen.add(str(asset_node_id))
    return out


def _collection_briefing(collection: dict, persona_id: str) -> dict:
    edges = supabase_client.list_edges_for_nodes(
        [collection["id"]],
        relation_types=["collection_has_briefing"],
        limit=100,
    )
    briefing_ids = [
        edge.get("target_node_id") if edge.get("source_node_id") == collection["id"] else edge.get("source_node_id")
        for edge in edges
    ]
    nodes = [
        row for row in supabase_client.list_knowledge_nodes_by_ids([node_id for node_id in briefing_ids if node_id])
        if row.get("node_type") == "briefing"
    ]
    if not nodes:
        return {
            "id": f"briefing-{collection.get('slug')}",
            "title": "AI-BRAIN Graph Menu",
            "tone": "Fonte viva via knowledge graph + Gallery.",
        }
    node = nodes[0]
    meta = _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "title": node.get("title") or "Briefing",
        "tone": meta.get("tone") or node.get("summary") or "",
        "notes": node.get("summary") or "",
        "rules": meta.get("rules") or [],
    }


def _resolve_persona(persona_slug: str) -> dict:
    candidates = [persona_slug]
    if persona_slug.lower() in {"baita", "baita-conveniencia"}:
        candidates.extend(["Baita-Conveniencia", "baita-conveniencia", "baita"])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        persona = supabase_client.get_persona(candidate)
        if persona:
            return persona

    normalized = persona_slug.strip().lower()
    for persona in supabase_client.get_personas():
        meta = _meta(persona)
        values = [
            persona.get("slug"),
            persona.get("name"),
            persona.get("title"),
            meta.get("display_name") if isinstance(meta, dict) else None,
        ]
        if any(str(value or "").strip().lower() == normalized for value in values):
            return persona

    raise HTTPException(404, f"Persona not found: {persona_slug}")


def build_menu_payload(persona_slug: str, collection_slug: str = "cardapio-baita-v14") -> dict:
    persona = _resolve_persona(persona_slug)
    persona_id = persona["id"]
    collection = supabase_client.get_knowledge_node_by_slug(
        collection_slug,
        persona_id=persona_id,
        node_type="product_collection",
    )
    if not collection:
        raise HTTPException(404, f"Collection not found: {collection_slug}")

    cache: dict = {}

    categories = [
        row for row in supabase_client.list_product_collection_nodes(
            persona_id=persona_id,
            node_type="category",
            limit=500,
        )
        if _meta(row).get("collection_slug") == collection_slug
    ]
    products = supabase_client.list_product_nodes(
        persona_id=persona_id,
        collection_slug=collection_slug,
        limit=1000,
    )
    products_by_category: dict[str, list[dict]] = {}
    product_assets = _product_assets(products, persona_id, cache=cache)
    product_related, related_node_map = _related_nodes(products, ["product_has_copy", "product_has_faq"])
    all_faq_nodes = [node for node in related_node_map.values() if node.get("node_type") == "faq"]
    embedded_faq_ids = _embedded_faq_ids(all_faq_nodes)
    for product in products:
        metadata = _meta(product)
        related = product_related.get(product["id"], [])
        copy_nodes = [node for node in related if node.get("node_type") == "copy" and node.get("status") != "archived"]
        faq_nodes = [
            node for node in related
            if node.get("node_type") == "faq"
            and node.get("status") != "archived"
            and node.get("id") in embedded_faq_ids
        ]
        product_payload = {
            "id": product["id"],
            "slug": product.get("slug") or product["id"],
            "name": product.get("title") or product.get("slug") or "Produto",
            "price_cents": _read_int(metadata.get("price_cents"), 0),
            "description": product.get("summary") or metadata.get("description") or "",
            "visible": metadata.get("visible") is not False and product.get("status") != "archived",
            "position": _read_int(metadata.get("position"), 0),
            "copies": [_copy_payload(node) for node in copy_nodes],
            "faqs": [_faq_payload(node) for node in faq_nodes],
            "assets": [
                _asset_payload(asset, alt=product.get("title") or "", edge=asset.get("_edge"))
                for asset in product_assets.get(product["id"], [])
            ],
        }
        products_by_category.setdefault(str(metadata.get("category_slug") or "sem-categoria"), []).append(product_payload)

    covers = _category_cover_assets(categories, persona_id, cache=cache)
    category_payloads = []
    for category in categories:
        metadata = _meta(category)
        cover_asset = covers.get(category["id"])
        cover_edge = (cover_asset or {}).get("_edge") if cover_asset else None
        category_slug = category.get("slug") or metadata.get("category_slug") or category["id"]
        category_payloads.append({
            "id": category["id"],
            "slug": category_slug,
            "title": category.get("title") or category_slug,
            "eyebrow": metadata.get("eyebrow") or metadata.get("category_eyebrow") or "",
            "cover": (cover_asset or {}).get("url") or "",
            "cover_alt": (cover_asset or {}).get("title") or category.get("title") or category_slug,
            "cover_asset_id": (cover_asset or {}).get("id") if cover_asset else None,
            "cover_edge_id": (cover_edge or {}).get("id") if cover_edge else None,
            "cover_slot_key": LandingSlot.PRODUCT_GROUP_COVER.value if cover_asset else None,
            "visible": metadata.get("visible") is not False and category.get("status") != "archived",
            "position": _read_int(metadata.get("position") or metadata.get("sort_order"), 0),
            "products": sorted(products_by_category.get(str(category_slug), []), key=lambda row: row.get("position", 0)),
        })

    collection_meta = _meta(collection)
    collection_cover = ""
    sorted_categories = sorted(category_payloads, key=lambda row: row.get("position", 0))
    for category in sorted_categories:
        if category.get("cover"):
            collection_cover = category["cover"]
            break
    collection_assets = _collection_campaign_assets(collection, persona_id, cache=cache)
    campaign_display_name = (
        collection_assets[0].get("alt")
        if collection_assets and collection_assets[0].get("alt")
        else collection_meta.get("campaign_name")
        or collection_meta.get("display_name")
        or collection.get("title")
        or "Cardapio"
    )
    persona_display_name = persona.get("name") or "Baita Conveniencia"

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_collection_id": collection["id"],
        "persona": {
            "id": persona_id,
            "slug": persona_slug,
            "name": persona_display_name,
            "brand": {
                "id": f"brand-{persona_slug}",
                "slug": "baita",
                "name": "BAITA!",
                "accent_color": "#f5c518",
            },
            "collections": [{
                "id": collection["id"],
                "slug": collection.get("slug") or collection_slug,
                "type": collection_meta.get("collection_type") or "menu",
                "display_name": campaign_display_name,
                "cover": collection_cover,
                "assets": collection_assets,
                "briefing": _collection_briefing(collection, persona_id),
                "categories": sorted_categories,
            }],
        },
    }


def _menu_response(persona_slug: str, collection_slug: str, response: Response, nocache: bool) -> dict:
    payload = build_menu_payload(persona_slug, collection_slug=collection_slug)
    response.headers["Cache-Control"] = "no-store" if nocache else _MENU_CACHE_CONTROL
    return payload


@router.get("/api/menu/{persona_slug}")
def get_api_menu(
    persona_slug: str,
    response: Response,
    collection_slug: str = Query("cardapio-baita-v14"),
    nocache: int = Query(0, ge=0, le=1),
):
    return _menu_response(persona_slug, collection_slug, response, bool(nocache))


@router.get("/menu/{persona_slug}")
def get_menu(
    persona_slug: str,
    response: Response,
    collection_slug: str = Query("cardapio-baita-v14"),
    nocache: int = Query(0, ge=0, le=1),
):
    return _menu_response(persona_slug, collection_slug, response, bool(nocache))



