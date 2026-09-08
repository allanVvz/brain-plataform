from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from core.landing_slots import LandingSlot, slot_for_metadata
from services import public_site, supabase_client
from utils.rich_text import to_clean_markdown

router = APIRouter(tags=["menu"])

_MENU_CACHE_CONTROL = "public, max-age=30, s-maxage=300, stale-while-revalidate=600"


def _canonical_json_checksum(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _public_graph_context(persona_slug: str) -> Optional[dict]:
    """Return public grants exclusively from the active immutable v3 snapshot."""
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        return None
    publication = supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication or publication.get("status") != "active":
        return None
    document = publication.get("document_json") or {}
    if not isinstance(document, dict) or document.get("schema_version") != "3.0":
        return None
    document_body = dict(document)
    document_checksum = str(document_body.pop("checksum", ""))
    publication_checksum = str(publication.get("checksum") or "")
    document_persona = document.get("persona") or {}
    if (
        not document_checksum
        or document_checksum != publication_checksum
        or _canonical_json_checksum(document_body) != document_checksum
        or str(document_persona.get("id") or "") != str(persona.get("id") or "")
        or str(document_persona.get("slug") or "") != persona_slug
    ):
        return None
    nodes = [node for node in document.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in document.get("edges") or [] if isinstance(edge, dict)]
    action = next(
        (
            node for node in nodes
            if str(node.get("node_type") or "").lower() == "gallery"
            and ((node.get("data") or {}).get("action") or {}).get("enabled") is True
            and ((node.get("data") or {}).get("action") or {}).get("destination_type") == "public_site"
        ),
        None,
    )
    by_id = {str(node.get("id")): node for node in nodes}
    granted = {
        str(edge.get("source")) for edge in edges
        if action is not None
        and edge.get("relation_type") in {"publishes_to", "gallery_asset"}
        and edge.get("target") == action.get("id")
        and (edge.get("metadata") or {}).get("active", True) is not False
        and by_id.get(str(edge.get("source")))
        and str(by_id[str(edge.get("source"))].get("status") or "").lower()
        in {"approved", "active", "validated", "ativo", "embedded"}
    }
    allowed: dict[str, set[str]] = {}
    asset_registry_ids: set[str] = set()
    for node_id in granted:
        node = by_id[node_id]
        node_type = str(node.get("node_type") or "")
        data = node.get("data") or {}
        allowed.setdefault(node_type, set()).add(str(node.get("slug") or ""))
        if node_type == "asset":
            blob = data.get("blob") or {}
            registry_id = blob.get("registry_id") or data.get("registry_id")
            if registry_id:
                asset_registry_ids.add(str(registry_id))
    return {
        "version": publication.get("version"),
        "checksum": publication.get("checksum"),
        "publication_id": publication.get("id"),
        "action": action,
        "allowed": allowed,
        "asset_registry_ids": asset_registry_ids,
        "nodes": nodes,
        "edges": edges,
    }


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
        "slot_key": page_binding.get("slot_key") or (slot.value if slot else None),
        "href": meta.get("href") or meta.get("cta_url"),
        "markdown": meta.get("markdown") or meta.get("body"),
    }


def _copy_payload(node: dict) -> dict:
    meta = _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "slot": meta.get("slot") or "body",
        # Copy bodies frequently arrive as HTML (Shopify/CMS). Clean to markdown
        # so no raw tags ever reach the cardapio, agents, or RAG.
        "body": to_clean_markdown(meta.get("body") or node.get("summary") or node.get("title") or ""),
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
        if row.get("knowledge_node_id")
        and row.get("url")
        and row.get("status") == "approved"
        and (row.get("file_path") or row.get("url"))
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
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        # A public product image is valid only while it remains connected both
        # to the product and to the Gallery terminal.  This makes graph edits
        # immediately authoritative for the landing-page projection.
        asset = gallery_by_node.get(str(asset_node_id))
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
    campaigns = [
        row for row in campaigns
        if (_meta(row).get("collection_slug") or collection_slug) == collection_slug
        and _meta(row).get("created_via") != "bind_slot"
        and not _meta(row).get("landing_slot")
    ]
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


