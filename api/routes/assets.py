# -*- coding: utf-8 -*-
"""Asset card upload & connect routes.

Two distinct flows are served by this module:

1. POST /assets/upload — Card ASSET. Multipart upload that:
   - stores the file in Supabase Storage (assets-raw bucket)
   - inserts public.assets row (upload_context='asset_card')
   - runs the asset_pipeline and writes public.asset_readings rows
   - creates knowledge_items (content_type='asset', status='pending')
   - bootstraps a knowledge_node node_type='asset' and edges:
       parent → asset      (relation_type='uses_asset')
       asset → gallery     (relation_type='gallery_asset')
   - never auto-creates knowledge_rag_entries (gated by is_rag_eligible)

2. The Sofia/CRIAR upload remains in /kb-intake/upload — it persists in
   public.assets only when the file can be tied to a persona and Graph evidence.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from core.landing_slots import (
    LandingSlot,
    edge_metadata_for_slot,
    slot_config,
    slot_for_key,
    slot_for_metadata,
)
from services import auth_service, knowledge_graph, supabase_client
from services.asset_pipeline import AssetPipelineContext, compose_markdown, run_pipeline

logger = logging.getLogger("routes.assets")

router = APIRouter(prefix="/assets", tags=["assets"])

# ── Type guards (Gallery only accepts asset connections) ─────────────────
_GALLERY_ONLY_FROM = {"asset"}


def _bundle_to_asset_type(kind: str) -> str:
    if kind.startswith("image"):
        return "image"
    if kind == "pdf":
        return "pdf"
    if kind == "video":
        return "video"
    if kind in ("text", "markdown"):
        return "text"
    return "image"


def _strip_gn_prefix(node_id: Optional[str]) -> Optional[str]:
    if not node_id:
        return None
    return node_id[3:] if node_id.startswith("gn:") else node_id


def _resolve_persona(persona_id: Optional[str], persona_slug: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if persona_id and persona_slug:
        return persona_id, persona_slug
    if persona_id and not persona_slug:
        persona = supabase_client.get_persona_by_id(persona_id) or {}
        return persona_id, persona.get("slug")
    if persona_slug and not persona_id:
        persona = supabase_client.get_persona(persona_slug) or {}
        return persona.get("id"), persona_slug
    return None, None


def _find_parent_node(persona_id: Optional[str], branch_hint: Optional[str]) -> Optional[dict]:
    """Look up a node by slug (or id) in the persona scope."""
    if not branch_hint:
        return None
    raw = _strip_gn_prefix(branch_hint) or ""
    # Try as id first.
    try:
        node = supabase_client.get_knowledge_node(raw)
        if node:
            return node
    except Exception:
        pass
    # Then by slug.
    try:
        return supabase_client.get_knowledge_node_by_slug(branch_hint, persona_id=persona_id)
    except Exception:
        return None


def _asset_graph_ref(asset: dict, key: str) -> Optional[str]:
    metadata = asset.get("metadata") or {}
    graph_meta = metadata.get("graph") or {}
    return asset.get(key) or metadata.get(key) or graph_meta.get(key)


def _asset_title(asset: dict, fallback: str = "Asset") -> str:
    return (
        asset.get("name")
        or asset.get("original_filename")
        or (asset.get("metadata") or {}).get("original_filename")
        or fallback
    )


def _ensure_asset_graph_contract(
    *,
    asset_id: str,
    asset_row: dict,
    persona_id: str,
    parent_node: dict,
    storage_bucket: Optional[str],
    storage_path: Optional[str],
    title: str,
    summary: str,
    slug_seed: str,
    asset_type: Optional[str],
    asset_function: Optional[str],
    tags: Optional[list[str]] = None,
    knowledge_item_id: Optional[str] = None,
    created_from: str = "asset_upload",
) -> dict:
    """Ensure every asset has branch -> asset and asset -> Gallery edges.

    This is intentionally strict for asset-card uploads: a file visible in
    marketing assets cannot be a detached database row.
    """
    if not asset_id:
        raise HTTPException(500, "Asset sem id nao pode ser conectado ao grafo.")
    if not persona_id:
        raise HTTPException(422, "Asset precisa de persona para entrar no grafo.")
    if not parent_node or not parent_node.get("id"):
        raise HTTPException(422, "Asset precisa de um braco do grafo como parent.")
    if (parent_node.get("node_type") or "").lower() in {"gallery", "embedded", "asset"}:
        raise HTTPException(422, "Asset deve ser conectado a campanha, produto, oferta, copy, briefing ou audiencia; nao a Gallery/Embedded/Asset.")

    existing_node = None
    existing_node_id = _asset_graph_ref(asset_row or {}, "knowledge_node_id")
    if existing_node_id:
        existing_node = supabase_client.get_knowledge_node(existing_node_id)
    if not existing_node:
        existing_node = supabase_client.get_knowledge_node_for_source("assets", asset_id, persona_id=persona_id)

    base_slug = knowledge_graph._slugify(slug_seed or title or asset_id)[:60] or "asset"
    node_payload = {
        "persona_id": persona_id,
        "source_table": "assets",
        "source_id": asset_id,
        "node_type": "asset",
        "slug": f"{base_slug}-{asset_id[:8]}",
        "title": title or _asset_title(asset_row),
        "summary": (summary or "")[:400] or None,
        "tags": tags or ["asset"],
        "metadata": {
            **((asset_row or {}).get("metadata") or {}),
            "asset_id": asset_id,
            "knowledge_item_id": knowledge_item_id,
            "storage_bucket": storage_bucket,
            "storage_path": storage_path,
            "file_path": f"{storage_bucket}:{storage_path}" if storage_bucket and storage_path else None,
            "asset_type": asset_type,
            "asset_function": asset_function,
            "parent_node_id": parent_node.get("id"),
            "parent_slug": parent_node.get("slug"),
            "parent_type": parent_node.get("node_type"),
            "open_url": "/marketing/assets",
        },
        "status": "active",
        "level": 108,
        "importance": 0.64,
        "confidence": 1.0,
    }
    node_payload["metadata"] = {k: v for k, v in node_payload["metadata"].items() if v is not None}
    asset_node = supabase_client.upsert_knowledge_node(node_payload)
    if not asset_node or not asset_node.get("id"):
        raise HTTPException(502, "Falha ao criar node de asset no Graph.")

    parent_edge = supabase_client.upsert_knowledge_edge(
        parent_node["id"],
        asset_node["id"],
        "uses_asset",
        persona_id=persona_id,
        weight=0.85,
        metadata={
            "created_from": created_from,
            "direction": "branch_to_asset",
            "primary_tree": True,
            "parent_slug": parent_node.get("slug"),
            "parent_type": parent_node.get("node_type"),
        },
    )
    if not parent_edge or not parent_edge.get("id"):
        raise HTTPException(502, "Falha ao conectar branch -> asset no Graph.")

    gallery_node = supabase_client.ensure_gallery_node(persona_id)
    if not gallery_node or not gallery_node.get("id"):
        raise HTTPException(502, "Falha ao criar node Gallery.")

    gallery_edge = supabase_client.upsert_knowledge_edge(
        asset_node["id"],
        gallery_node["id"],
        "gallery_asset",
        persona_id=persona_id,
        weight=0.9,
        metadata={
            "graph_layer": "auxiliary",
            "primary_tree": False,
            "visual_hidden": False,
            "relation_role": "asset_gallery",
            "created_from": created_from,
            "direction": "asset_to_gallery",
        },
    )
    if not gallery_edge or not gallery_edge.get("id"):
        raise HTTPException(502, "Falha ao conectar asset -> Gallery no Graph.")

    updated_asset = supabase_client.update_asset_graph_refs(
        asset_id,
        knowledge_node_id=asset_node["id"],
        gallery_edge_id=gallery_edge["id"],
        parent_node_id=parent_node["id"],
        parent_edge_id=parent_edge["id"],
    )

    return {
        "asset_node": asset_node,
        "parent_edge": parent_edge,
        "gallery_node": gallery_node,
        "gallery_edge": gallery_edge,
        "asset": updated_asset or asset_row,
    }


def _repair_asset_graph_if_possible(asset: dict) -> dict:
    """Best-effort repair for older asset rows returned by /assets."""
    if not asset:
        return asset
    existing_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    existing_gallery_edge_id = _asset_graph_ref(asset, "gallery_edge_id")
    if existing_node_id and existing_gallery_edge_id:
        return asset
    if existing_node_id and not existing_gallery_edge_id and asset.get("persona_id"):
        try:
            gallery = supabase_client.ensure_gallery_node(asset["persona_id"])
            if gallery:
                gallery_edge = supabase_client.upsert_knowledge_edge(
                    existing_node_id,
                    gallery["id"],
                    "gallery_asset",
                    persona_id=asset["persona_id"],
                    weight=0.9,
                    metadata={
                        "graph_layer": "auxiliary",
                        "primary_tree": False,
                        "visual_hidden": False,
                        "relation_role": "asset_gallery",
                        "created_from": "asset_list_repair",
                        "direction": "asset_to_gallery",
                    },
                )
                return supabase_client.update_asset_graph_refs(
                    asset["id"],
                    knowledge_node_id=existing_node_id,
                    gallery_edge_id=(gallery_edge or {}).get("id") if isinstance(gallery_edge, dict) else None,
                ) or asset
        except Exception as exc:
            logger.warning("asset gallery repair skipped asset=%s: %s", asset.get("id"), exc)
            return {**asset, "graph_status": "repair_failed"}
    persona_id = asset.get("persona_id")
    metadata = asset.get("metadata") or {}
    branch_hint = metadata.get("parent_node_id") or metadata.get("branch_hint") or metadata.get("parent_slug")
    if not persona_id or not branch_hint:
        return {**asset, "graph_status": "missing_branch"}
    parent_node = _find_parent_node(persona_id, branch_hint)
    if not parent_node:
        return {**asset, "graph_status": "missing_branch"}
    try:
        result = _ensure_asset_graph_contract(
            asset_id=asset["id"],
            asset_row=asset,
            persona_id=persona_id,
            parent_node=parent_node,
            storage_bucket=asset.get("storage_bucket") or metadata.get("storage_bucket"),
            storage_path=asset.get("storage_path") or metadata.get("storage_path"),
            title=_asset_title(asset),
            summary=metadata.get("visual_summary") or metadata.get("extracted_text") or "",
            slug_seed=asset.get("original_filename") or asset.get("name") or asset["id"],
            asset_type=asset.get("type") or metadata.get("kind"),
            asset_function=metadata.get("asset_function"),
            tags=metadata.get("tags") if isinstance(metadata.get("tags"), list) else ["asset"],
            knowledge_item_id=metadata.get("knowledge_item_id"),
            created_from="asset_list_repair",
        )
        return result.get("asset") or asset
    except Exception as exc:
        logger.warning("asset graph repair skipped asset=%s: %s", asset.get("id"), exc)
        return {**asset, "graph_status": "repair_failed"}


# ── POST /assets/upload ───────────────────────────────────────────────────

@router.post("/upload")
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    persona_id: str = Form(...),
    branch_hint: Optional[str] = Form(None),
    asset_function: Optional[str] = Form(None),
    persona_slug: Optional[str] = Form(None),
):
    auth_service.assert_persona_access(request, persona_id=persona_id)
    persona_id, persona_slug = _resolve_persona(persona_id, persona_slug)
    if not persona_id:
        raise HTTPException(400, "persona invalida")
    if not branch_hint:
        # Asset cannot live without a branch — UI must pick one.
        raise HTTPException(
            422,
            {"error": "branch_required", "needs_parent": True, "message": "Escolha o galho do grafo onde o asset sera conectado."},
        )

    parent_node = _find_parent_node(persona_id, branch_hint)
    if not parent_node:
        raise HTTPException(404, f"Parent node nao encontrado para slug/id={branch_hint}")

    try:
        return await _upload_asset_impl(file, persona_id, persona_slug, parent_node, asset_function)
    except HTTPException:
        raise
    except Exception as exc:
        import traceback as _tb
        logger.error("/assets/upload failed for persona=%s parent=%s: %s\n%s",
                     persona_id, (parent_node or {}).get("slug"), exc, _tb.format_exc())
        raise HTTPException(
            502,
            {
                "error": "asset_upload_failed",
                "exception_type": type(exc).__name__,
                "message": str(exc)[:400] or "Falha inesperada ao processar o asset.",
                "filename": file.filename,
                "parent_slug": (parent_node or {}).get("slug"),
            },
        ) from exc


def _append_image_ref_to_parent_card(parent_node: dict, image_slug: str) -> bool:
    """Append `![[image_slug]]` (Obsidian embed) to the parent card's .md.

    The parent card is a knowledge_node of type brand / briefing / product /
    copy / faq whose long-form markdown lives in a linked knowledge_item.
    Returns True when the embed was actually inserted (False when the parent
    has no editable knowledge_item or the reference is already present).
    """
    if not parent_node or not image_slug:
        return False
    parent_id = parent_node.get("id")
    if not parent_id:
        return False
    item_id = None
    if parent_node.get("source_table") == "knowledge_items" and parent_node.get("source_id"):
        item_id = parent_node["source_id"]
    else:
        item_id = (parent_node.get("metadata") or {}).get("knowledge_item_id")
    if not item_id:
        return False
    try:
        item = supabase_client.get_knowledge_item(item_id)
    except Exception:
        return False
    if not item:
        return False
    current = str(item.get("content") or "")
    ref = f"![[{image_slug}]]"
    if ref in current:
        return False
    section_header = "## Imagens"
    if section_header in current:
        new_content = current.rstrip() + f"\n{ref}\n"
    else:
        sep = "\n\n" if current.strip() else ""
        new_content = f"{current.rstrip()}{sep}{section_header}\n\n{ref}\n"
    try:
        supabase_client.update_knowledge_item(item_id, {"content": new_content})
        return True
    except Exception:
        return False


async def _upload_asset_impl(
    file: UploadFile,
    persona_id: str,
    persona_slug: Optional[str],
    parent_node: dict,
    asset_function: Optional[str],
):
    content = await file.read()
    fname = file.filename or "upload"
    mime = file.content_type or ""

    # 1) Upload to Supabase Storage.
    storage_bucket = "assets-raw"
    storage_path = f"{persona_id}/{fname}"
    try:
        file_url = supabase_client.upload_to_storage(storage_bucket, storage_path, content, mime or "application/octet-stream")
    except Exception as exc:
        logger.warning("assets-raw upload failed, falling back to 'knowledge': %s", exc)
        storage_bucket = "knowledge"
        storage_path = f"assets/{persona_id}/{fname}"
        file_url = supabase_client.upload_to_storage(storage_bucket, storage_path, content, mime or "application/octet-stream")

    # 2) Run the pipeline.
    ctx = AssetPipelineContext(
        persona_id=persona_id,
        persona_slug=persona_slug,
        session_id=None,
        upload_context="asset_card",
        original_filename=fname,
        mime=mime,
        branch_hint=parent_node.get("slug"),
        branch_label=parent_node.get("title") or parent_node.get("slug"),
        asset_function=asset_function or None,
    )
    bundle = run_pipeline(content, ctx)

    # 3) Persist public.assets.
    asset_type = _bundle_to_asset_type(bundle.classification.kind)
    asset_row = supabase_client.insert_asset({
        "persona_id": persona_id,
        "type": asset_type,
        "name": bundle.rename.title or fname,
        "url": file_url,
        "metadata": {
            "session_id": None,
            "persona_slug": persona_slug,
            "original_filename": fname,
            "preview_path": None,
            "reading_status": bundle.reading_status,
            "extracted_text": (bundle.extracted_text or "")[:8000],
            "visual_summary": bundle.visual_summary or "",
            "video_reading_mocked": bool(bundle.video_mock),
            "upload_context": "asset_card",
            "validation_status": "pending_validation",
            "kind": bundle.classification.kind,
            "asset_function": asset_function or bundle.rename.asset_function,
            "branch_hint": parent_node.get("slug"),
        },
        "source": "upload",
        "storage_bucket": storage_bucket,
        "storage_path": storage_path,
        "mime_type": mime,
        "file_size": len(content),
        "original_filename": fname,
        "status": "ready" if bundle.reading_status in ("completed", "mocked") else "reading",
        "upload_context": "asset_card",
    })
    asset_id = (asset_row or {}).get("id")
    if not asset_id:
        raise HTTPException(500, "Falha ao registrar asset.")

    for row in bundle.rows_to_persist:
        payload = dict(row)
        payload["asset_id"] = asset_id
        try:
            supabase_client.insert_asset_reading(payload)
        except Exception as exc:
            logger.warning("asset_reading insert failed: %s", exc)

    # 4) Create knowledge_item content_type='asset' pending.
    file_type = ""
    if "." in fname:
        file_type = fname.rsplit(".", 1)[-1].lower()
    source = supabase_client.get_or_create_manual_source()
    markdown = compose_markdown(bundle, persona_slug, parent_node.get("title") or parent_node.get("slug"), storage_path)
    item = supabase_client.insert_knowledge_item({
        "persona_id": persona_id,
        "source_id": source["id"],
        "status": "pending",
        "content_type": "asset",
        "title": bundle.rename.title or fname,
        "content": markdown[:12000],
        "file_type": file_type,
        "file_path": f"{storage_bucket}:{storage_path}",
        "asset_type": asset_type,
        "asset_function": asset_function or bundle.rename.asset_function,
        "agent_visibility": "private",
        "tags": bundle.rename.tags,
        "metadata": {
            "asset_id": asset_id,
            "storage_bucket": storage_bucket,
            "storage_path": storage_path,
            "asset_kind": bundle.classification.kind,
            "validation_status": "pending_validation",
            "upload_context": "asset_card",
            "parent_slug": parent_node.get("slug"),
            "session_id": None,
            "created_via": "asset_upload",
            "engine": (bundle.ocr.engine if bundle.ocr else None),
        },
    })

    # 5) Create/verify graph node + branch / gallery edges. This is a hard
    # contract: an asset-card upload is not successful while detached from Graph.
    graph = _ensure_asset_graph_contract(
        asset_id=asset_id,
        asset_row=asset_row,
        persona_id=persona_id,
        parent_node=parent_node,
        storage_bucket=storage_bucket,
        storage_path=storage_path,
        title=bundle.rename.title or fname,
        summary=bundle.visual_summary or bundle.extracted_text or markdown,
        slug_seed=bundle.rename.slug or fname,
        asset_type=asset_type,
        asset_function=asset_function or bundle.rename.asset_function,
        tags=bundle.rename.tags,
        knowledge_item_id=(item or {}).get("id"),
        created_from="asset_upload",
    )
    mirror = graph["asset_node"]
    parent_edge = graph["parent_edge"]
    gallery_edge = graph["gallery_edge"]
    asset_row = graph.get("asset") or asset_row

    # 6) Insert `![[slug]]` (Obsidian-style embed) into the parent card's
    # markdown so the image is anchored inside the card's .md. The parent
    # card is brand / briefing / product / copy / faq — whichever was
    # selected as branch_hint at upload time.
    parent_card_md_appended = False
    image_slug = (mirror or {}).get("slug") or fname
    try:
        parent_card_md_appended = _append_image_ref_to_parent_card(parent_node, image_slug)
    except Exception as exc:
        logger.warning("parent card .md append skipped parent=%s asset=%s: %s",
                       parent_node.get("id"), asset_id, exc)

    return {
        "success": True,
        "asset_id": asset_id,
        "asset": asset_row,
        "evidence": {
            "asset_id": asset_id,
            "knowledge_item_id": (item or {}).get("id"),
            "knowledge_node_id": (mirror or {}).get("id"),
            "parent_edge_id": (parent_edge or {}).get("id") if isinstance(parent_edge, dict) else None,
            "gallery_edge_id": (gallery_edge or {}).get("id") if isinstance(gallery_edge, dict) else None,
            "parent_card_node_id": (parent_node or {}).get("id"),
            "parent_card_md_appended": parent_card_md_appended,
            "image_ref": f"![[{image_slug}]]",
            "reading_status": bundle.reading_status,
        },
        "asset_reading": bundle.to_summary(),
        "file_url": file_url,
    }


# ── GET /assets ───────────────────────────────────────────────────────────

@router.get("")
def list_assets_route(
    request: Request,
    persona_id: Optional[str] = Query(None),
    upload_context: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    ensure_graph: bool = Query(True),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    rows = supabase_client.list_assets(
        persona_id=persona_id,
        upload_context=upload_context,
        status=status,
        limit=limit,
        offset=offset,
    )
    if not ensure_graph:
        return rows
    return [_repair_asset_graph_if_possible(row) for row in rows]


# ── GET /assets/{id} ──────────────────────────────────────────────────────

def _kind_label(kind: str) -> str:
    return {
        "image_screenshot": "Imagem (screenshot)",
        "image_product":    "Imagem (produto)",
        "image_document":   "Imagem (documento)",
        "image_social":     "Imagem (social)",
        "image_other":      "Imagem",
        "pdf":              "PDF",
        "text":             "Texto",
        "markdown":         "Markdown",
        "video":            "Video",
        "unknown":          "Desconhecido",
    }.get(kind or "", kind or "Asset")


def _compose_markdown_from_asset(asset: dict, readings: list[dict]) -> str:
    """Re-build the canonical markdown for an asset directly from the DB rows.

    Used by the detail view and by ensure-gallery so the same string is shown
    regardless of whether the linked knowledge_item is reachable.
    """
    metadata = asset.get("metadata") or {}
    title = _asset_title(asset, fallback="Asset")
    kind = metadata.get("kind") or asset.get("type") or "unknown"
    storage_path = (
        asset.get("storage_path")
        or metadata.get("storage_path")
        or asset.get("file_path")
    )
    bucket = asset.get("storage_bucket") or metadata.get("storage_bucket")
    file_location = f"{bucket}:{storage_path}" if bucket and storage_path else storage_path or "-"
    extracted = (metadata.get("extracted_text") or "").strip()
    visual = (metadata.get("visual_summary") or "").strip()
    asset_function = metadata.get("asset_function") or "(definir)"
    branch_hint = metadata.get("branch_hint") or metadata.get("parent_slug") or "(definir)"
    status = metadata.get("validation_status") or asset.get("status") or "ready"

    # Prefer richer readings when present (full OCR text instead of the 8k slice
    # we keep in metadata).
    full_ocr = ""
    full_visual = ""
    for r in readings or []:
        rtype = r.get("reading_type") or ""
        payload = r.get("payload") or {}
        if rtype == "ocr" and not full_ocr:
            full_ocr = (payload.get("text") or payload.get("extracted_text") or "").strip()
        if rtype == "ai_fallback" and not full_visual:
            full_visual = (payload.get("visual_summary") or payload.get("description") or "").strip()
        if rtype == "pdf_text" and not full_ocr:
            full_ocr = (payload.get("text") or "").strip()
    if full_ocr:
        extracted = full_ocr
    if full_visual:
        visual = full_visual

    lines = [
        f"# Asset — {title}",
        "",
        "## Tipo",
        _kind_label(str(kind)),
        "",
        "## Origem",
        str(metadata.get("upload_context") or asset.get("upload_context") or "asset_card"),
        "",
        "## Arquivo",
        str(file_location),
        "",
        "## Texto extraido",
        extracted or "(sem texto)",
        "",
        "## Leitura visual",
        visual or "(sem leitura visual)",
        "",
        "## Uso recomendado",
        str(asset_function),
        "",
        "## Conexao sugerida",
        str(branch_hint),
        "",
        "## Status",
        str(status),
    ]
    return "\n".join(lines)


def _graph_state(asset: dict) -> dict:
    """Compact view of where the asset lives in the graph. Drives the
    'Está no grafo de conhecimento' badge in the dashboard detail modal."""
    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    gallery_edge_id = _asset_graph_ref(asset, "gallery_edge_id")
    parent_node_id = _asset_graph_ref(asset, "parent_node_id")
    parent_edge_id = _asset_graph_ref(asset, "parent_edge_id")
    in_graph = bool(knowledge_node_id and gallery_edge_id)
    if in_graph:
        reason = "ok"
    elif not knowledge_node_id:
        reason = "missing_node"
    else:
        reason = "missing_gallery_edge"
    return {
        "in_graph": in_graph,
        "reason": reason,
        "knowledge_node_id": knowledge_node_id,
        "gallery_edge_id": gallery_edge_id,
        "parent_node_id": parent_node_id,
        "parent_edge_id": parent_edge_id,
    }


@router.get("/{asset_id}")
def get_asset_route(asset_id: str, request: Request):
    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    if asset.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=asset["persona_id"])
    readings = supabase_client.list_asset_readings(asset_id)

    # The /assets modal shows the PARENT CARD's markdown (brand/briefing/
    # product/copy/faq). The image was inserted into it as `![[slug]]` at
    # upload time. Falls back to the asset's own description when there is
    # no linked parent card with content.
    metadata = asset.get("metadata") or {}
    parent_card: Optional[dict] = None
    parent_card_markdown: Optional[str] = None
    parent_node_id = metadata.get("parent_node_id") or _asset_graph_ref(asset, "parent_node_id")
    if parent_node_id:
        try:
            parent_card = supabase_client.get_knowledge_node(parent_node_id)
        except Exception as exc:
            logger.warning("get_parent_card failed for asset=%s parent=%s: %s", asset_id, parent_node_id, exc)
        if parent_card:
            parent_item_id = (parent_card.get("metadata") or {}).get("knowledge_item_id") or parent_card.get("source_id")
            if parent_item_id and parent_card.get("source_table") == "knowledge_items":
                try:
                    pitem = supabase_client.get_knowledge_item(parent_item_id)
                    if pitem and pitem.get("content"):
                        parent_card_markdown = str(pitem["content"])
                except Exception as exc:
                    logger.warning("get_parent_card_item failed parent=%s: %s", parent_node_id, exc)

    markdown: Optional[str] = parent_card_markdown
    item_id = metadata.get("knowledge_item_id")
    if not markdown and item_id:
        try:
            item = supabase_client.get_knowledge_item(item_id)
            if item and item.get("content"):
                markdown = str(item["content"])
        except Exception as exc:
            logger.warning("get_knowledge_item failed for asset=%s item=%s: %s", asset_id, item_id, exc)
    if not markdown:
        markdown = _compose_markdown_from_asset(asset, readings)

    return {
        "asset": asset,
        "readings": readings,
        "markdown": markdown,
        "parent_card": parent_card,
        "graph": _graph_state(asset),
    }


# ── POST /assets/{id}/ensure-gallery ──────────────────────────────────────

@router.post("/{asset_id}/ensure-gallery")
def ensure_gallery_for_asset(asset_id: str, request: Request):
    """Repair flow used by the Assets detail modal: when an asset is not in the
    graph (no `knowledge_node_id` or no `gallery_edge_id`), this endpoint
    creates the md node and ensures `asset -> Gallery`.

    The asset-card contract still requires a parent for new uploads; this
    endpoint is the salvage path for older rows or for Sofia attachments that
    never had a branch assigned. The created node carries the same canonical
    markdown the detail modal shows, so Gallery curation stays in sync."""
    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    persona_id = asset.get("persona_id")
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    if not persona_id:
        raise HTTPException(
            422,
            {"error": "missing_persona", "message": "Asset sem persona nao pode entrar no grafo."},
        )

    readings = supabase_client.list_asset_readings(asset_id)
    markdown = _compose_markdown_from_asset(asset, readings)
    metadata = asset.get("metadata") or {}

    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    knowledge_node: Optional[dict] = None
    if knowledge_node_id:
        try:
            knowledge_node = supabase_client.get_knowledge_node(knowledge_node_id)
        except Exception:
            knowledge_node = None
    if not knowledge_node:
        knowledge_node = supabase_client.get_knowledge_node_for_source(
            "assets", asset_id, persona_id=persona_id
        )

    if not knowledge_node:
        base_slug = knowledge_graph._slugify(
            asset.get("original_filename") or asset.get("name") or asset_id
        )[:60] or "asset"
        node_payload = {
            "persona_id": persona_id,
            "source_table": "assets",
            "source_id": asset_id,
            "node_type": "asset",
            "slug": f"{base_slug}-{asset_id[:8]}",
            "title": _asset_title(asset),
            "summary": (markdown or "")[:400] or None,
            "tags": metadata.get("tags") if isinstance(metadata.get("tags"), list) else ["asset"],
            "metadata": {
                **metadata,
                "asset_id": asset_id,
                "storage_bucket": asset.get("storage_bucket") or metadata.get("storage_bucket"),
                "storage_path": asset.get("storage_path") or metadata.get("storage_path"),
                "asset_type": asset.get("type"),
                "asset_function": metadata.get("asset_function"),
                "created_via": "ensure_gallery",
                "open_url": "/marketing/assets",
                "markdown_excerpt": markdown[:600],
            },
            "status": "active",
            "level": 108,
            "importance": 0.64,
            "confidence": 1.0,
        }
        node_payload["metadata"] = {k: v for k, v in node_payload["metadata"].items() if v is not None}
        knowledge_node = supabase_client.upsert_knowledge_node(node_payload)
        if not knowledge_node or not knowledge_node.get("id"):
            raise HTTPException(502, "Falha ao criar node do asset no Graph.")

    gallery_node = supabase_client.ensure_gallery_node(persona_id)
    if not gallery_node or not gallery_node.get("id"):
        raise HTTPException(502, "Falha ao garantir node Gallery.")

    gallery_edge = supabase_client.upsert_knowledge_edge(
        knowledge_node["id"],
        gallery_node["id"],
        "gallery_asset",
        persona_id=persona_id,
        weight=0.9,
        metadata={
            "graph_layer": "auxiliary",
            "primary_tree": False,
            "visual_hidden": False,
            "relation_role": "asset_gallery",
            "created_from": "ensure_gallery",
            "direction": "asset_to_gallery",
        },
    )
    if not gallery_edge or not gallery_edge.get("id"):
        raise HTTPException(502, "Falha ao conectar asset -> Gallery no Graph.")

    updated = supabase_client.update_asset_graph_refs(
        asset_id,
        knowledge_node_id=knowledge_node["id"],
        gallery_edge_id=gallery_edge["id"],
    )
    asset_after = updated or {**asset, "knowledge_node_id": knowledge_node["id"], "gallery_edge_id": gallery_edge["id"]}

    return {
        "success": True,
        "asset": asset_after,
        "knowledge_node": knowledge_node,
        "gallery_node": gallery_node,
        "gallery_edge": gallery_edge,
        "graph": _graph_state(asset_after),
        "markdown": markdown,
    }


# ── POST /assets/{id}/connect ─────────────────────────────────────────────

class ConnectBody(BaseModel):
    parent_node_id: str
    relation_type: str = "uses_asset"


@router.post("/{asset_id}/connect")
def connect_asset(asset_id: str, body: ConnectBody, request: Request):
    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    if asset.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=asset["persona_id"])

    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    if not knowledge_node_id:
        raise HTTPException(409, "Asset ainda nao foi promovido para o grafo.")

    parent_raw = _strip_gn_prefix(body.parent_node_id)
    parent = _find_parent_node(asset.get("persona_id"), parent_raw)
    if not parent:
        raise HTTPException(404, "Parent node nao encontrado.")

    # Guard: never let a non-asset source land directly on Gallery via this endpoint.
    if (parent.get("node_type") or "") == "gallery":
        raise HTTPException(
            422,
            {"error": "gallery_invalid_target", "message": "Gallery so aceita asset -> gallery."},
        )

    edge = supabase_client.upsert_knowledge_edge(
        parent["id"], knowledge_node_id, body.relation_type or "uses_asset",
        persona_id=asset.get("persona_id"),
        weight=0.8,
        metadata={"created_from": "asset_connect", "primary_tree": True},
    )
    gallery = supabase_client.ensure_gallery_node(asset.get("persona_id"))
    gallery_edge = None
    if gallery:
        gallery_edge = supabase_client.upsert_knowledge_edge(
            knowledge_node_id,
            gallery["id"],
            "gallery_asset",
            persona_id=asset.get("persona_id"),
            weight=0.9,
            metadata={
                "graph_layer": "auxiliary",
                "primary_tree": False,
                "visual_hidden": False,
                "relation_role": "asset_gallery",
                "created_from": "asset_connect",
                "direction": "asset_to_gallery",
            },
        )
    supabase_client.update_asset_graph_refs(
        asset_id,
        knowledge_node_id=knowledge_node_id,
        gallery_edge_id=(gallery_edge or {}).get("id") if isinstance(gallery_edge, dict) else None,
        parent_node_id=parent["id"],
        parent_edge_id=(edge or {}).get("id") if isinstance(edge, dict) else None,
    )
    return {"success": True, "edge": edge, "gallery_edge": gallery_edge}


# ── Landing-page slot bindings ────────────────────────────────────────────
#
# A landing page has fixed surfaces (hero, product_group_cover,
# campaign_footer). Binding an asset to a slot is just an upsert of a
# knowledge_edge with metadata.page_binding.slot_key set.


class BindSlotBody(BaseModel):
    slot: str
    persona_slug: Optional[str] = None
    target_slug: Optional[str] = None      # required for product_group_cover (category slug)
    collection_slug: Optional[str] = None  # required for hero / campaign_footer
    position: int = 0
    label: Optional[str] = None


def _ensure_campaign_node_for_slot(
    persona_id: str,
    slot: LandingSlot,
    collection_slug: str,
    *,
    label: Optional[str],
) -> dict:
    """Find or create a per-collection campaign node that owns hero/footer slots.

    A single campaign node per (persona, collection_slug, slot) keeps the graph
    flat: hero edges live on one campaign, footer edges on another. The node
    carries page_binding so menu.py can serialize the binding back out.
    """
    cfg = slot_config(slot)
    slug = f"landing-{slot.value}-{collection_slug}"[:60]
    existing = supabase_client.get_knowledge_node_by_slug(
        slug,
        persona_id=persona_id,
        node_type="campaign",
    )
    if existing:
        return existing
    payload = {
        "persona_id": persona_id,
        "node_type": "campaign",
        "slug": slug,
        "title": label or f"{cfg['label']} · {collection_slug}",
        "summary": f"Landing slot '{slot.value}' for collection '{collection_slug}'.",
        "tags": ["landing", "campaign", slot.value],
        "metadata": {
            "collection_slug": collection_slug,
            "page_binding": {
                "slot_key": slot.value,
                "section": cfg["page_section"],
                "label": label or cfg["label"],
            },
            "landing_slot": slot.value,
            "created_via": "bind_slot",
        },
        "status": "active",
        "level": 60,
        "importance": 0.7,
        "confidence": 1.0,
    }
    node = supabase_client.upsert_knowledge_node(payload)
    if not node or not node.get("id"):
        raise HTTPException(502, "Falha ao criar node de campanha para o slot.")
    return node


def _resolve_slot_parent(
    persona_id: str,
    slot: LandingSlot,
    *,
    target_slug: Optional[str],
    collection_slug: Optional[str],
    label: Optional[str],
) -> dict:
    cfg = slot_config(slot)
    parent_type = cfg["parent_node_type"]
    if parent_type in {"category", "product"}:
        if not target_slug:
            raise HTTPException(422, f"{slot.value} precisa de target_slug ({parent_type} slug).")
        node = supabase_client.get_knowledge_node_by_slug(
            target_slug, persona_id=persona_id, node_type=parent_type,
        )
        if not node:
            raise HTTPException(404, f"{parent_type} nao encontrado: {target_slug}")
        return node
    # hero / footer → campaign node scoped to collection
    if not collection_slug:
        raise HTTPException(422, f"{slot.value} precisa de collection_slug.")
    return _ensure_campaign_node_for_slot(persona_id, slot, collection_slug, label=label)


def _asset_connection_row(edge: dict, parent_node: dict, slot: Optional[LandingSlot]) -> dict:
    meta = edge.get("metadata") or {}
    binding = meta.get("page_binding") or {}
    return {
        "edge_id": edge.get("id"),
        "relation_type": edge.get("relation_type"),
        "slot_key": (slot.value if slot else binding.get("slot_key") or binding.get("section")),
        "page_section": binding.get("section") or meta.get("page_section"),
        "label": binding.get("label"),
        "position": binding.get("position"),
        "role": meta.get("role"),
        "parent_node": {
            "id": parent_node.get("id"),
            "slug": parent_node.get("slug"),
            "node_type": parent_node.get("node_type"),
            "title": parent_node.get("title"),
            "collection_slug": (parent_node.get("metadata") or {}).get("collection_slug"),
        },
    }


@router.post("/{asset_id}/bind-slot")
def bind_asset_to_slot(asset_id: str, body: BindSlotBody, request: Request):
    """Upsert a knowledge_edge that binds the asset to a landing-page slot."""
    slot = slot_for_key(body.slot)
    if not slot:
        raise HTTPException(422, f"Slot invalido: {body.slot}")

    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    persona_id = asset.get("persona_id")
    if not persona_id:
        raise HTTPException(422, "Asset sem persona nao pode ser conectado a um slot.")
    auth_service.assert_persona_access(request, persona_id=persona_id)

    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    if not knowledge_node_id:
        raise HTTPException(409, "Asset ainda nao foi promovido para o grafo. Use ensure-gallery primeiro.")

    parent = _resolve_slot_parent(
        persona_id,
        slot,
        target_slug=body.target_slug,
        collection_slug=body.collection_slug,
        label=body.label,
    )

    cfg = slot_config(slot)
    slot_metadata = edge_metadata_for_slot(slot, position=body.position, label=body.label)
    edge = supabase_client.upsert_knowledge_edge(
        parent["id"],
        knowledge_node_id,
        cfg["relation_type"],
        persona_id=persona_id,
        weight=0.85,
        metadata={
            "created_from": "bind_slot",
            "primary_tree": True,
            "direction": "branch_to_asset",
            "parent_slug": parent.get("slug"),
            "parent_type": parent.get("node_type"),
            **slot_metadata,
        },
    )
    if not edge or not edge.get("id"):
        raise HTTPException(502, "Falha ao criar edge do slot.")

    asset_metadata = {**(asset.get("metadata") or {}), "asset_function": cfg["asset_function"]}
    try:
        supabase_client.update_asset(asset_id, {"metadata": asset_metadata})
    except Exception as exc:
        logger.warning("update_asset metadata failed asset=%s: %s", asset_id, exc)

    return {
        "success": True,
        "edge": edge,
        "slot": slot.value,
        "connection": _asset_connection_row(edge, parent, slot),
    }


@router.delete("/{asset_id}/bind-slot/{slot_key}")
def unbind_asset_slot(asset_id: str, slot_key: str, request: Request, target_slug: Optional[str] = Query(None)):
    """Soft-delete every active edge that ties this asset to the given slot.

    For product_group_cover the same asset can be on multiple categories, so
    `target_slug` narrows the unbind to a single category when provided.
    """
    slot = slot_for_key(slot_key)
    if not slot:
        raise HTTPException(422, f"Slot invalido: {slot_key}")

    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    persona_id = asset.get("persona_id")
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)

    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    if not knowledge_node_id:
        return {"success": True, "removed": 0}

    edges = supabase_client.list_edges_for_nodes([knowledge_node_id], limit=200)
    removed_ids: list[str] = []
    for edge in edges:
        if edge.get("target_node_id") != knowledge_node_id:
            continue
        edge_slot = slot_for_metadata(edge.get("metadata") or {})
        if edge_slot != slot:
            continue
        if target_slug:
            parent_node = supabase_client.get_knowledge_node(edge.get("source_node_id"))
            if not parent_node or parent_node.get("slug") != target_slug:
                continue
        if supabase_client.delete_knowledge_edge(edge["id"]):
            removed_ids.append(edge["id"])

    return {"success": True, "removed": len(removed_ids), "edge_ids": removed_ids}


@router.get("/{asset_id}/connections")
def list_asset_connections(asset_id: str, request: Request):
    """List every active landing-relevant edge incident on this asset.

    Excludes gallery_asset (already reflected by graph_state.in_graph).
    """
    asset = supabase_client.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset nao encontrado")
    if asset.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=asset["persona_id"])

    knowledge_node_id = _asset_graph_ref(asset, "knowledge_node_id")
    if not knowledge_node_id:
        return {"asset_id": asset_id, "knowledge_node_id": None, "connections": []}

    edges = supabase_client.list_edges_for_nodes([knowledge_node_id], limit=500)
    parent_ids = {
        edge.get("source_node_id")
        for edge in edges
        if edge.get("target_node_id") == knowledge_node_id and edge.get("relation_type") != "gallery_asset"
    }
    parent_ids.discard(None)
    parents = {row["id"]: row for row in supabase_client.list_knowledge_nodes_by_ids(list(parent_ids))}

    connections: list[dict] = []
    for edge in edges:
        if edge.get("target_node_id") != knowledge_node_id:
            continue
        if edge.get("relation_type") == "gallery_asset":
            continue
        parent_node = parents.get(edge.get("source_node_id"))
        if not parent_node:
            continue
        slot = slot_for_metadata(edge.get("metadata") or {})
        connections.append(_asset_connection_row(edge, parent_node, slot))

    return {
        "asset_id": asset_id,
        "knowledge_node_id": knowledge_node_id,
        "connections": connections,
    }
