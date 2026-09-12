from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Query, Response

from brain_contracts.pricing import normalize_offer, offer_to_price_cents
from core.landing_slots import LandingSlot, slot_for_metadata
from services import public_site, supabase_client, graph_json_v2_store, graph_json_v21_adapter
from utils.rich_text import to_clean_markdown

router = APIRouter(tags=["menu"])

_MENU_CACHE_CONTROL = "public, max-age=30, s-maxage=300, stale-while-revalidate=600"
_DEFAULT_PUBLIC_ASSET_BUCKETS = frozenset({"assets-raw", "assets-derived"})
# Bilingual on purpose: authored CTA copy is Portuguese, so a bracketed
# technical ref leaks exactly like `[grupo:conjuntos]` did in production
# (2026-09-05) if only the English node-type word is banned.
_TECHNICAL_ID_PATTERN = re.compile(
    r"\b(?:asset|ativo|product_group|grupo_de_produto|product|produto|group|grupo"
    r"|audience|audiencia|campaign|campanha|copy|persona):[a-z0-9]",
    re.I,
)


def _canonical_json_checksum(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _asset_registry_id(node: dict) -> Optional[str]:
    data = node.get("data") or node.get("spec") or {}
    blob = data.get("blob") if isinstance(data.get("blob"), dict) else {}
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    value = (
        data.get("registry_id")
        or data.get("asset_id")
        or blob.get("registry_id")
        or media.get("registry_id")
    )
    return str(value) if value else None


def _active_publication_context(persona_id: str, persona_slug: Optional[str] = None) -> Optional[dict]:
    """Resolve public grants from the immutable active GraphBundle v3 output.

    Raw knowledge rows are authoring state and may contain a staged bundle.  The
    active graph publication is the only safe authority for deciding what may
    be projected publicly.
    """
    try:
        publication = supabase_client.get_active_graph_publication(persona_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "code": "graph_publication_lookup_failed",
            "persona_id": persona_id,
        }) from exc
    if not publication:
        return None

    document = publication.get("document_json") or {}
    document_persona = document.get("persona") if isinstance(document.get("persona"), dict) else {}
    identity_errors = []
    if str(publication.get("persona_id") or "") != persona_id:
        identity_errors.append("publication.persona_id:mismatch")
    if str(document_persona.get("id") or "") != persona_id:
        identity_errors.append("document.persona.id:mismatch")
    if persona_slug and str(document_persona.get("slug") or "") != persona_slug:
        identity_errors.append("document.persona.slug:mismatch")
    if document.get("schema_version") != "3.0":
        identity_errors.append("document.schema_version:v3_required")
    if not publication.get("id"):
        identity_errors.append("publication.id:required")
    if not isinstance(publication.get("version"), int):
        identity_errors.append("publication.version:integer_required")
    checksum = str(publication.get("checksum") or document.get("checksum") or "")
    if not checksum.startswith("sha256:"):
        identity_errors.append("publication.checksum:invalid")
    if publication.get("checksum") and document.get("checksum") and publication["checksum"] != document["checksum"]:
        identity_errors.append("publication.checksum:document_mismatch")
    if identity_errors:
        raise HTTPException(status_code=503, detail={
            "code": "graph_publication_identity_invalid",
            "persona_id": persona_id,
            "errors": identity_errors,
        })
    nodes = document.get("nodes") or list((document.get("node_by_id") or {}).values())
    edges = document.get("edges") or []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    gallery_ids = {
        node_id for node_id, node in by_id.items()
        if str(node.get("node_type") or "").lower() == "gallery"
    }
    granted = {
        str(edge.get("source"))
        for edge in edges
        if edge.get("relation_type") == "publishes_to"
        and str(edge.get("target")) in gallery_ids
        and edge.get("source") in by_id
    }
    allowed: dict[str, set[str]] = {}
    asset_registry_ids: set[str] = set()
    for node_id in granted:
        node = by_id[node_id]
        allowed.setdefault(str(node.get("node_type") or ""), set()).add(str(node.get("slug") or ""))
        if node.get("node_type") == "asset":
            registry_id = _asset_registry_id(node)
            if registry_id:
                asset_registry_ids.add(registry_id)

    # An active but malformed publication must fail closed.  Falling back to a
    # Graph JSON snapshot here would combine two independently versioned
    # authorities and could expose staged content.
    return {
        "publication_id": str(publication.get("id") or ""),
        "version": publication.get("version"),
        "checksum": publication.get("checksum") or document.get("checksum"),
        "action": None,
        "action_node_id": sorted(gallery_ids)[0] if gallery_ids else None,
        "allowed": allowed,
        "asset_registry_ids": asset_registry_ids,
        "granted_node_ids": granted,
        "source": "graph_publication_v3",
        "document": document,
    }