def _brand_payload(persona: dict, persona_slug: str, cache: Optional[dict] = None) -> dict:
    """Build the persona.brand block from the graph.

    Looks up the persona's brand node and any `brand_has_asset` edges. The
    bound assets are surfaced as `brand.logo` and `brand.cover` (the cardapio
    Brand schema only renders these two; secondary assets are returned in
    `brand.secondary_assets` for future use)."""
    persona_id = persona["id"]
    fallback = {
        "id": f"brand-{persona_slug}",
        "slug": persona.get("slug") or persona_slug,
        "name": persona.get("name") or persona_slug,
        "accent_color": "#f5c518",
    }
    try:
        brand_rows = (
            supabase_client.get_client()
            .table("knowledge_nodes")
            .select("*")
            .eq("persona_id", persona_id)
            .eq("node_type", "brand")
            .neq("status", "archived")
            .limit(2)
            .execute()
            .data or []
        )
    except Exception:
        return fallback
    if not brand_rows:
        return fallback
    brand = brand_rows[0]
    brand_meta = _meta(brand)
    out = {
        "id": brand.get("id") or fallback["id"],
        "slug": brand.get("slug") or fallback["slug"],
        "name": brand.get("title") or fallback["name"],
        # short_name = selo/monograma curto da marca (ex.: "VZ"); wordmark = texto
        # exibido. Sem isso o front cai em iniciais derivadas do nome (ex.: "VZ
        # Lupas" -> "VL"). Emitir o valor canonico evita esse derivado errado.
        "short_name": brand_meta.get("short_name") or None,
        "wordmark": brand_meta.get("wordmark") or None,
        "accent_color": brand_meta.get("accent_color") or fallback["accent_color"],
        # node_id is only present when a real knowledge_node backs this brand.
        # admin-blocks uses it to decide whether to emit brand_* slot blocks.
        "node_id": brand.get("id"),
    }
    gallery_by_node = _gallery_assets_by_node(persona_id, cache=cache)
    edges = supabase_client.list_edges_for_nodes(
        [brand["id"]],
        relation_types=["brand_has_asset", "uses_asset"],
        limit=200,
    )
    by_slot: dict[str, dict] = {}
    secondary: list[dict] = []
    for edge in edges:
        if edge.get("source_node_id") != brand["id"]:
            continue
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        asset_node_id = edge.get("target_node_id")
        asset = gallery_by_node.get(str(asset_node_id))
        if not asset:
            continue
        slot = slot_for_metadata(meta)
        if slot == LandingSlot.BRAND_LOGO:
            payload = _asset_payload(asset, asset_type="logo", alt=brand.get("title") or "Logo", edge=edge)
            by_slot[LandingSlot.BRAND_LOGO.value] = payload
        elif slot == LandingSlot.BRAND_COVER:
            payload = _asset_payload(asset, asset_type="cover", alt=brand.get("title") or "Cover", edge=edge)
            by_slot[LandingSlot.BRAND_COVER.value] = payload
        elif slot == LandingSlot.BRAND_SECONDARY:
            secondary.append(_asset_payload(asset, asset_type="image", alt=brand.get("title") or "", edge=edge))
    if LandingSlot.BRAND_LOGO.value in by_slot:
        out["logo"] = by_slot[LandingSlot.BRAND_LOGO.value]
    if LandingSlot.BRAND_COVER.value in by_slot:
        out["cover"] = by_slot[LandingSlot.BRAND_COVER.value]
    if secondary:
        out["secondary_assets"] = secondary
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
    persona = supabase_client.get_persona(persona_slug)
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


def _default_collection_slug(persona: dict, persona_slug: str) -> str:
    config = persona.get("config") or {}
    if isinstance(config, dict):
        public_config = config.get("public_site") if isinstance(config.get("public_site"), dict) else {}
        explicit = (
            public_config.get("default_collection_slug")
            or config.get("default_collection_slug")
            or config.get("collection_slug")
        )
        if explicit:
            return str(explicit)
    return f"cardapio-{persona_slug}-v1"


