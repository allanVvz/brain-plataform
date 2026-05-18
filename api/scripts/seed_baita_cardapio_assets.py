"""Seed Baita menu mock images as campaign assets.

Uploads local files to Supabase Storage, creates public.assets rows, mirrors
each file as a knowledge_node node_type='asset', links every asset to Gallery,
and links the 4 catalog product images to the matching product nodes.

Usage:
  cd api
  python scripts/seed_baita_cardapio_assets.py --image-dir "C:\\path\\to\\images"

Optional:
  --persona-slug baita-conveniencia
  --mapping C:\\path\\mapping.json

mapping.json shape:
{
  "licor-jagermeister-700ml": "jager.png",
  "patagonia-weisse-473ml": "patagonia.jpg",
  "avalie-e-ganhe-um-drink": "avalie.png"
}
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = API_DIR.parent
for path in (API_DIR, ROOT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from utils.tls import configure_trust_store

configure_trust_store()

from services import knowledge_graph, supabase_client


CARDAPIO_CAMPAIGN_SLUG = "cardapio-baita-v14"
AVALIE_CAMPAIGN_SLUG = "avalie-e-ganhe"
SEED_SOURCE = "baita_cardapio_seed"

IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp"]

CAMPAIGNS = {
    CARDAPIO_CAMPAIGN_SLUG: {
        "title": "Cardapio Baita v14",
        "summary": (
            "Campanha principal de catalogo/cardapio da Baita. Sofia deve usar "
            "os nomes dos arquivos mockados para reconhecer produtos, briefing, "
            "copy, FAQ e Gallery."
        ),
        "tags": ["baita", "cardapio", "catalogo", "v14"],
    },
    AVALIE_CAMPAIGN_SLUG: {
        "title": "Avalie e Ganhe",
        "summary": (
            "Campanha separada de incentivo: cliente avalia a Baita no Google, "
            "mostra a avaliacao para a equipe e ganha um drink."
        ),
        "tags": ["baita", "avaliacao", "google", "drink"],
    },
}

PRODUCT_ASSETS: list[dict[str, Any]] = [
    {
        "slug": "licor-jagermeister-700ml",
        "title": "Licor Jagermeister 700ml",
        "category_slug": "destilados-premium",
        "category_title": "Destilados Premium",
        "brief": "Licor premium para consumo bem gelado, shots e composicoes de bar.",
        "copy": "Jagermeister bem gelado para abrir a noite com intensidade.",
        "aliases": ["licor-jagermeister-700ml", "jagermeister", "jager", "yergermeter", "a-noite-pede", "destilados-premium"],
    },
    {
        "slug": "patagonia-weisse-473ml",
        "title": "Patagonia Weisse 473ml",
        "category_slug": "cervejas-premium",
        "category_title": "Cervejas Premium",
        "brief": "Cerveja de trigo premium, leve, refrescante e frutada.",
        "copy": "Patagonia Weisse: refrescancia de montanha no cardapio da Baita.",
        "aliases": ["patagonia-weisse-473ml", "patagonia", "patagonia-daytime", "weisse", "cervejas-premium"],
    },
    {
        "slug": "vinho-suspeito-750ml",
        "title": "Vinho Suspeito 750ml",
        "category_slug": "vinhos-e-espumantes",
        "category_title": "Vinhos e Espumantes",
        "brief": "Vinho natural/espumante nacional com linguagem descontraida e visual solar.",
        "copy": "Suspeito na mesa, brinde garantido: vinho leve para dividir.",
        "aliases": ["vinho-suspeito-750ml", "suspeito", "vinho-suspeito", "vinhos-espumantes"],
    },
    {
        "slug": "lagunitas-daytime-355ml",
        "title": "Lagunitas Daytime Session IPA 355ml",
        "category_slug": "cervejas-premium",
        "category_title": "Cervejas Premium",
        "brief": "Session IPA leve e aromatica para roles de dia e consumo refrescante.",
        "copy": "Lagunitas DayTime: Session IPA suave para todo role.",
        "aliases": ["lagunitas-daytime-355ml", "lagunitas-daytime", "lagunitas", "daytime", "session-ipa", "bateu-fome"],
    },
]

SUPPORT_ASSETS: list[dict[str, Any]] = [
    {
        "slug": "drink-jack-baita-hero",
        "title": "Drink Jack Baita - Hero",
        "campaign_slug": CARDAPIO_CAMPAIGN_SLUG,
        "asset_function": "menu_drink_hero",
        "usage": "Asset de apoio para abrir bloco de drinks/noite no cardapio; nao representa produto cadastrado.",
        "aliases": ["drink-jack-baita-hero", "jack-drink-hero", "jack-baita", "editorial-product-bg"],
    },
    {
        "slug": "drink-jack-baita-close",
        "title": "Drink Jack Baita - Close",
        "campaign_slug": CARDAPIO_CAMPAIGN_SLUG,
        "asset_function": "menu_drink_detail",
        "usage": "Asset de detalhe para Gallery e materiais de drinks; nao deve criar node produto.",
        "aliases": ["drink-jack-baita-close", "jack-drink-close", "drink-baita", "editorial-product-bg-2"],
    },
    {
        "slug": "baita-brand-dark-placeholder",
        "title": "Baita Brand Dark Placeholder",
        "campaign_slug": CARDAPIO_CAMPAIGN_SLUG,
        "asset_function": "brand_background",
        "usage": "Asset abstrato/escuro para fundo, transicao ou placeholder visual da marca no catalogo.",
        "aliases": ["baita-brand-dark-placeholder", "brand-dark", "placeholder", "baita-conveniencia-brand"],
    },
    {
        "slug": "baita-logo-b",
        "title": "Baita Logo B",
        "campaign_slug": CARDAPIO_CAMPAIGN_SLUG,
        "asset_function": "brand_logo",
        "usage": "Logo/assinatura Baita para materiais da Gallery e identidade do cardapio; nao representa produto.",
        "aliases": ["baita-logo-b", "logo-b", "baita-logo"],
    },
    {
        "slug": "baita-estrelas-decorativas",
        "title": "Baita Estrelas Decorativas",
        "campaign_slug": CARDAPIO_CAMPAIGN_SLUG,
        "asset_function": "decorative_element",
        "usage": "Elemento visual decorativo para composicoes da campanha cardapio; nao deve criar node produto.",
        "aliases": ["baita-estrelas-decorativas", "baita-asset-2estrelhas", "2estrelhas"],
    },
    {
        "slug": "avalie-e-ganhe-um-drink",
        "title": "Avalie e Ganhe um Drink",
        "campaign_slug": AVALIE_CAMPAIGN_SLUG,
        "asset_function": "campaign_key_visual",
        "usage": "Key visual da campanha Avalie e Ganhe; pertence a outra campanha e nao ao cardapio.",
        "aliases": ["avalie-e-ganhe-um-drink", "avalie-e-ganhe", "avalie"],
    },
]


def _load_mapping(path: Optional[str]) -> dict[str, str]:
    if not path:
        return {}
    import json

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("mapping must be a JSON object: slug_or_alias -> filename")
    return {str(k): str(v) for k, v in data.items()}


def _find_image(image_dir: Path, key: str, mapping: dict[str, str], aliases: Optional[list[str]] = None) -> Path:
    keys = [key, *(aliases or [])]
    for lookup_key in keys:
        if lookup_key in mapping:
            candidate = (image_dir / mapping[lookup_key]).resolve()
            if candidate.exists():
                return candidate
            raise FileNotFoundError(f"Mapped file not found for {lookup_key}: {candidate}")
    for lookup_key in keys:
        for ext in IMAGE_EXTS:
            candidate = image_dir / f"{lookup_key}{ext}"
            if candidate.exists():
                return candidate.resolve()
    stems = [
        (p, knowledge_graph._slugify(p.stem))
        for p in image_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    for lookup_key in keys:
        slug_key = knowledge_graph._slugify(lookup_key)
        matches = [p for p, stem in stems if slug_key and slug_key == stem]
        if matches:
            return matches[0].resolve()
    for lookup_key in keys:
        slug_key = knowledge_graph._slugify(lookup_key)
        matches = [p for p, stem in stems if slug_key and slug_key in stem]
        if matches:
            return matches[0].resolve()
    raise FileNotFoundError(f"No image found for {key} in {image_dir}")


def _maybe_find_image(
    image_dir: Path,
    key: str,
    mapping: dict[str, str],
    aliases: Optional[list[str]] = None,
    *,
    optional: bool = False,
) -> Optional[Path]:
    try:
        return _find_image(image_dir, key, mapping, aliases)
    except FileNotFoundError:
        if optional:
            return None
        raise


def _campaign_node(persona_id: str, persona_slug: str, campaign_slug: str) -> dict:
    spec = CAMPAIGNS[campaign_slug]
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "campaign",
        "slug": campaign_slug,
        "title": spec["title"],
        "summary": spec["summary"],
        "tags": ["campaign", *spec["tags"]],
        "metadata": {
            "persona_slug": persona_slug,
            "campaign_slug": campaign_slug,
            "source_file": "BAITA_MENU_SYSTEM_v14_2.md",
            "created_from": SEED_SOURCE,
        },
        "status": "pending_validation",
    })
    if not node:
        raise RuntimeError(f"Could not ensure campaign node: {campaign_slug}")
    return node


def _edge(source: dict, target: dict, relation_type: str, persona_id: str, *, weight: float = 0.75, primary: bool = False) -> Optional[dict]:
    return supabase_client.upsert_knowledge_edge(
        source["id"],
        target["id"],
        relation_type,
        persona_id=persona_id,
        weight=weight,
        metadata={"created_from": SEED_SOURCE, "primary_tree": primary, "active": True},
    )


def _ensure_campaign_support_nodes(persona_id: str, campaign: dict, collection: Optional[dict]) -> dict[str, dict]:
    campaign_slug = campaign["slug"]
    brief = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "briefing",
        "slug": f"briefing-{campaign_slug}",
        "title": f"Briefing {campaign['title']}",
        "summary": campaign.get("summary") or "",
        "tags": ["briefing", "baita", campaign_slug],
        "metadata": {"campaign_slug": campaign_slug, "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    copy = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "copy",
        "slug": f"copy-{campaign_slug}",
        "title": f"Copy {campaign['title']}",
        "summary": "Use os nomes cadastrados dos assets para responder como Sofia e encaminhar para FAQ/Gallery.",
        "tags": ["copy", "baita", campaign_slug],
        "metadata": {"campaign_slug": campaign_slug, "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    faq = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "faq",
        "slug": f"faq-{campaign_slug}",
        "title": f"FAQ {campaign['title']}",
        "summary": "FAQ de uso dos assets, nomes, produtos e destino Gallery da campanha.",
        "tags": ["faq", "baita", campaign_slug],
        "metadata": {"campaign_slug": campaign_slug, "question_count": 3, "routing": ["faq", "gallery"], "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    for child in [brief, copy, faq]:
        if child:
            _edge(campaign, child, "contains", persona_id, weight=0.76, primary=True)
    if faq:
        _edge(faq, campaign, "answers_question", persona_id, weight=0.8, primary=False)
    if collection and campaign_slug == CARDAPIO_CAMPAIGN_SLUG:
        _edge(campaign, collection, "contains", persona_id, weight=0.8, primary=True)
    return {"briefing": brief, "copy": copy, "faq": faq}


def _ensure_base_cardapio_nodes(persona_id: str, persona_slug: str) -> dict[str, Any]:
    persona_node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "persona",
        "slug": persona_slug,
        "title": "Baita Conveniencia",
        "summary": "Persona raiz da Baita Conveniencia para o seed do cardapio.",
        "tags": ["baita", "persona"],
        "metadata": {"persona_slug": persona_slug, "protected": True, "created_from": SEED_SOURCE},
        "status": "validated",
    })
    brand = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "brand",
        "slug": "baita",
        "title": "Baita",
        "summary": "Brand Baita conectada ao fluxo de produtos e campanhas.",
        "tags": ["baita", "brand"],
        "metadata": {"persona_slug": persona_slug, "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    collection = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "product_collection",
        "slug": CARDAPIO_CAMPAIGN_SLUG,
        "title": "Cardapio Baita v14",
        "summary": "Cardapio oficial da Baita Conveniencia, versao v14.",
        "tags": ["product_collection", "cardapio", "baita", "v14"],
        "metadata": {
            "collection_type": "menu",
            "display_name": "Cardapio Baita v14",
            "version": "v14",
            "source_file": "BAITA_MENU_SYSTEM_v14_2.md",
            "created_from": SEED_SOURCE,
        },
        "status": "pending_validation",
    })
    if persona_node and brand:
        _edge(persona_node, brand, "contains", persona_id, weight=1.0, primary=True)
    if brand and collection:
        _edge(brand, collection, "brand_has_collection", persona_id, weight=0.9, primary=True)

    categories: dict[str, dict] = {}
    products: dict[str, dict] = {}
    for spec in PRODUCT_ASSETS:
        cat_slug = spec["category_slug"]
        category = categories.get(cat_slug) or supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "category",
            "slug": cat_slug,
            "title": spec["category_title"],
            "summary": f"Categoria {spec['category_title']} do cardapio Baita v14.",
            "tags": ["baita", "category", cat_slug],
            "metadata": {"collection_slug": CARDAPIO_CAMPAIGN_SLUG, "created_from": SEED_SOURCE},
            "status": "pending_validation",
        })
        categories[cat_slug] = category
        if collection and category:
            _edge(collection, category, "collection_has_category", persona_id, weight=0.85, primary=True)

        product = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "product",
            "slug": spec["slug"],
            "title": spec["title"],
            "summary": spec["brief"],
            "tags": ["baita", "product", spec["slug"], cat_slug],
            "metadata": {
                "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
                "category_slug": cat_slug,
                "source_file": "BAITA_MENU_SYSTEM_v14_2.md",
                "created_from": SEED_SOURCE,
            },
            "status": "pending_validation",
        })
        products[spec["slug"]] = product
        if category and product:
            _edge(category, product, "category_has_product", persona_id, weight=0.86, primary=True)
        if product and collection:
            _edge(product, collection, "part_of_collection", persona_id, weight=0.7)
    return {"persona": persona_node, "brand": brand, "collection": collection, "categories": categories, "products": products}


def _ensure_product_support_nodes(persona_id: str, campaign: dict, product: dict, spec: dict[str, Any]) -> dict[str, dict]:
    brief = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "briefing",
        "slug": f"briefing-{product['slug']}",
        "title": f"Brief {product['title']}",
        "summary": spec["brief"],
        "tags": ["briefing", "baita", product["slug"]],
        "metadata": {"product_slug": product["slug"], "campaign_slug": campaign["slug"], "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    copy = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "copy",
        "slug": f"copy-{product['slug']}",
        "title": f"Copy {product['title']}",
        "summary": spec["copy"],
        "tags": ["copy", "baita", product["slug"]],
        "metadata": {"product_slug": product["slug"], "campaign_slug": campaign["slug"], "created_from": SEED_SOURCE},
        "status": "pending_validation",
    })
    for child in [brief, copy]:
        if child:
            relation_type = "briefed_by" if child["node_type"] == "briefing" else "product_has_copy"
            _edge(product, child, relation_type, persona_id, weight=0.78, primary=True)
            _edge(child, campaign, "part_of_campaign", persona_id, weight=0.72)
    return {"briefing": brief, "copy": copy}


def _create_asset_row(
    *,
    persona_id: str,
    persona_slug: str,
    image_path: Path,
    campaign_slug: str,
    asset_function: str,
    product_slug: Optional[str] = None,
    usage: Optional[str] = None,
) -> dict:
    content = image_path.read_bytes()
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    storage_bucket = "assets-raw"
    storage_path = f"{persona_id}/baita-cardapio-v14/{image_path.name}"
    try:
        existing_rows = (
            supabase_client.get_client()
            .table("assets")
            .select("*")
            .eq("persona_id", persona_id)
            .eq("storage_bucket", storage_bucket)
            .eq("storage_path", storage_path)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing_rows:
            return existing_rows[0]
    except Exception:
        pass
    url = supabase_client.upload_to_storage(storage_bucket, storage_path, content, mime)
    metadata = {
        "persona_slug": persona_slug,
        "original_filename": image_path.name,
        "upload_context": SEED_SOURCE,
        "validation_status": "pending_validation",
        "campaign_slug": campaign_slug,
        "asset_function": asset_function,
    }
    if campaign_slug == CARDAPIO_CAMPAIGN_SLUG:
        metadata["collection_slug"] = CARDAPIO_CAMPAIGN_SLUG
    if product_slug:
        metadata["product_slug"] = product_slug
    if usage:
        metadata["asset_usage"] = usage
    asset = supabase_client.insert_asset({
        "persona_id": persona_id,
        "type": "image",
        "name": image_path.stem,
        "url": url,
        "metadata": metadata,
        "source": "imported",
        "storage_bucket": storage_bucket,
        "storage_path": storage_path,
        "mime_type": mime,
        "file_size": len(content),
        "original_filename": image_path.name,
        "status": "ready",
        "upload_context": "imported",
    })
    if not asset.get("id"):
        raise RuntimeError(f"Could not insert asset row for {image_path}")
    return asset


def _ensure_asset_node(
    asset: dict,
    persona_id: str,
    persona_slug: str,
    *,
    title: str,
    summary: str,
    parent: Optional[dict] = None,
) -> dict:
    metadata = asset.get("metadata") or {}
    slug_seed = asset.get("original_filename") or asset.get("name") or asset["id"]
    parent_meta = {}
    if parent:
        parent_meta = {
            "parent_node_id": parent.get("id"),
            "parent_slug": parent.get("slug"),
            "parent_type": parent.get("node_type"),
        }
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "source_table": "assets",
        "source_id": asset["id"],
        "node_type": "asset",
        "slug": f"{knowledge_graph._slugify(slug_seed)[:56]}-{asset['id'][:8]}",
        "title": title,
        "summary": summary,
        "tags": [
            "asset",
            "baita",
            metadata.get("campaign_slug") or CARDAPIO_CAMPAIGN_SLUG,
            "product_image" if metadata.get("product_slug") else "support_asset",
        ],
        "metadata": {
            **metadata,
            **parent_meta,
            "asset_id": asset["id"],
            "persona_slug": persona_slug,
            "storage_bucket": asset.get("storage_bucket"),
            "storage_path": asset.get("storage_path"),
            "file_path": f"{asset.get('storage_bucket')}:{asset.get('storage_path')}",
            "asset_type": asset.get("type") or "image",
            "open_url": "/marketing/assets",
        },
        "status": "active",
    })
    if not node:
        raise RuntimeError(f"Could not create asset node for {asset['id']}")
    return node


def _link_asset(
    *,
    persona_id: str,
    asset: dict,
    asset_node: dict,
    gallery: dict,
    campaign: dict,
    product: Optional[dict] = None,
) -> dict:
    gallery_edge = _edge(asset_node, gallery, "gallery_asset", persona_id, weight=0.9)
    campaign_edge = _edge(asset_node, campaign, "supports_campaign", persona_id, weight=0.8)
    _edge(campaign, asset_node, "uses_asset", persona_id, weight=0.72)
    parent_edge = None
    parent_node_id = None
    if product:
        parent_node_id = product["id"]
        parent_edge = supabase_client.upsert_knowledge_edge(
            asset_node["id"],
            product["id"],
            "product_image",
            persona_id=persona_id,
            weight=0.85,
            metadata={"status": "pending_validation", "proposed_by": "seed", "created_from": SEED_SOURCE, "primary_tree": False, "active": True},
        )
        _edge(product, asset_node, "product_has_asset", persona_id, weight=0.8, primary=True)
    supabase_client.update_asset_graph_refs(
        asset["id"],
        knowledge_node_id=asset_node["id"],
        gallery_edge_id=(gallery_edge or {}).get("id"),
        parent_node_id=parent_node_id,
        parent_edge_id=(parent_edge or campaign_edge or {}).get("id"),
    )
    return {
        "asset_id": asset["id"],
        "asset_node_id": asset_node["id"],
        "gallery_edge_id": (gallery_edge or {}).get("id"),
        "campaign_edge_id": (campaign_edge or {}).get("id"),
        "product_image_edge_id": (parent_edge or {}).get("id") if parent_edge else None,
    }


def seed_assets(image_dir: Path, persona_slug: str, mapping_path: Optional[str]) -> dict:
    mapping = _load_mapping(mapping_path)
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise RuntimeError(f"Persona not found: {persona_slug}")
    persona_id = persona["id"]
    gallery = supabase_client.ensure_gallery_node(persona_id)
    if not gallery:
        raise RuntimeError("Could not ensure Gallery node")

    base_nodes = _ensure_base_cardapio_nodes(persona_id, persona_slug)
    collection = base_nodes["collection"]
    campaigns = {
        slug: _campaign_node(persona_id, persona_slug, slug)
        for slug in (CARDAPIO_CAMPAIGN_SLUG, AVALIE_CAMPAIGN_SLUG)
    }
    for campaign in campaigns.values():
        _ensure_campaign_support_nodes(persona_id, campaign, collection)

    results = []
    for spec in PRODUCT_ASSETS:
        product = supabase_client.get_knowledge_node_by_slug(spec["slug"], persona_id=persona_id, node_type="product")
        product = product or (base_nodes.get("products") or {}).get(spec["slug"])
        if not product:
            raise RuntimeError(f"Product node not found and could not be created: {spec['slug']}")
        _ensure_product_support_nodes(persona_id, campaigns[CARDAPIO_CAMPAIGN_SLUG], product, spec)
        image_path = _find_image(image_dir, spec["slug"], mapping, spec.get("aliases"))
        asset = _create_asset_row(
            persona_id=persona_id,
            persona_slug=persona_slug,
            image_path=image_path,
            campaign_slug=CARDAPIO_CAMPAIGN_SLUG,
            asset_function="product_catalog_image",
            product_slug=spec["slug"],
            usage=f"Imagem principal de catalogo vinculada ao produto {product.get('title')}.",
        )
        asset_node = _ensure_asset_node(
            asset,
            persona_id,
            persona_slug,
            title=f"Asset {product.get('title')}",
            summary=f"Imagem mock definitiva para Sofia reconhecer {product.get('title')} no cardapio.",
            parent=product,
        )
        links = _link_asset(
            persona_id=persona_id,
            asset=asset,
            asset_node=asset_node,
            gallery=gallery,
            campaign=campaigns[CARDAPIO_CAMPAIGN_SLUG],
            product=product,
        )
        results.append({"kind": "product_asset", "product_slug": spec["slug"], "campaign_slug": CARDAPIO_CAMPAIGN_SLUG, "file": str(image_path), **links})

    for spec in SUPPORT_ASSETS:
        image_path = _maybe_find_image(
            image_dir,
            spec["slug"],
            mapping,
            spec.get("aliases"),
            optional=bool(spec.get("optional")),
        )
        if not image_path:
            results.append({"kind": "support_asset", "support_slug": spec["slug"], "skipped": True, "reason": "optional_file_not_found"})
            continue
        campaign = campaigns[spec["campaign_slug"]]
        asset = _create_asset_row(
            persona_id=persona_id,
            persona_slug=persona_slug,
            image_path=image_path,
            campaign_slug=spec["campaign_slug"],
            asset_function=spec["asset_function"],
            usage=spec["usage"],
        )
        asset_node = _ensure_asset_node(
            asset,
            persona_id,
            persona_slug,
            title=spec["title"],
            summary=spec["usage"],
            parent=campaign,
        )
        links = _link_asset(
            persona_id=persona_id,
            asset=asset,
            asset_node=asset_node,
            gallery=gallery,
            campaign=campaign,
            product=None,
        )
        results.append({"kind": "support_asset", "support_slug": spec["slug"], "campaign_slug": spec["campaign_slug"], "file": str(image_path), **links})

    active_results = [r for r in results if not r.get("skipped")]
    return {
        "ok": True,
        "persona_slug": persona_slug,
        "campaigns": sorted(campaigns),
        "count": len(active_results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--persona-slug", default=os.environ.get("BAITA_PERSONA_SLUG", "baita-conveniencia"))
    parser.add_argument("--mapping")
    args = parser.parse_args()

    load_dotenv()
    result = seed_assets(Path(args.image_dir).resolve(), args.persona_slug, args.mapping)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