def _public_graph_context(persona_slug: str, persona_id: Optional[str] = None) -> Optional[dict]:
    """Return active v3 Gallery grants, with 2.1 only as a legacy fallback."""
    if persona_id:
        active = _active_publication_context(persona_id, persona_slug)
        if active is not None:
            return active
    try:
        current = graph_json_v2_store.load_current(persona_slug)
    except Exception:
        return None
    if not current or current[1].schema_version != "2.1":
        return None
    version, graph = current
    graph = graph_json_v21_adapter.upgrade_to_v21(graph)
    action = next(
        (
            node for node in graph.nodes
            if node.node_type == "gallery" and node.action and node.action.enabled
            and node.action.destination_type == "public_site"
        ),
        None,
    )
    if action is None:
        return {"version": version, "checksum": graph.content_checksum, "action": None, "allowed": {}}
    by_id = {node.id: node for node in graph.nodes}
    granted = {
        edge.source for edge in graph.edges
        if edge.relation_type == "publishes_to"
        and edge.target == action.id
        and edge.lifecycle.status == "active"
        and by_id.get(edge.source)
        and by_id[edge.source].lifecycle.status in {"approved", "active"}
    }
    allowed: dict[str, set[str]] = {}
    asset_registry_ids: set[str] = set()
    for node_id in granted:
        node = by_id[node_id]
        allowed.setdefault(node.node_type, set()).add(node.slug)
        if node.node_type == "asset":
            blob = (node.spec or {}).get("blob") or {}
            registry_id = blob.get("registry_id") or (node.spec or {}).get("registry_id")
            if registry_id:
                asset_registry_ids.add(str(registry_id))
    return {
        "publication_id": None,
        "version": version,
        "checksum": graph.content_checksum or graph_json_v2_store.checksum_graph(graph),
        "action": action,
        "allowed": allowed,
        "asset_registry_ids": asset_registry_ids,
        "action_node_id": action.id if action else None,
        "source": "graph_json_v21_legacy",
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


def _configured_public_asset_buckets() -> frozenset[str]:
    configured = os.environ.get("BRAIN_PUBLIC_ASSET_BUCKETS")
    if not configured:
        return _DEFAULT_PUBLIC_ASSET_BUCKETS
    return frozenset(value.strip() for value in configured.split(",") if value.strip())


def _storage_location(asset: dict) -> tuple[Optional[str], Optional[str]]:
    meta = asset.get("metadata") or {}
    bucket = asset.get("storage_bucket") or meta.get("storage_bucket")
    path = asset.get("storage_path") or meta.get("storage_path")
    file_path = asset.get("file_path") or meta.get("file_path")
    if (
        (not bucket or not path)
        and isinstance(file_path, str)
        and ":" in file_path
        and not file_path.startswith(("http://", "https://"))
    ):
        file_bucket, file_storage_path = file_path.split(":", 1)
        bucket = bucket or file_bucket
        path = path or file_storage_path
    return (str(bucket) if bucket else None, str(path) if path else None)


def _asset_url(asset: dict) -> str:
    """Use a stable URL for known-public buckets; preserve private signed URLs."""
    meta = asset.get("metadata") or {}
    fallback = asset.get("url") or meta.get("public_url") or meta.get("url") or ""
    bucket, path = _storage_location(asset)
    if not bucket or not path or bucket not in _configured_public_asset_buckets():
        return str(fallback or "")

    base = (os.environ.get("SUPABASE_PUBLIC_URL") or "").rstrip("/")
    if not base and fallback:
        parsed = urlsplit(str(fallback))
        if parsed.scheme and parsed.netloc and "/storage/v1/object/" in parsed.path:
            base = f"{parsed.scheme}://{parsed.netloc}"
    if not base:
        base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    if not base:
        return str(fallback or "")
    return (
        f"{base}/storage/v1/object/public/{quote(bucket, safe='')}/"
        f"{quote(path.lstrip('/'), safe='/%')}"
    )


def _stable_public_asset_url(asset: dict) -> str:
    """Return only durable HTTPS object URLs from explicitly public buckets."""
    bucket, path = _storage_location(asset)
    if not bucket or not path or bucket not in _configured_public_asset_buckets():
        return ""
    value = _asset_url(asset)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or "/storage/v1/object/public/" not in parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return value


def _published_assets_by_registry(
    persona_id: str,
    asset_registry_ids: set[str],
    cache: Optional[dict] = None,
) -> dict[str, dict]:
    """Resolve published blobs directly from assets, never from live graph rows."""
    cache_key = f"published_assets:{persona_id}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    rows = supabase_client.list_assets(persona_id=persona_id, limit=5000)
    result: dict[str, dict] = {}
    for row in rows:
        asset_id = str(row.get("id") or "")
        approval_status = str(row.get("approval_status") or "").lower()
        operational_status = str(row.get("status") or "").lower()
        if (
            not asset_id
            or asset_id not in asset_registry_ids
            or str(row.get("persona_id") or "") != persona_id
            or approval_status != "approved"
            or operational_status in {"archived", "rejected", "failed"}
        ):
            continue
        result[asset_id] = row
    if cache is not None:
        cache[cache_key] = result
    return result


def _positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _is_public_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


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
        "url": _asset_url(asset),
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
        "content_sha256": asset.get("content_sha256") or meta.get("content_sha256") or meta.get("sha256"),
        "width": _positive_int(asset.get("width") or meta.get("width")),
        "height": _positive_int(asset.get("height") or meta.get("height")),
    }


def _site_node_spec(node: dict, kind: str) -> dict:
    data = node.get("data") or {}
    public = data.get("public_site") if isinstance(data.get("public_site"), dict) else {}
    site = data.get("site") if isinstance(data.get("site"), dict) else {}
    specific = data.get(f"public_site_{kind}") or data.get(kind)
    return {
        **public,
        **site,
        **(specific if isinstance(specific, dict) else {}),
    }


def _site_ref_spec(raw: Any, nodes: dict[str, dict], kind: str, errors: list[str]) -> tuple[Optional[dict], dict]:
    ref = raw if isinstance(raw, str) else (raw or {}).get("node_id")
    node = nodes.get(str(ref or ""))
    if not node:
        errors.append(f"{kind}_node_missing:{ref or 'empty'}")
        return None, {}
    inline = raw if isinstance(raw, dict) else {}
    return node, {**inline, **_site_node_spec(node, kind)}


def _required_text(spec: dict, key: str, path: str, errors: list[str]) -> str:
    value = str(spec.get(key) or "").strip()
    if not value:
        errors.append(f"{path}.{key}:required")
    return value


def _required_natural_message(spec: dict, key: str, path: str, errors: list[str]) -> str:
    value = _required_text(spec, key, path, errors)
    if _TECHNICAL_ID_PATTERN.search(value):
        errors.append(f"{path}.{key}:technical_id_forbidden")
    return value


def _site_asset(
    raw: Any,
    *,
    nodes: dict[str, dict],
    gallery_by_node: dict[str, dict],
    granted_asset_ids: set[str],
    path: str,
    errors: list[str],
) -> Optional[dict]:
    node, spec = _site_ref_spec(raw, nodes, "asset", errors)
    if not node:
        return None
    if node.get("node_type") != "asset":
        errors.append(f"{path}.node_type:asset_required")
        return None
    node_id = str(node.get("id") or "")
    registry_id = _asset_registry_id(node)
    by_registry = {
        str(row.get("id")): row
        for row in gallery_by_node.values()
        if row.get("id")
    }
    asset = gallery_by_node.get(str(node.get("projection_node_id") or ""))
    asset = asset or (by_registry.get(registry_id) if registry_id else None)
    if not registry_id or not asset or str(asset.get("id") or "") != registry_id:
        errors.append(f"{path}.asset_registry:approved_gallery_asset_required")
        return None
    if registry_id not in granted_asset_ids:
        errors.append(f"{path}.publishes_to:required")
    data = node.get("data") or {}
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    meta = asset.get("metadata") or {}
    content_sha256 = str(
        asset.get("content_sha256")
        or meta.get("content_sha256")
        or data.get("content_sha256")
        or media.get("sha256")
        or ""
    ).lower()
    url = _stable_public_asset_url(asset)
    if len(content_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in content_sha256):
        errors.append(f"{path}.content_sha256:invalid")
    if not url:
        errors.append(f"{path}.url:stable_public_https_required")
    return {
        "node_id": node_id,
        "asset_id": registry_id,
        "url": url,
        "alt": str(spec.get("alt") or node.get("title") or ""),
        "content_sha256": content_sha256,
        "width": _positive_int(asset.get("width") or meta.get("width") or media.get("width")),
        "height": _positive_int(asset.get("height") or meta.get("height") or media.get("height")),
    }


def _site_cta_variant(raw: Any) -> Optional[dict]:
    """Validate one {label, message_template} pair through the same guard.

    Shared by the default CTA and each `by_audience` override so a technical
    id can never leak through either path -- it is the same bracketed-ref
    risk either way, just keyed by audience instead of by node.
    """
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    message = str(raw.get("message_template") or "").strip()
    if not label or not message or _TECHNICAL_ID_PATTERN.search(message):
        return None
    return {"label": label, "message_template": message}


def _site_cta(node: dict) -> Optional[dict]:
    data = node.get("data") or {}
    public = data.get("public_site") if isinstance(data.get("public_site"), dict) else {}
    raw = public.get("cta") or data.get("cta")
    if not isinstance(raw, dict):
        return None
    base = _site_cta_variant(raw)
    if base is None:
        return None
    result = {
        # A CTA belongs to the compiled node that owns it.  Do not accept a
        # second, free-form node reference that could point outside the active
        # immutable document.
        "node_id": str(node.get("id") or "") or None,
        **base,
    }
    # `by_audience` lets the CTA wording itself declare the customer's
    # purchase profile (varejo vs atacado) so the model's semantic
    # classification picks it up from the customer's own first message,
    # with zero technical tags. It is an optional enhancement on top of the
    # required base CTA above: a variant that fails validation (or is
    # simply absent) drops silently and the base CTA still applies -- see
    # `_catalog_cta_errors`, which never inspects `by_audience`.
    raw_variants = raw.get("by_audience")
    if isinstance(raw_variants, dict):
        by_audience = {}
        for audience_slug, variant_raw in raw_variants.items():
            variant = _site_cta_variant(variant_raw)
            if variant is not None:
                by_audience[str(audience_slug)] = variant
        if by_audience:
            result["by_audience"] = by_audience
    return result