def _products_by_group(products: list[dict], group_ids: list[str]) -> dict[str, list[str]]:
    """Map product_group_id -> [product_id] using canonical edges.

    Tries product_group_has_product (canonical), then legacy in_category /
    category_has_product. Products without an edge fall back to metadata.product_group_slug
    or metadata.category_slug matching on the caller side.
    """
    product_ids = [row["id"] for row in products if row.get("id")]
    if not product_ids or not group_ids:
        return {}
    edges = supabase_client.list_edges_for_nodes(
        list(set(product_ids) | set(group_ids)),
        relation_types=["product_group_has_product", "in_category", "category_has_product", "contains"],
        limit=5000,
    )
    by_group: dict[str, list[str]] = {}
    group_set = set(group_ids)
    product_set = set(product_ids)
    for edge in edges:
        if (edge.get("metadata") or {}).get("active") is False:
            continue
        src = edge.get("source_node_id")
        tgt = edge.get("target_node_id")
        group_id = src if src in group_set else (tgt if tgt in group_set else None)
        product_id = tgt if group_id == src else (src if group_id == tgt else None)
        if group_id and product_id in product_set:
            by_group.setdefault(group_id, []).append(product_id)
    return by_group


def _active_node_data(node: dict) -> dict:
    data = node.get("data") or {}
    return data if isinstance(data, dict) else {}


def _active_asset_payload(
    node: dict,
    *,
    persona_id: str,
    registry_cache: dict[str, Optional[dict]],
) -> dict:
    data = _active_node_data(node)
    blob = data.get("blob") or {}
    registry_id = str(blob.get("registry_id") or data.get("registry_id") or "")
    registry = None
    if registry_id:
        if registry_id not in registry_cache:
            registry_cache[registry_id] = supabase_client.get_asset(registry_id)
        candidate = registry_cache[registry_id]
        candidate_meta = (candidate or {}).get("metadata") or {}
        registry_state = str(
            candidate_meta.get("validation_status")
            or (candidate or {}).get("approval_status")
            or (candidate or {}).get("status")
            or ""
        ).lower()
        node_state = str(
            node.get("status") or data.get("validation_status") or ""
        ).lower()
        has_object = bool(
            (candidate or {}).get("storage_bucket")
            and (candidate or {}).get("storage_path")
        )
        if (
            candidate
            and str(candidate.get("persona_id") or "") == str(persona_id)
            and node_state in {"approved", "validated", "active", "ativo"}
            and registry_state not in {"archived", "rejected", "failed"}
            and has_object
        ):
            registry = candidate
    # A URL inside a GraphBundle is evidence metadata, not proof that the
    # binary still exists or is approved. Public rendering resolves only the
    # persona-owned assets registry row and otherwise emits no image.
    resolved_url = supabase_client.asset_display_url(registry) if registry else ""
    return {
        "id": str(node.get("id") or ""),
        "asset_id": registry_id or node.get("id"),
        "knowledge_node_id": node.get("id"),
        "edge_id": None,
        "type": data.get("type") or data.get("asset_type") or "image",
        "url": resolved_url,
        "alt": data.get("alt") or node.get("title") or "",
        "role": data.get("role") or data.get("asset_function"),
        "section": data.get("page_section"),
        "slot_key": (data.get("page_binding") or {}).get("slot_key"),
        "href": data.get("href") or data.get("cta_url"),
        "markdown": data.get("markdown") or data.get("body"),
    }


def _collection_scope(
    collection: Optional[dict], nodes: list[dict], edges: list[dict]
) -> tuple[Optional[dict], set[str]]:
    """Resolve one explicit commercial Brand and its owned descendants."""
    if not collection:
        brands = [node for node in nodes if str(node.get("node_type") or "").lower() == "brand"]
        return (brands[0], set()) if len(brands) == 1 else (None, set())
    data = _active_node_data(collection)
    explicit_ids = {
        str(data.get(key) or "")
        for key in ("brand_node_id", "branch_node_id", "scope_node_id")
        if data.get(key)
    }
    explicit_slugs = {
        str(data.get(key) or "")
        for key in ("brand_slug", "branch_slug", "scope_slug")
        if data.get(key)
    }
    collection_id = str(collection.get("id") or "")
    connected_ids = {
        str(edge.get("target") if str(edge.get("source") or "") == collection_id else edge.get("source"))
        for edge in edges
        if collection_id in {str(edge.get("source") or ""), str(edge.get("target") or "")}
    }
    brands = [
        node for node in nodes
        if str(node.get("node_type") or "").lower() == "brand"
        and (
            str(node.get("id") or "") in explicit_ids
            or str(node.get("slug") or "") in explicit_slugs
            or str(node.get("id") or "") in connected_ids
        )
    ]
    if not brands:
        all_brands = [node for node in nodes if str(node.get("node_type") or "").lower() == "brand"]
        brands = all_brands if len(all_brands) == 1 else []
    if len(brands) != 1:
        return None, set()
    brand = brands[0]
    owned = {
        str(edge.get("target") or "")
        for edge in edges
        if str(edge.get("source") or "") == str(brand.get("id") or "")
        and str(edge.get("relation_type") or "") == "contains"
    }
    return brand, owned


def _select_group_cover(explicit_assets: list[dict], products: list[dict]) -> Optional[dict]:
    direct = next((asset for asset in explicit_assets if asset.get("url")), None)
    if direct:
        return direct
    products_with_media = [
        product for product in products
        if any(asset.get("url") for asset in product.get("assets") or [])
    ]
    if len(products_with_media) != 1:
        return None
    return next(
        (asset for asset in products_with_media[0].get("assets") or [] if asset.get("url")),
        None,
    )


def build_menu_payload(persona_slug: str, collection_slug: Optional[str] = None) -> dict:
    """Build the public site only from the active immutable GraphBundle v3."""
    persona = _resolve_persona(persona_slug)
    publication = _public_graph_context(persona_slug)
    if publication is None:
        raise HTTPException(409, "active_graph_publication_v3_required")

    nodes = publication.get("nodes") or []
    edges = [
        edge for edge in publication.get("edges") or []
        if (edge.get("metadata") or {}).get("active", True) is not False
    ]
    action = publication.get("action")
    allowed = publication.get("allowed") or {}
    allowed_slugs = {
        slug for values in allowed.values() for slug in values if slug
    }
    public_nodes = [
        node for node in nodes
        if str(node.get("slug") or "") in allowed_slugs
    ]
    by_id = {str(node.get("id") or ""): node for node in public_nodes}
    neighbours: dict[str, set[str]] = {}
    for edge in edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source in by_id and target in by_id:
            neighbours.setdefault(source, set()).add(target)
            neighbours.setdefault(target, set()).add(source)

    def typed(node_type: str) -> list[dict]:
        return [
            node for node in public_nodes
            if str(node.get("node_type") or "").lower() == node_type
        ]

    def adjacent(node: dict, node_type: str) -> list[dict]:
        return [
            by_id[node_id] for node_id in neighbours.get(str(node.get("id") or ""), set())
            if str(by_id[node_id].get("node_type") or "").lower() == node_type
        ]

    effective_collection_slug = collection_slug or _default_collection_slug(persona, persona_slug)
    campaigns = typed("campaign")
    collection_node = next(
        (node for node in campaigns if node.get("slug") == effective_collection_slug),
        None,
    )
    if collection_node is None and len(campaigns) == 1 and not collection_slug:
        collection_node = campaigns[0]
    if collection_node is None and (campaigns or collection_slug):
        raise HTTPException(404, f"Collection not found: {effective_collection_slug}")

    scoped_brand, brand_owned_node_ids = _collection_scope(collection_node, public_nodes, edges)
    if len(typed("brand")) > 1 and scoped_brand is None:
        raise HTTPException(409, "public_collection_brand_scope_ambiguous")
    registry_cache: dict[str, Optional[dict]] = {}

    products = typed("product")
    groups = typed("product_group")
    products_by_group: dict[str, list[dict]] = {str(group.get("id")): [] for group in groups}
    ungrouped: list[dict] = []
    for product in products:
        linked = [
            node for node in adjacent(product, "product_group")
            if str(node.get("id") or "") in products_by_group
        ]
        if linked:
            for group in linked:
                products_by_group[str(group.get("id"))].append(product)
        else:
            ungrouped.append(product)
    if ungrouped:
        synthetic = {
            "id": "public:sem-categoria",
            "slug": "sem-categoria",
            "title": "Produtos",
            "node_type": "product_group",
            "data": {"synthesized": True},
        }
        groups.append(synthetic)
        products_by_group[synthetic["id"]] = ungrouped

    def product_payload(product: dict) -> dict:
        data = _active_node_data(product)
        copies = [
            node for node in adjacent(product, "copy")
            if not brand_owned_node_ids or str(node.get("id") or "") in brand_owned_node_ids
        ]
        faqs = adjacent(product, "faq")
        assets = adjacent(product, "asset")
        offers = [
            node for node in adjacent(product, "offer")
            if not brand_owned_node_ids or str(node.get("id") or "") in brand_owned_node_ids
        ]
        offer_data = _active_node_data(offers[0]) if offers else {}
        return {
            "id": product.get("id"),
            "slug": product.get("slug") or product.get("id"),
            "name": product.get("title") or product.get("slug") or "Produto",
            "price_cents": _read_int(offer_data.get("price_cents") or data.get("price_cents"), 0),
            "offer": offer_data.get("price") or data.get("price") or None,
            "offer_id": offers[0].get("id") if offers else None,
            "description": to_clean_markdown(
                product.get("summary") or data.get("description") or ""
            ),
            "visible": data.get("visible") is not False,
            "position": _read_int(data.get("position"), 0),
            "copies": [{
                "id": node.get("id"),
                "slug": node.get("slug"),
                "slot": _active_node_data(node).get("slot") or "body",
                "body": to_clean_markdown(
                    _active_node_data(node).get("content")
                    or _active_node_data(node).get("body")
                    or node.get("summary") or ""
                ),
            } for node in copies],
            "faqs": [{
                "id": node.get("id"),
                "slug": node.get("slug"),
                "question": _active_node_data(node).get("question") or node.get("title") or "",
                "answer": (
                    _active_node_data(node).get("answer")
                    or _active_node_data(node).get("content")
                    or node.get("summary") or ""
                ),
                "is_rag_eligible": True,
            } for node in faqs],
            "assets": [
                _active_asset_payload(
                    node, persona_id=str(persona["id"]), registry_cache=registry_cache,
                )
                for node in assets
            ],
        }

    categories = []
    for group in groups:
        data = _active_node_data(group)
        group_products = sorted(
            (product_payload(node) for node in products_by_group.get(str(group.get("id")), [])),
            key=lambda row: row["position"],
        )
        group_assets = adjacent(group, "asset") if str(group.get("id")) in by_id else []
        # A direct group cover is explicit and always wins. Product media may
        # cover the group only when exactly one product in it has any approved
        # image, preventing one product's photo from representing its siblings.
        explicit_group_assets = [
            _active_asset_payload(
                node, persona_id=str(persona["id"]), registry_cache=registry_cache,
            ) for node in group_assets
        ]
        cover = _select_group_cover(explicit_group_assets, group_products)
        group_slug = group.get("slug") or group.get("id")
        message_template = str(
            ((persona.get("config") or {}).get("public_site") or {}).get("whatsapp_message_template")
            or "Tenho interesse em {group_name}."
        )
        readable_message = message_template.replace("{group_name}", str(group.get("title") or group_slug))
        readable_message = readable_message.replace("{group_slug}", str(group_slug)).strip()
        cta_message = f"{readable_message} [vitrine:{group_slug}]"
        categories.append({
            "id": group.get("id"),
            "slug": group.get("slug") or group.get("id"),
            "title": group.get("title") or group.get("slug") or "Produtos",
            "eyebrow": data.get("eyebrow") or data.get("category_eyebrow") or "",
            "cover": (cover or {}).get("url") or "",
            "cover_alt": (cover or {}).get("alt") or group.get("title") or "",
            "cover_asset_id": (cover or {}).get("asset_id"),
            "cover_edge_id": None,
            "cover_slot_key": (cover or {}).get("slot_key"),
            "cta_message": cta_message,
            "visible": data.get("visible") is not False,
            "position": _read_int(data.get("position") or data.get("sort_order"), 0),
            "products": group_products,
        })
    categories.sort(key=lambda row: row["position"])

    formats = supabase_client.list_public_site_formats(enabled_only=True)
    site = public_site.public_site_payload(persona, formats, catalog_url=persona.get("catalog_url"))
    action_data = ((_active_node_data(action).get("action") if action else None) or {})
    projection = action_data.get("projection") or {}
    for key in ("site_slug", "site_name", "default_collection_slug"):
        if projection.get(key):
            site[key] = projection[key]

    brand = {}
    if scoped_brand:
        node = scoped_brand
        data = _active_node_data(node)
        brand = {
            "slug": node.get("slug"),
            "name": node.get("title") or "",
            "description": node.get("summary") or "",
            **{key: data[key] for key in (
                "logo_url", "primary_color", "secondary_color", "accent_color"
            ) if data.get(key)},
        }
    collection_assets = [
        _active_asset_payload(
            node, persona_id=str(persona["id"]), registry_cache=registry_cache,
        ) for node in typed("asset")
        if not any(node in adjacent(product, "asset") for product in products)
        and (not brand_owned_node_ids or str(node.get("id") or "") in brand_owned_node_ids)
    ]
    collection_data = _active_node_data(collection_node) if collection_node else {}
    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_collection_id": (
            collection_node.get("id") if collection_node
            else f"persona:{persona['id']}:cardapio"
        ),
        "site": site,
        "persona": {
            "id": persona["id"],
            "slug": persona_slug,
            "name": persona.get("name") or persona_slug,
            "brand": brand,
            "collections": [{
                "id": collection_node.get("id") if collection_node else f"persona:{persona['id']}:cardapio",
                "slug": collection_node.get("slug") if collection_node else effective_collection_slug,
                "type": collection_data.get("collection_type") or "menu",
                "display_name": (
                    collection_data.get("display_name")
                    or (collection_node or {}).get("title")
                    or persona.get("name") or persona_slug
                ),
                "cover": next((row["cover"] for row in categories if row["cover"]), ""),
                "assets": collection_assets,
                "briefing": next((
                    {
                        "id": node.get("id"),
                        "title": node.get("title"),
                        "summary": node.get("summary") or _active_node_data(node).get("content") or "",
                    }
                    for node in typed("briefing")
                ), None),
                "categories": categories,
            }],
        },
        "graph_version": publication.get("version"),
        "graph_checksum": publication.get("checksum"),
        "action_node_id": action.get("id") if action else None,
        "publication_id": publication.get("publication_id"),
    }
    checksum_payload = {key: value for key, value in payload.items() if key != "generated_at"}
    payload["projection_checksum"] = _canonical_json_checksum(checksum_payload)
    return payload