def _catalog_cta_errors(categories: list[dict]) -> list[str]:
    errors: list[str] = []
    for category in categories:
        if not category.get("cta"):
            errors.append(f"{category.get('id')}:cta_required")
        for product in category.get("products") or []:
            if product.get("assets") and not product.get("cta"):
                errors.append(f"{product.get('id')}:cta_required")
    return sorted(errors)


def _publication_grants(publication: dict, nodes: dict[str, dict], edges: list[dict]) -> set[str]:
    explicit = publication.get("granted_node_ids")
    if explicit is not None:
        return {str(value) for value in explicit}
    galleries = {
        node_id for node_id, node in nodes.items()
        if node.get("node_type") == "gallery"
    }
    return {
        str(edge.get("source"))
        for edge in edges
        if edge.get("relation_type") == "publishes_to"
        and str(edge.get("target")) in galleries
        and str(edge.get("source")) in nodes
    }


def _compiled_offer(node: dict, offer_node: dict | None = None) -> Optional[dict]:
    target = offer_node or node
    data = target.get("data") or {}
    metadata = target.get("metadata") or {}
    offer = normalize_offer(data, metadata)
    if offer is None:
        return None
    return {"amount": offer.amount, "currency": offer.currency}


def _compiled_asset_payload(
    node: dict,
    edge: dict,
    *,
    gallery_by_node: dict[str, dict],
    granted_node_ids: set[str],
    granted_asset_ids: set[str],
    alt: str,
    path: str,
    errors: list[str],
) -> Optional[dict]:
    node_id = str(node.get("id") or "")
    registry_id = _asset_registry_id(node)
    by_registry = {
        str(row.get("id")): row for row in gallery_by_node.values() if row.get("id")
    }
    row = gallery_by_node.get(str(node.get("projection_node_id") or ""))
    row = row or (by_registry.get(registry_id) if registry_id else None)
    if node_id not in granted_node_ids or not registry_id or registry_id not in granted_asset_ids:
        errors.append(f"{path}:asset_not_published")
        return None
    if not row or str(row.get("id") or "") != registry_id:
        errors.append(f"{path}:approved_gallery_asset_required")
        return None
    url = _stable_public_asset_url(row)
    if not url:
        errors.append(f"{path}:stable_public_https_required")
        return None
    data = node.get("data") or {}
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    metadata = row.get("metadata") or {}
    content_sha256 = (
        row.get("content_sha256") or metadata.get("content_sha256")
        or data.get("content_sha256") or media.get("sha256")
    )
    payload = _asset_payload({**row, "url": url}, alt=alt, edge=edge)
    payload.update({
        "url": url,
        "content_sha256": content_sha256,
        "width": _positive_int(row.get("width") or metadata.get("width") or media.get("width")),
        "height": _positive_int(row.get("height") or metadata.get("height") or media.get("height")),
    })
    return payload


def _compiled_catalog_payload(
    publication: dict,
    *,
    site: dict,
    persona: dict,
    persona_slug: str,
    cache: dict,
) -> dict:
    """Project the v3 catalog exclusively from the immutable publication."""
    document = publication.get("document") or {}
    nodes = {
        str(node.get("id")): node
        for node in (document.get("nodes") or list((document.get("node_by_id") or {}).values()))
        if node.get("id")
    }
    edges = [edge for edge in document.get("edges") or [] if isinstance(edge, dict)]
    granted_node_ids = _publication_grants(publication, nodes, edges)
    granted_asset_ids = {str(value) for value in publication.get("asset_registry_ids") or set()}
    gallery_by_node = _published_assets_by_registry(
        str(persona["id"]), granted_asset_ids, cache=cache,
    )
    errors: list[str] = []

    persona_node = next((node for node in nodes.values() if node.get("node_type") == "persona"), None)
    brands = [
        node for node_id, node in nodes.items()
        if node.get("node_type") == "brand" and node_id in granted_node_ids
    ]
    if len(brands) != 1:
        errors.append(f"site.catalog.brand_node_count:{len(brands)}")
        brand_node = {}
    else:
        brand_node = brands[0]
    brand_data = brand_node.get("data") or {}
    brand = {
        "id": str(brand_node.get("id") or ""),
        "slug": str(brand_node.get("slug") or ""),
        "name": str(brand_node.get("title") or brand_node.get("slug") or ""),
        "description": brand_node.get("summary") or None,
        "short_name": brand_data.get("short_name"),
        "wordmark": brand_data.get("wordmark"),
        "accent_color": brand_data.get("accent_color"),
        "node_id": brand_node.get("id"),
    }

    product_nodes = {
        node_id: node for node_id, node in nodes.items()
        if node.get("node_type") == "product" and node_id in granted_node_ids
    }
    group_nodes = {
        node_id: node for node_id, node in nodes.items()
        if node.get("node_type") == "product_group" and node_id in granted_node_ids
    }
    asset_nodes = {
        node_id: node for node_id, node in nodes.items() if node.get("node_type") == "asset"
    }
    copy_nodes = {
        node_id: node for node_id, node in nodes.items()
        if node.get("node_type") == "copy" and node_id in granted_node_ids
    }
    faq_nodes = {
        node_id: node for node_id, node in nodes.items()
        if node.get("node_type") == "faq" and node_id in granted_node_ids
    }
    offer_nodes = {
        node_id: node for node_id, node in nodes.items() if node.get("node_type") == "offer"
    }

    products_by_group: dict[str, list[str]] = {}
    related_by_product: dict[str, list[str]] = {}
    asset_edges_by_owner: dict[str, list[dict]] = {}
    offers_by_product: dict[str, list[dict]] = {}
    group_relations = {"product_group_has_product", "in_category", "category_has_product", "contains"}
    copy_relations = {"product_has_copy", "supports_copy", "offer_has_copy"}
    faq_relations = {"product_has_faq", "answers_question"}
    offer_relations = {"about_product"}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        relation = str(edge.get("relation_type") or "")
        if source in group_nodes and target in product_nodes and relation in group_relations:
            products_by_group.setdefault(source, []).append(target)
        elif target in group_nodes and source in product_nodes and relation in group_relations:
            products_by_group.setdefault(target, []).append(source)
        if relation in copy_relations | faq_relations:
            product_id = source if source in product_nodes else target if target in product_nodes else None
            related_id = target if product_id == source else source
            if product_id and related_id in nodes:
                related_by_product.setdefault(product_id, []).append(related_id)
        if relation in {"uses_asset", "brand_has_asset", "category_has_asset", "campaign_has_asset"}:
            if source in nodes and target in asset_nodes:
                asset_edges_by_owner.setdefault(source, []).append(edge)
        if relation in offer_relations and source in offer_nodes and target in product_nodes:
            offers_by_product.setdefault(target, []).append(offer_nodes[source])

    def _chosen_offer_target(product_id: str, node: dict) -> dict:
        """Public storefront shows the retail (varejo) price; wholesale needs
        an audience/quantity qualifier the anonymous carousel never has."""
        candidates = offers_by_product.get(product_id) or []
        by_channel = {str((c.get("data") or {}).get("channel") or ""): c for c in candidates}
        return by_channel.get("varejo") or (candidates[0] if candidates else node)

    def _product_offer(product_id: str, node: dict) -> Optional[dict]:
        return _compiled_offer(node, _chosen_offer_target(product_id, node))

    def _product_price_cents(product_id: str, node: dict) -> int:
        target = _chosen_offer_target(product_id, node)
        offer = normalize_offer(target.get("data") or {}, target.get("metadata") or {})
        return offer_to_price_cents(offer)

    seen_brand_assets: set[str] = set()
    for edge in asset_edges_by_owner.get(str(brand_node.get("id") or ""), []):
        slot = slot_for_metadata(edge.get("metadata") or {})
        if slot not in {LandingSlot.BRAND_LOGO, LandingSlot.BRAND_COVER, LandingSlot.BRAND_SECONDARY}:
            continue
        asset_node = asset_nodes.get(str(edge.get("target") or ""))
        registry_id = _asset_registry_id(asset_node or {})
        if not asset_node or not registry_id or registry_id in seen_brand_assets:
            continue
        payload = _compiled_asset_payload(
            asset_node, edge, gallery_by_node=gallery_by_node,
            granted_node_ids=granted_node_ids, granted_asset_ids=granted_asset_ids,
            alt=str(brand_node.get("title") or "Logo"), path=f"{brand_node.get('id')}.assets.{registry_id}",
            errors=errors,
        )
        if not payload:
            continue
        seen_brand_assets.add(registry_id)
        if slot == LandingSlot.BRAND_LOGO:
            brand["logo"] = {**payload, "type": "logo"}
        elif slot == LandingSlot.BRAND_COVER:
            brand["cover"] = {**payload, "type": "cover"}
        else:
            brand.setdefault("secondary_assets", []).append(payload)

    linked_products = {product_id for values in products_by_group.values() for product_id in values}
    for product_id in sorted(set(product_nodes) - linked_products):
        errors.append(f"{product_id}:published_group_relation_required")

    eligible_faq_ids = {str(value) for value in document.get("eligible_faq_node_ids") or []}
    compiled_products: dict[str, dict] = {}
    for product_id, node in product_nodes.items():
        data = node.get("data") or {}
        assets: list[dict] = []
        seen_assets: set[str] = set()
        for edge in asset_edges_by_owner.get(product_id, []):
            if edge.get("relation_type") != "uses_asset" or slot_for_metadata(edge.get("metadata") or {}) != LandingSlot.PRODUCT_IMAGE:
                continue
            asset_node = asset_nodes.get(str(edge.get("target") or ""))
            registry_id = _asset_registry_id(asset_node or {})
            if not asset_node or not registry_id or registry_id in seen_assets:
                continue
            payload = _compiled_asset_payload(
                asset_node, edge, gallery_by_node=gallery_by_node,
                granted_node_ids=granted_node_ids, granted_asset_ids=granted_asset_ids,
                alt=str(node.get("title") or ""), path=f"{product_id}.assets.{registry_id}", errors=errors,
            )
            if payload:
                assets.append(payload)
                seen_assets.add(registry_id)
        related = related_by_product.get(product_id, [])
        compiled_products[product_id] = {
            "id": product_id,
            "slug": str(node.get("slug") or product_id),
            "name": str(node.get("title") or node.get("slug") or "Produto"),
            "description": to_clean_markdown(node.get("summary") or data.get("description") or ""),
            "offer": _product_offer(product_id, node),
            "price_cents": _product_price_cents(product_id, node),
            "visible": data.get("visible") is not False,
            "position": _read_int(data.get("position") or data.get("sort_order"), 0),
            "cta": _site_cta(node),
            "copies": [_copy_payload(copy_nodes[value]) for value in related if value in copy_nodes],
            "faqs": [
                {**_faq_payload(faq_nodes[value]), "is_rag_eligible": value in eligible_faq_ids}
                for value in related if value in faq_nodes
            ],
            "assets": assets,
        }

    categories: list[dict] = []
    for group_id, node in group_nodes.items():
        data = node.get("data") or {}
        cover_payload = None
        for edge in sorted(
            asset_edges_by_owner.get(group_id, []),
            key=lambda item: _read_int(((item.get("metadata") or {}).get("page_binding") or {}).get("position"), 0),
        ):
            if slot_for_metadata(edge.get("metadata") or {}) != LandingSlot.PRODUCT_GROUP_COVER:
                continue
            asset_node = asset_nodes.get(str(edge.get("target") or ""))
            if not asset_node:
                continue
            cover_payload = _compiled_asset_payload(
                asset_node, edge, gallery_by_node=gallery_by_node,
                granted_node_ids=granted_node_ids, granted_asset_ids=granted_asset_ids,
                alt=str(node.get("title") or ""), path=f"{group_id}.cover", errors=errors,
            )
            if cover_payload:
                break
        products = sorted(
            [compiled_products[value] for value in products_by_group.get(group_id, []) if value in compiled_products],
            key=lambda item: item["position"],
        )
        if cover_payload is None:
            cover_payload = next((asset for product in products for asset in product["assets"]), None)
        categories.append({
            "id": group_id,
            "slug": str(node.get("slug") or group_id),
            "title": str(node.get("title") or node.get("slug") or group_id),
            "eyebrow": data.get("eyebrow") or data.get("category_eyebrow") or "",
            "cover": (cover_payload or {}).get("url") or "",
            "cover_alt": (cover_payload or {}).get("alt") or node.get("title") or "",
            "cover_asset_id": (cover_payload or {}).get("asset_id"),
            "cover_edge_id": (cover_payload or {}).get("edge_id"),
            "cover_slot_key": (cover_payload or {}).get("slot_key"),
            "cover_width": (cover_payload or {}).get("width"),
            "cover_height": (cover_payload or {}).get("height"),
            "visible": data.get("visible") is not False,
            "position": _read_int(data.get("position") or data.get("sort_order"), 0),
            "cta": _site_cta(node),
            "assets": [cover_payload] if cover_payload else [],
            "products": products,
        })
    categories.sort(key=lambda item: item["position"])

    collection_slug = str(site["default_collection_slug"])
    collection_assets: list[dict] = []
    seen_collection_assets: set[str] = set()
    for campaign_id, campaign in nodes.items():
        campaign_data = campaign.get("data") or {}
        if (
            campaign.get("node_type") != "campaign"
            or campaign_id not in granted_node_ids
            or (
                campaign.get("slug") != collection_slug
                and campaign_data.get("collection_slug") != collection_slug
            )
        ):
            continue
        for edge in asset_edges_by_owner.get(campaign_id, []):
            slot = slot_for_metadata(edge.get("metadata") or {})
            if slot not in {LandingSlot.HERO, LandingSlot.CAMPAIGN_FOOTER}:
                continue
            asset_node = asset_nodes.get(str(edge.get("target") or ""))
            registry_id = _asset_registry_id(asset_node or {})
            if not asset_node or not registry_id or registry_id in seen_collection_assets:
                continue
            payload = _compiled_asset_payload(
                asset_node, edge, gallery_by_node=gallery_by_node,
                granted_node_ids=granted_node_ids, granted_asset_ids=granted_asset_ids,
                alt=str(campaign.get("title") or site["name"]),
                path=f"{campaign_id}.assets.{registry_id}", errors=errors,
            )
            if payload:
                collection_assets.append({**payload, "type": "banner"})
                seen_collection_assets.add(registry_id)

    cta_errors = _catalog_cta_errors(categories)
    errors.extend(cta_errors)
    if errors:
        raise HTTPException(status_code=503, detail={
            "code": "public_site_contract_incomplete",
            "publication_id": publication.get("publication_id"),
            "graph_checksum": publication.get("checksum"),
            "errors": sorted(set(errors)),
        })

    collection_node = next(
        (
            node for node in nodes.values()
            if node.get("slug") == collection_slug
            and node.get("node_type") in {"product_collection", "campaign"}
        ),
        None,
    )
    collection_id = str((collection_node or {}).get("id") or f"collection:{collection_slug}")
    collection_title = str((collection_node or {}).get("title") or site["name"])
    collection = {
        "id": collection_id,
        "slug": collection_slug,
        "type": "catalog",
        "display_name": collection_title,
        "cover": next((item["cover"] for item in categories if item.get("cover")), ""),
        "assets": collection_assets,
        "briefing": None,
        "categories": categories,
    }
    return {
        "active_collection_id": collection_id,
        "persona": {
            "id": str(persona["id"]),
            "slug": persona_slug,
            "name": str((persona_node or {}).get("title") or site["name"]),
            "brand": brand,
            "collections": [collection],
        },
    }