def _menu_response(persona_slug: str, collection_slug: Optional[str], response: Response, nocache: bool) -> dict:
    payload = build_menu_payload(persona_slug, collection_slug=collection_slug)
    response.headers["Cache-Control"] = "no-store" if nocache else _MENU_CACHE_CONTROL
    if payload.get("projection_checksum"):
        response.headers["ETag"] = f'"{payload["projection_checksum"]}"'
    return payload


@router.get("/api/menu/{persona_slug}")
def get_api_menu(
    persona_slug: str,
    response: Response,
    collection_slug: Optional[str] = Query(None),
    nocache: int = Query(0, ge=0, le=1),
):
    return _menu_response(persona_slug, collection_slug, response, bool(nocache))


@router.get("/menu/{persona_slug}")
def get_menu(
    persona_slug: str,
    response: Response,
    collection_slug: Optional[str] = Query(None),
    nocache: int = Query(0, ge=0, le=1),
):
    return _menu_response(persona_slug, collection_slug, response, bool(nocache))


# ── Public read-only admin views (auth-exempt, under /api/menu/*) ─────────
#
# The cardapio admin UI lives in the same public site as the landing page;
# it has no AI-BRAIN session. Exposing read-only asset + connection state
# here lets the admin grid render without auth, while writes (bind-slot,
# unbind, ensure-gallery, delete-edge) still require a session on /assets/*.