def _canonical_site_from_publication(publication: dict, cache: dict) -> dict:
    document = publication.get("document") or {}
    nodes = {
        str(node.get("id")): node
        for node in (document.get("nodes") or list((document.get("node_by_id") or {}).values()))
        if node.get("id")
    }
    persona_nodes = [node for node in nodes.values() if node.get("node_type") == "persona"]
    errors: list[str] = []
    if len(persona_nodes) != 1:
        errors.append(f"persona_node_count:{len(persona_nodes)}")
        persona_node = {}
    else:
        persona_node = persona_nodes[0]
    root = (persona_node.get("data") or {}).get("public_site")
    if not isinstance(root, dict):
        root = {}
        errors.append("persona.data.public_site:required")

    persona_id = str((document.get("persona") or {}).get("id") or "")
    granted_asset_ids = set(publication.get("asset_registry_ids") or set())
    gallery_by_node = _published_assets_by_registry(persona_id, granted_asset_ids, cache=cache)
    slug = _required_text(root, "slug", "site", errors)
    name = _required_text(root, "name", "site", errors)
    format_key = _required_text(root, "format_key", "site", errors)
    default_collection_slug = _required_text(root, "default_collection_slug", "site", errors)
    brand_family = _required_text(root, "brand_family", "site", errors)
    brand_channel = _required_text(root, "brand_channel", "site", errors)

    whatsapp_raw = root.get("whatsapp") if isinstance(root.get("whatsapp"), dict) else {}
    phone = public_site.normalize_whatsapp_phone(whatsapp_raw.get("phone"))
    message_template = _required_natural_message(whatsapp_raw, "message_template", "site.whatsapp", errors)
    if len(phone) < 8:
        errors.append("site.whatsapp.phone:invalid")

    identity_raw = root.get("identity") if isinstance(root.get("identity"), dict) else {}
    identity: dict[str, dict] = {}
    for key in ("logo_round", "logo_wordmark", "logo_reverse"):
        asset = _site_asset(
            identity_raw.get(key), nodes=nodes, gallery_by_node=gallery_by_node,
            granted_asset_ids=granted_asset_ids,
            path=f"site.identity.{key}", errors=errors,
        )
        if asset:
            asset.pop("width", None)
            asset.pop("height", None)
            identity[key] = asset
    # A short/icon-only mark is a rollout-in-progress enhancement, not part of
    # the required identity contract: unlike the three above, its absence
    # must never turn into a `public_site_contract_incomplete` 503 for every
    # persona that hasn't authored one yet.
    if "logo_short" in identity_raw:
        short_errors: list[str] = []
        short_asset = _site_asset(
            identity_raw.get("logo_short"), nodes=nodes, gallery_by_node=gallery_by_node,
            granted_asset_ids=granted_asset_ids,
            path="site.identity.logo_short", errors=short_errors,
        )
        if short_asset:
            short_asset.pop("width", None)
            short_asset.pop("height", None)
            identity["logo_short"] = short_asset

    pages = []
    for index, raw in enumerate(root.get("pages") or []):
        node, spec = _site_ref_spec(raw, nodes, "page", errors)
        if not node:
            continue
        if node.get("node_type") != "campaign":
            errors.append(f"site.pages[{index}].node_type:campaign_required")
        route = _required_text(spec, "route", f"site.pages[{index}]", errors)
        kind = str(spec.get("kind") or "")
        if not route.startswith("/"):
            errors.append(f"site.pages[{index}].route:invalid")
        if kind not in {"linktree", "showcase"}:
            errors.append(f"site.pages[{index}].kind:invalid")
        actions = []
        for action_index, action in enumerate(spec.get("actions") or []):
            action = action if isinstance(action, dict) else {}
            action_kind = str(action.get("kind") or "")
            if action_kind not in {"internal", "whatsapp", "location", "disabled"}:
                errors.append(f"site.pages[{index}].actions[{action_index}].kind:invalid")
            action_node_id = action.get("node_id")
            if action_node_id and str(action_node_id) not in nodes:
                errors.append(f"site.pages[{index}].actions[{action_index}].node_id:missing")
            if action.get("message_template") and _TECHNICAL_ID_PATTERN.search(str(action["message_template"])):
                errors.append(f"site.pages[{index}].actions[{action_index}].message_template:technical_id_forbidden")
            actions.append({
                "id": _required_text(action, "id", f"site.pages[{index}].actions[{action_index}]", errors),
                "node_id": str(action_node_id) if action_node_id else None,
                "label": _required_text(action, "label", f"site.pages[{index}].actions[{action_index}]", errors),
                "kind": action_kind,
                "href": action.get("href"),
                "contact_key": action.get("contact_key"),
                "message_template": action.get("message_template"),
                "position": _read_int(action.get("position"), 0),
                "disabled": bool(action.get("disabled", False)),
            })
        sections = spec.get("sections") if isinstance(spec.get("sections"), dict) else None
        if kind == "showcase" or sections is not None:
            section_fields = {
                "audiences": ("eyebrow", "title"),
                "groups": ("eyebrow", "title", "item_eyebrow", "item_description"),
                "final_cta": ("title", "description", "action_label"),
            }
            if sections is None:
                errors.append(f"site.pages[{index}].sections:required")
            else:
                normalized_sections = {}
                for section, fields in section_fields.items():
                    block = sections.get(section) if isinstance(sections.get(section), dict) else {}
                    normalized_sections[section] = {
                        field: _required_text(
                            block, field, f"site.pages[{index}].sections.{section}", errors
                        )
                        for field in fields
                    }
                sections = normalized_sections
        pages.append({
            "node_id": str(node["id"]),
            "route": route,
            "kind": kind,
            "eyebrow": spec.get("eyebrow"),
            "title": _required_text(spec, "title", f"site.pages[{index}]", errors),
            "description": _required_text(spec, "description", f"site.pages[{index}]", errors),
            "cta_label": spec.get("cta_label"),
            "ribbon_terms": [str(value) for value in spec.get("ribbon_terms") or [] if str(value).strip()],
            "actions": sorted(actions, key=lambda row: row["position"]),
            "sections": sections,
        })
    if len(pages) < 2:
        errors.append("site.pages:min_2")

    contacts = []
    for index, raw in enumerate(root.get("contacts") or []):
        node, spec = _site_ref_spec(raw, nodes, "contact", errors)
        if not node:
            continue
        if node.get("node_type") != "copy":
            errors.append(f"site.contacts[{index}].node_type:copy_required")
        contact_phone = public_site.normalize_whatsapp_phone(spec.get("phone"))
        if len(contact_phone) < 8:
            errors.append(f"site.contacts[{index}].phone:invalid")
        contacts.append({
            "key": _required_text(spec, "key", f"site.contacts[{index}]", errors),
            "node_id": str(node["id"]),
            "label": _required_text(spec, "label", f"site.contacts[{index}]", errors),
            "phone": contact_phone,
            "message_template": _required_natural_message(spec, "message_template", f"site.contacts[{index}]", errors),
            "position": _read_int(spec.get("position"), 0),
        })
    if not contacts:
        errors.append("site.contacts:min_1")

    covers = []
    for index, raw in enumerate(root.get("covers") or []):
        asset = _site_asset(
            raw, nodes=nodes, gallery_by_node=gallery_by_node,
            granted_asset_ids=granted_asset_ids,
            path=f"site.covers[{index}]", errors=errors,
        )
        if not asset:
            continue
        spec = raw if isinstance(raw, dict) else {}
        position = _read_int(spec.get("position"), 0)
        if position < 0 or position > 2:
            errors.append(f"site.covers[{index}].position:invalid")
        asset.pop("width", None)
        asset.pop("height", None)
        focal_point = spec.get("focal_point") if isinstance(spec.get("focal_point"), dict) else {}
        if focal_point.get("desktop") != "full" or focal_point.get("mobile") != "split-halves":
            errors.append(f"site.covers[{index}].focal_point:invalid")
        asset.update({
            "position": position,
            "focal_point": focal_point,
        })
        covers.append(asset)
    if not covers:
        errors.append("site.covers:min_1")

    audiences = []
    for index, raw in enumerate(root.get("audiences") or []):
        node, spec = _site_ref_spec(raw, nodes, "audience", errors)
        if not node:
            continue
        if node.get("node_type") != "audience":
            errors.append(f"site.audiences[{index}].node_type:audience_required")
        audiences.append({
            "node_id": str(node["id"]),
            "label": _required_text(spec, "label", f"site.audiences[{index}]", errors),
            "message_template": _required_natural_message(spec, "message_template", f"site.audiences[{index}]", errors),
            "position": _read_int(spec.get("position"), 0),
        })
    if not audiences:
        errors.append("site.audiences:min_1")

    locations = []
    for index, raw in enumerate(root.get("locations") or []):
        node, spec = _site_ref_spec(raw, nodes, "location", errors)
        if not node:
            continue
        node_data = node.get("data") or {}
        node_metadata = node_data.get("metadata") if isinstance(node_data.get("metadata"), dict) else {}
        if (
            node.get("node_type") != "campaign"
            or str(node_data.get("campaign_subtype") or node_metadata.get("campaign_subtype") or "") != "physical_store"
        ):
            errors.append(f"site.locations[{index}].node_type:physical_store_campaign_required")
        coords = spec.get("coordinates") if isinstance(spec.get("coordinates"), dict) else {}
        try:
            latitude = float(coords.get("latitude"))
            longitude = float(coords.get("longitude"))
        except (TypeError, ValueError):
            latitude = longitude = 999.0
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            errors.append(f"site.locations[{index}].coordinates:invalid")
        validation_status = str(spec.get("validation_status") or "pending")
        if validation_status not in {"pending", "validated"}:
            errors.append(f"site.locations[{index}].validation_status:invalid")
        map_spec = spec.get("map") if isinstance(spec.get("map"), dict) else {}
        for field in ("zoom", "min_zoom", "max_zoom"):
            if field in map_spec:
                try:
                    float(map_spec[field])
                except (TypeError, ValueError):
                    errors.append(f"site.locations[{index}].map.{field}:invalid")
        map_payload = {
            "style_url": map_spec.get("style_url"),
            "zoom": _number(map_spec.get("zoom"), 15.5),
            "min_zoom": _number(map_spec.get("min_zoom"), 11),
            "max_zoom": _number(map_spec.get("max_zoom"), 18),
        }
        if not all(0 <= map_payload[key] <= 24 for key in ("zoom", "min_zoom", "max_zoom")):
            errors.append(f"site.locations[{index}].map:zoom_invalid")
        if map_payload["min_zoom"] > map_payload["max_zoom"]:
            errors.append(f"site.locations[{index}].map:zoom_range_invalid")
        google_maps_url = _required_text(spec, "google_maps_url", f"site.locations[{index}]", errors)
        google_business_url = spec.get("google_business_url")
        style_url = map_payload.get("style_url")
        if google_maps_url and not _is_public_url(google_maps_url):
            errors.append(f"site.locations[{index}].google_maps_url:invalid")
        if google_business_url and not _is_public_url(google_business_url):
            errors.append(f"site.locations[{index}].google_business_url:invalid")
        if style_url and not _is_public_url(style_url):
            errors.append(f"site.locations[{index}].map.style_url:invalid")
        ui_theme = spec.get("ui_theme") if isinstance(spec.get("ui_theme"), dict) else {}
        marker_color = ui_theme.get("marker_color")
        if marker_color and (
            not isinstance(marker_color, str)
            or len(marker_color) != 7
            or not marker_color.startswith("#")
            or any(char.lower() not in "0123456789abcdef" for char in marker_color[1:])
        ):
            errors.append(f"site.locations[{index}].ui_theme.marker_color:invalid")
        locations.append({
            "node_id": str(node["id"]),
            "label": _required_text(spec, "label", f"site.locations[{index}]", errors),
            "address": _required_text(spec, "address", f"site.locations[{index}]", errors),
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "validation_status": validation_status,
            "google_maps_url": google_maps_url,
            "google_business_url": google_business_url,
            "ui_theme": ui_theme,
            "map": map_payload,
        })
    if not locations:
        errors.append("site.locations:min_1")

    if errors:
        raise HTTPException(status_code=503, detail={
            "code": "public_site_contract_incomplete",
            "publication_id": publication.get("publication_id"),
            "graph_checksum": publication.get("checksum"),
            "errors": sorted(set(errors)),
        })
    return {
        "slug": slug,
        "name": name,
        "format_key": format_key,
        "default_collection_slug": default_collection_slug,
        "brand_family": brand_family,
        "brand_channel": brand_channel,
        "whatsapp": {
            "phone": phone,
            "message_template": message_template,
            "href": public_site.whatsapp_href(phone, message_template),
        },
        "identity": identity,
        "pages": pages,
        "contacts": sorted(contacts, key=lambda row: row["position"]),
        "covers": sorted(covers, key=lambda row: row["position"]),
        "audiences": sorted(audiences, key=lambda row: row["position"]),
        "locations": locations,
    }