def _admin_asset_payload(row: dict) -> dict:
    """Whitelist asset fields for the public admin view (no signing keys)."""
    metadata = row.get("metadata") or {}
    display_url = supabase_client.asset_display_url(row)
    return {
        "id": row.get("id"),
        "persona_id": row.get("persona_id"),
        "type": row.get("type"),
        "name": row.get("name"),
        "url": display_url,
        "display_url": display_url,
        "original_filename": row.get("original_filename") or metadata.get("original_filename"),
        "storage_bucket": row.get("storage_bucket") or metadata.get("storage_bucket"),
        "storage_path": row.get("storage_path") or metadata.get("storage_path"),
        "mime_type": row.get("mime_type"),
        "file_size": row.get("file_size"),
        "status": row.get("status"),
        "upload_context": row.get("upload_context") or metadata.get("upload_context"),
        "knowledge_node_id": row.get("knowledge_node_id") or metadata.get("knowledge_node_id"),
        "gallery_edge_id": row.get("gallery_edge_id") or metadata.get("gallery_edge_id"),
        "parent_node_id": row.get("parent_node_id") or metadata.get("parent_node_id"),
        "parent_edge_id": row.get("parent_edge_id") or metadata.get("parent_edge_id"),
        "graph_status": row.get("graph_status"),
        "metadata": {
            "asset_function": metadata.get("asset_function"),
            "visual_summary": metadata.get("visual_summary"),
            "extracted_text": (metadata.get("extracted_text") or "")[:600] or None,
            "kind": metadata.get("kind"),
            "branch_hint": metadata.get("branch_hint") or metadata.get("parent_slug"),
            "tags": metadata.get("tags"),
        },
    }


@router.get("/api/menu/{persona_slug}/admin-assets")
def list_admin_assets(persona_slug: str, response: Response):
    persona = _resolve_persona(persona_slug)
    rows = supabase_client.list_assets(persona_id=persona["id"], limit=500, offset=0)
    response.headers["Cache-Control"] = "no-store"
    return [_admin_asset_payload(row) for row in rows]


@router.get("/api/menu/{persona_slug}/admin-blocks")
def list_admin_blocks(persona_slug: str, response: Response, collection_slug: Optional[str] = Query(None)):
    """Configurable landing blocks for the admin UI: hero, footer, every category cover,
    every product image. Each row carries everything the UI needs to call
    POST /assets/{id}/bind-slot or DELETE /assets/{id}/bind-slot/{slot}.
    """
    payload = build_menu_payload(persona_slug, collection_slug=collection_slug)
    persona = payload["persona"]
    collection = persona["collections"][0]
    brand = persona.get("brand") or {}
    blocks: list[dict] = []

    # Only emit brand blocks when the persona actually has a knowledge_node of
    # type 'brand'. Without it, bind-slot would fail with 404 since brand slots
    # are resolved through that node.
    brand_slug = brand.get("slug") if brand.get("node_id") else None
    if brand_slug:
        logo_asset = brand.get("logo") or {}
        blocks.append({
            "block_id": f"brand-logo:{brand_slug}",
            "label": f"Logo da marca: {brand.get('name') or brand_slug}",
            "where": "Cabecalho e badges do cardapio",
            "slot_key": LandingSlot.BRAND_LOGO.value,
            "collection_slug": collection["slug"],
            "target_slug": brand_slug,
            "current_asset_url": logo_asset.get("url") or None,
            "current_asset_id": logo_asset.get("asset_id") or logo_asset.get("id"),
            "current_edge_id": logo_asset.get("edge_id"),
        })
        cover_asset = brand.get("cover") or {}
        blocks.append({
            "block_id": f"brand-cover:{brand_slug}",
            "label": f"Capa da marca: {brand.get('name') or brand_slug}",
            "where": "Capa institucional do cardapio",
            "slot_key": LandingSlot.BRAND_COVER.value,
            "collection_slug": collection["slug"],
            "target_slug": brand_slug,
            "current_asset_url": cover_asset.get("url") or None,
            "current_asset_id": cover_asset.get("asset_id") or cover_asset.get("id"),
            "current_edge_id": cover_asset.get("edge_id"),
        })
        for index, secondary in enumerate(brand.get("secondary_assets") or []):
            blocks.append({
                "block_id": f"brand-secondary:{brand_slug}:{index}",
                "label": f"Asset secundario {index + 1}",
                "where": "Galeria de elementos de marca no cardapio",
                "slot_key": LandingSlot.BRAND_SECONDARY.value,
                "slot_instance_key": f"{LandingSlot.BRAND_SECONDARY.value}:{brand_slug}:{index}",
                "collection_slug": collection["slug"],
                "target_slug": brand_slug,
                "current_asset_url": secondary.get("url") or None,
                "current_asset_id": secondary.get("asset_id") or secondary.get("id"),
                "current_edge_id": secondary.get("edge_id"),
            })

    hero_asset = next(
        (a for a in collection["assets"] if a.get("slot_key") == LandingSlot.HERO.value),
        None,
    )
    blocks.append({
        "block_id": f"hero:{collection['slug']}",
        "label": "Home Hero",
        "where": "Topo da landing /cardapio/<persona>",
        "slot_key": LandingSlot.HERO.value,
        "collection_slug": collection["slug"],
        "target_slug": None,
        "current_asset_url": (hero_asset or {}).get("url") or collection.get("cover") or None,
        "current_asset_id": (hero_asset or {}).get("asset_id") or (hero_asset or {}).get("id") or None,
        "current_edge_id": (hero_asset or {}).get("edge_id"),
    })

    footer_asset = next(
        (a for a in collection["assets"] if a.get("slot_key") == LandingSlot.CAMPAIGN_FOOTER.value),
        None,
    )
    blocks.append({
        "block_id": f"footer:{collection['slug']}",
        "label": "Campanha de rodape",
        "where": "Rodape da landing /cardapio/<persona>",
        "slot_key": LandingSlot.CAMPAIGN_FOOTER.value,
        "collection_slug": collection["slug"],
        "target_slug": None,
        "current_asset_url": (footer_asset or {}).get("url"),
        "current_asset_id": (footer_asset or {}).get("asset_id") or (footer_asset or {}).get("id"),
        "current_edge_id": (footer_asset or {}).get("edge_id"),
    })

    for category in collection["categories"]:
        blocks.append({
            "block_id": f"category:{category['slug']}",
            "label": f"Categoria: {category['title']}",
            "where": f"Card de grupo · /cardapio/{persona_slug}#category-{category['slug']}",
            "slot_key": LandingSlot.PRODUCT_GROUP_COVER.value,
            "collection_slug": collection["slug"],
            "target_slug": category["slug"],
            "current_asset_url": category.get("cover") or None,
            "current_asset_id": category.get("cover_asset_id"),
            "current_edge_id": category.get("cover_edge_id"),
        })

    for category in collection["categories"]:
        for product in category.get("products", []):
            assets = product.get("assets") or []
            current = assets[0] if assets else {}
            blocks.append({
                "block_id": f"product:{product['slug']}",
                "label": f"Produto — {product['name']}",
                "where": f"Card de produto · {category['title']} > {product['name']}",
                "slot_key": LandingSlot.PRODUCT_IMAGE.value,
                "slot_instance_key": f"{LandingSlot.PRODUCT_IMAGE.value}:{product['slug']}",
                "collection_slug": collection["slug"],
                "target_slug": product["slug"],
                "current_asset_url": current.get("url") or None,
                "current_asset_id": current.get("asset_id") or current.get("id"),
                "current_edge_id": current.get("edge_id"),
            })

    response.headers["Cache-Control"] = "no-store"
    return {
        "persona_slug": persona_slug,
        "collection_slug": collection["slug"],
        "blocks": blocks,
    }