def _copy_payload(node: dict) -> dict:
    meta = node.get("data") if isinstance(node.get("data"), dict) else _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "slug": node.get("slug") or node.get("id") or "",
        "slot": meta.get("slot") or "body",
        # Copy bodies frequently arrive as HTML (Shopify/CMS). Clean to markdown
        # so no raw tags ever reach the cardapio, agents, or RAG.
        "body": to_clean_markdown(meta.get("body") or node.get("summary") or node.get("title") or ""),
    }


def _faq_payload(node: dict) -> dict:
    meta = node.get("data") if isinstance(node.get("data"), dict) else _meta(node)
    return {
        "id": node.get("id") or node.get("slug") or "",
        "slug": node.get("slug") or node.get("id") or "",
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
        relation_types=["uses_asset", "product_image", "product_has_asset"],
        limit=5000,
    )
    candidates: dict[tuple[str, str], tuple[tuple[int, int, str], dict]] = {}
    for edge in edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        product_id = source_id if source_id in product_ids else target_id if target_id in product_ids else None
        asset_node_id = target_id if product_id == source_id else source_id
        meta = edge.get("metadata") or {}
        if meta.get("active") is False:
            continue
        relation_type = edge.get("relation_type")
        if relation_type == "uses_asset":
            # uses_asset is generic (campaigns, brands and products all use
            # it).  It represents a product image only with an explicit slot,
            # and the canonical direction is product -> asset.
            if source_id != product_id or slot_for_metadata(meta) != LandingSlot.PRODUCT_IMAGE:
                continue
        # A public product image is valid only while it remains connected both
        # to the product and to the Gallery terminal.  This makes graph edits
        # immediately authoritative for the landing-page projection.
        asset = gallery_by_node.get(str(asset_node_id))
        if product_id and asset:
            asset_id = str(asset.get("id") or asset.get("knowledge_node_id") or asset_node_id)
            precedence = (
                0 if relation_type == "uses_asset"
                else 1 if relation_type == "product_image"
                else 2
            )
            binding = meta.get("page_binding") or {}
            rank = (precedence, _read_int(binding.get("position"), 0), str(edge.get("id") or ""))
            key = (str(product_id), asset_id)
            previous = candidates.get(key)
            if previous is None or rank < previous[0]:
                candidates[key] = (rank, {**asset, "_edge": edge})
    out: dict[str, list[dict]] = {}
    for (product_id, _asset_id), (rank, asset) in sorted(
        candidates.items(), key=lambda item: (item[0][0], item[1][0])
    ):
        asset["_rank"] = rank
        out.setdefault(product_id, []).append(asset)
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
        if not campaign_id or not asset_node_id:
            continue
        asset = gallery_by_node.get(str(asset_node_id))
        if not asset:
            continue
        asset_identity = str(asset.get("id") or asset.get("knowledge_node_id") or asset_node_id)
        if asset_identity in seen:
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
        seen.add(asset_identity)
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