@router.get("/api/menu/{persona_slug}/admin-connections/{asset_id}")
def list_admin_connections(persona_slug: str, asset_id: str, response: Response):
    persona = _resolve_persona(persona_slug)
    asset = supabase_client.get_asset(asset_id)
    if not asset or asset.get("persona_id") != persona["id"]:
        raise HTTPException(404, "Asset nao encontrado para esta persona.")
    knowledge_node_id = (asset.get("knowledge_node_id")
                         or (asset.get("metadata") or {}).get("knowledge_node_id"))
    if not knowledge_node_id:
        response.headers["Cache-Control"] = "no-store"
        return {"asset_id": asset_id, "knowledge_node_id": None, "connections": []}
    edges = supabase_client.list_edges_for_nodes([knowledge_node_id], limit=500)
    parent_ids = list({
        edge.get("source_node_id")
        for edge in edges
        if edge.get("target_node_id") == knowledge_node_id
        and edge.get("relation_type") not in {"gallery_asset", "belongs_to_persona"}
    } - {None})
    parents = {row["id"]: row for row in supabase_client.list_knowledge_nodes_by_ids(parent_ids)}
    out: list[dict] = []
    for edge in edges:
        if edge.get("target_node_id") != knowledge_node_id:
            continue
        if edge.get("relation_type") in {"gallery_asset", "belongs_to_persona"}:
            continue
        parent = parents.get(edge.get("source_node_id"))
        if not parent:
            continue
        meta = edge.get("metadata") or {}
        binding = meta.get("page_binding") or {}
        derived_slot = slot_for_metadata(meta)
        out.append({
            "edge_id": edge.get("id"),
            "relation_type": edge.get("relation_type"),
            "slot_key": binding.get("slot_key") or (derived_slot.value if derived_slot else None),
            "page_section": binding.get("section") or meta.get("page_section"),
            "label": binding.get("label"),
            "position": binding.get("position"),
            "role": meta.get("role"),
            "parent_node": {
                "id": parent.get("id"),
                "slug": parent.get("slug"),
                "node_type": parent.get("node_type"),
                "title": parent.get("title"),
                "collection_slug": (parent.get("metadata") or {}).get("collection_slug"),
            },
        })
    response.headers["Cache-Control"] = "no-store"
    return {"asset_id": asset_id, "knowledge_node_id": knowledge_node_id, "connections": out}