def build_menu_payload(persona_slug: str, collection_slug: Optional[str] = None) -> dict:
    persona = _resolve_persona(persona_slug)
    persona_id = persona["id"]
    cache: dict = {}
    publication = _public_graph_context(persona_slug, persona_id)
    if publication and publication.get("source") == "graph_publication_v3":
        document_persona = ((publication.get("document") or {}).get("persona") or {})
        identity_errors = []
        if str(document_persona.get("id") or "") != str(persona_id):
            identity_errors.append("document.persona.id:mismatch")
        if str(document_persona.get("slug") or "") != persona_slug:
            identity_errors.append("document.persona.slug:mismatch")
        if identity_errors:
            raise HTTPException(status_code=503, detail={
                "code": "graph_publication_identity_invalid",
                "persona_id": persona_id,
                "errors": identity_errors,
            })
        canonical_site = _canonical_site_from_publication(publication, cache)
        if collection_slug is not None and collection_slug != canonical_site["default_collection_slug"]:
            raise HTTPException(404, f"Collection not found in active publication: {collection_slug}")
        catalog = _compiled_catalog_payload(
            publication, site=canonical_site, persona=persona,
            persona_slug=persona_slug, cache=cache,
        )
        payload = {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "site": canonical_site,
            **catalog,
            "publication_id": publication.get("publication_id"),
            "graph_version": publication.get("version"),
            "graph_checksum": publication.get("checksum"),
            "action_node_id": publication.get("action_node_id"),
        }
        payload["projection_checksum"] = _canonical_json_checksum(payload)
        return payload
    effective_collection_slug = collection_slug or _default_collection_slug(persona, persona_slug)

    # Try to find an explicit collection node. Migration 039 canonicalized
    # product_collection -> product_group, so try the legacy alias first and
    # then the canonical type. When no anchor node exists we still serve the
    # persona's product_groups + products under a synthetic container so
    # universal personas (vz-lupas, etc.) work without seeding extra rows.
    collection = supabase_client.get_knowledge_node_by_slug(
        effective_collection_slug,
        persona_id=persona_id,
        node_type="product_collection",
    ) or supabase_client.get_knowledge_node_by_slug(
        effective_collection_slug,
        persona_id=persona_id,
        node_type="product_group",
    )
    synthesized_collection = False
    if not collection:
        if collection_slug is not None:
            # Caller asked for a specific collection we cannot resolve.
            raise HTTPException(404, f"Collection not found: {collection_slug}")
        synthesized_collection = True
        collection = {
            "id": f"persona:{persona_id}:cardapio",
            "slug": effective_collection_slug,
            "title": persona.get("name") or persona_slug,
            "metadata": {
                "collection_type": "menu",
                "display_name": persona.get("name") or persona_slug,
                "synthesized": True,
            },
        }

    # Categories = canonical product_group nodes for this persona. When a
    # collection_slug filter is provided AND any group carries that slug in
    # metadata, narrow to that subset; otherwise show every product_group.
    all_groups = supabase_client.list_product_collection_nodes(
        persona_id=persona_id,
        node_type="product_group",
        limit=500,
    )
    # Archived legacy groups remain in the database until the destructive
    # cleanup window. They must not leak into the public menu projection.
    all_groups = [
        row for row in all_groups
        if str(row.get("status") or "").lower() != "archived"
    ]
    filtered_groups = [
        row for row in all_groups
        if _meta(row).get("collection_slug") == effective_collection_slug
    ]
    categories = filtered_groups if filtered_groups else all_groups

    products = supabase_client.list_product_nodes(
        persona_id=persona_id,
        collection_slug=effective_collection_slug if filtered_groups else None,
        limit=1000,
    )
    # When no metadata.collection_slug filter narrowed the result, list every
    # product for the persona so canonical edges can still bind them to a group.
    if not products:
        products = supabase_client.list_product_nodes(persona_id=persona_id, limit=1000)
    products_by_category: dict[str, list[dict]] = {}
    product_assets = _product_assets(products, persona_id, cache=cache)
    product_related, related_node_map = _related_nodes(products, ["product_has_copy", "supports_copy", "product_has_faq", "offer_has_copy"])
    all_faq_nodes = [node for node in related_node_map.values() if node.get("node_type") == "faq"]
    embedded_faq_ids = _embedded_faq_ids(all_faq_nodes)
    product_to_group_id = {
        product_id: group_id
        for group_id, product_ids in _products_by_group(products, [row["id"] for row in categories if row.get("id")]).items()
        for product_id in product_ids
    }
    categories_by_id = {row["id"]: row for row in categories if row.get("id")}
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
        # Both price_cents and offer must come from the same normalized offer
        # (never metadata["price_cents"] / metadata["price"] read separately):
        # vz-lupas only writes metadata.price -> price_cents used to default to
        # 0; Baita only writes metadata.price_cents -> offer used to be None.
        legacy_offer = normalize_offer(product.get("data") or {}, metadata)
        product_payload = {
            "id": product["id"],
            "slug": product.get("slug") or product["id"],
            "name": product.get("title") or product.get("slug") or "Produto",
            "price_cents": offer_to_price_cents(legacy_offer),
            # Offer = preco/kits/variacoes comerciais, normalizado -> nunca
            # inventar preco quando ausente.
            "offer": (
                {"amount": legacy_offer.amount, "currency": legacy_offer.currency}
                if legacy_offer is not None else None
            ),
            # Limpa HTML importado -> markdown enxuto (sem tags cruas).
            "description": to_clean_markdown(product.get("summary") or metadata.get("description") or ""),
            "visible": metadata.get("visible") is not False and product.get("status") != "archived",
            "position": _read_int(metadata.get("position"), 0),
            "copies": [_copy_payload(node) for node in copy_nodes],
            "faqs": [_faq_payload(node) for node in faq_nodes],
            "assets": [
                _asset_payload(asset, alt=product.get("title") or "", edge=asset.get("_edge"))
                for asset in product_assets.get(product["id"], [])
            ],
        }
        # Resolve product -> category via canonical edge first, then metadata.
        group_id = product_to_group_id.get(product["id"])
        category_slug: Optional[str] = None
        if group_id and group_id in categories_by_id:
            group_row = categories_by_id[group_id]
            category_slug = group_row.get("slug") or _meta(group_row).get("category_slug")
        if not category_slug:
            category_slug = (
                metadata.get("category_slug")
                or metadata.get("product_group_slug")
                or metadata.get("parent_group")
                or "sem-categoria"
            )
        products_by_category.setdefault(str(category_slug), []).append(product_payload)

    covers = _category_cover_assets(categories, persona_id, cache=cache)
    category_payloads = []
    for category in categories:
        metadata = _meta(category)
        cover_asset = covers.get(category["id"])
        cover_edge = (cover_asset or {}).get("_edge") if cover_asset else None
        category_slug = category.get("slug") or metadata.get("category_slug") or category["id"]
        cover_url = (cover_asset or {}).get("url") or ""
        # Fallback: toda categoria deve ter capa. Sem cover dedicado, usa a
        # primeira imagem de um produto interno do grupo (os assets de produto
        # ja foram resolvidos em products_by_category acima).
        if not cover_url:
            for product in products_by_category.get(str(category_slug), []):
                product_cover = next((a.get("url") for a in product.get("assets") or [] if a.get("url")), None)
                if product_cover:
                    cover_url = product_cover
                    break
        category_payload = {
            "id": category["id"],
            "slug": category_slug,
            "title": category.get("title") or category_slug,
            "eyebrow": metadata.get("eyebrow") or metadata.get("category_eyebrow") or "",
            "cover": cover_url,
            "cover_alt": (cover_asset or {}).get("title") or category.get("title") or category_slug,
            "cover_asset_id": (cover_asset or {}).get("id") if cover_asset else None,
            "cover_edge_id": (cover_edge or {}).get("id") if cover_edge else None,
            "cover_slot_key": LandingSlot.PRODUCT_GROUP_COVER.value if cover_asset else None,
            "cover_width": _positive_int((cover_asset or {}).get("width") or _meta(cover_asset).get("width")),
            "cover_height": _positive_int((cover_asset or {}).get("height") or _meta(cover_asset).get("height")),
            "visible": metadata.get("visible") is not False and category.get("status") != "archived",
            "position": _read_int(metadata.get("position") or metadata.get("sort_order"), 0),
            "products": sorted(products_by_category.get(str(category_slug), []), key=lambda row: row.get("position", 0)),
        }
        category_payloads.append(category_payload)

    collection_meta = _meta(collection)
    collection_cover = ""
    sorted_categories = sorted(category_payloads, key=lambda row: row.get("position", 0))
    for category in sorted_categories:
        if category.get("cover"):
            collection_cover = category["cover"]
            break
    collection_assets = _collection_campaign_assets(collection, persona_id, cache=cache)
    campaign_display_name = (
        collection_meta.get("campaign_name")
        or collection_meta.get("display_name")
        or collection.get("title")
        or "Cardapio"
    )
    persona_display_name = persona.get("name") or persona_slug

    brand = _brand_payload(persona, persona_slug, cache=cache)
    # GraphBundle v3 owns the complete public-site contract.  The format
    # registry/persona config belongs only to the legacy path.
    formats = supabase_client.list_public_site_formats(enabled_only=True)

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_collection_id": collection["id"],
        "site": public_site.public_site_payload(
            persona, formats, catalog_url=persona.get("catalog_url"),
        ),
        "persona": {
            "id": persona_id,
            "slug": persona_slug,
            "name": persona_display_name,
            "brand": brand,
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
    if publication is not None:
        action = publication.get("action")
        allowed = publication.get("allowed") or {}
        asset_ids = publication.get("asset_registry_ids") or set()
        collection_payload = payload["persona"]["collections"][0]
        filtered_categories = []
        for category in collection_payload.get("categories") or []:
            if (
                category.get("cover_asset_id")
                and str(category.get("cover_asset_id")) not in asset_ids
            ):
                category.update({
                    "cover": "",
                    "cover_asset_id": None,
                    "cover_edge_id": None,
                    "cover_slot_key": None,
                    "cover_width": None,
                    "cover_height": None,
                })
            products = []
            for product in category.get("products") or []:
                if product.get("slug") not in allowed.get("product", set()):
                    continue
                product["copies"] = [
                    row for row in product.get("copies") or []
                    if row.get("slug") in allowed.get("copy", set())
                ]
                product["faqs"] = [
                    row for row in product.get("faqs") or []
                    if row.get("slug") in allowed.get("faq", set())
                ]
                product["assets"] = [
                    row for row in product.get("assets") or []
                    if str(row.get("asset_id") or row.get("id") or "") in asset_ids
                ]
                products.append(product)
            category["products"] = products
            if category.get("slug") in allowed.get("product_group", set()) or products:
                filtered_categories.append(category)
        collection_payload["categories"] = filtered_categories
        collection_payload["assets"] = [
            row for row in collection_payload.get("assets") or []
            if str(row.get("asset_id") or row.get("id") or "") in asset_ids
        ]
        if payload["persona"].get("brand", {}).get("slug") not in allowed.get("brand", set()):
            payload["persona"]["brand"] = {}
        if action and action.action:
            projection = action.action.projection.model_dump(mode="json")
            site = payload.get("site") or {}
            for key in ("site_slug", "site_name", "default_collection_slug"):
                if projection.get(key):
                    site[key] = projection[key]
            payload["site"] = site
        payload.update({
            "publication_id": publication.get("publication_id"),
            "graph_version": publication.get("version"),
            "graph_checksum": publication.get("checksum"),
            "action_node_id": publication.get("action_node_id") or (action.id if action else None),
        })
        payload["projection_checksum"] = _canonical_json_checksum(payload)
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
