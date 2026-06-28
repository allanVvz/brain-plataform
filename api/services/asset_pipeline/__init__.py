# -*- coding: utf-8 -*-
"""Asset reading pipeline — single entry point.

run_pipeline(file_bytes, mime, ctx) -> AssetReadingBundle

The pipeline is shared by:
- /kb-intake/upload (Sofia/CRIAR — file becomes immediate session context)
- /assets/upload    (ASSET card — also creates knowledge_item + node + edges)

The pipeline persists nothing on its own. The caller decides what to write to
public.assets / public.asset_readings / knowledge_items.
"""
from __future__ import annotations

import logging
from typing import Optional

from . import ai_fallback as _ai
from . import classifier as _classifier
from . import ocr_local as _ocr
from . import pdf_text as _pdf
from . import renamer as _renamer
from . import video_mock as _video
from .schemas import (
    AssetPipelineContext,
    AssetReadingBundle,
    ClassificationResult,
    ReadingStatus,
)

logger = logging.getLogger("asset_pipeline")


def _build_rows(
    persona_id: Optional[str],
    classification: ClassificationResult,
    ocr_res,
    pdf_res,
    video_res,
    ai_res,
    rename_res,
) -> list[dict]:
    rows: list[dict] = []
    rows.append({
        "reading_type": "classification",
        "persona_id": persona_id,
        "title": None,
        "summary": None,
        "extracted_text": None,
        "visual_summary": None,
        "markdown": None,
        "classification": {
            "kind": classification.kind,
            "needs_ocr": classification.needs_ocr,
            "width": classification.width,
            "height": classification.height,
            "extra": classification.extra,
        },
        "confidence": classification.confidence,
        "model_used": None,
        "status": "completed",
        "metadata": {},
    })
    if ocr_res:
        rows.append({
            "reading_type": "ocr",
            "persona_id": persona_id,
            "title": None,
            "summary": None,
            "extracted_text": ocr_res.extracted_text,
            "visual_summary": None,
            "markdown": None,
            "classification": {"engine": ocr_res.engine},
            "confidence": ocr_res.confidence,
            "model_used": ocr_res.engine,
            "status": "completed" if ocr_res.extracted_text and not ocr_res.needs_ai_fallback else "partial",
            "metadata": {"needs_ai_fallback": ocr_res.needs_ai_fallback, "error": ocr_res.error},
        })
    if pdf_res:
        rows.append({
            "reading_type": "pdf_text",
            "persona_id": persona_id,
            "title": None,
            "summary": None,
            "extracted_text": pdf_res.extracted_text,
            "visual_summary": None,
            "markdown": None,
            "classification": {"page_count": pdf_res.page_count},
            "confidence": 0.9 if pdf_res.extracted_text else 0.0,
            "model_used": "pypdf",
            "status": "completed" if pdf_res.extracted_text else "partial",
            "metadata": {"error": pdf_res.error},
        })
    if video_res:
        rows.append({
            "reading_type": "video_mock",
            "persona_id": persona_id,
            "title": None,
            "summary": video_res.get("visual_summary"),
            "extracted_text": None,
            "visual_summary": video_res.get("visual_summary"),
            "markdown": None,
            "classification": {},
            "confidence": 0.0,
            "model_used": "mock",
            "status": "mocked",
            "metadata": {"video_reading_mocked": True},
        })
    if ai_res:
        rows.append({
            "reading_type": "ai_fallback",
            "persona_id": persona_id,
            "title": None,
            "summary": ai_res.visual_summary,
            "extracted_text": ai_res.extracted_text,
            "visual_summary": ai_res.visual_summary,
            "markdown": None,
            "classification": {},
            "confidence": 0.7 if ai_res.extracted_text else 0.0,
            "model_used": ai_res.model_used or "vision",
            "status": "completed" if ai_res.extracted_text and not ai_res.error else "failed",
            "metadata": {"error": ai_res.error},
        })
    if rename_res:
        rows.append({
            "reading_type": "rename",
            "persona_id": persona_id,
            "title": rename_res.title,
            "summary": None,
            "extracted_text": None,
            "visual_summary": None,
            "markdown": None,
            "classification": {
                "filename": rename_res.filename,
                "slug": rename_res.slug,
                "asset_function": rename_res.asset_function,
                "tags": rename_res.tags,
                "suggested_parent_slug": rename_res.suggested_parent_slug,
            },
            "confidence": 0.8,
            "model_used": rename_res.model_used,
            "status": "completed",
            "metadata": {"used_model": rename_res.used_model},
        })
    return rows


def _final_status(classification: ClassificationResult, ocr_res, pdf_res, video_res, ai_res) -> ReadingStatus:
    if classification.kind == "video":
        return "mocked"
    if classification.kind == "pdf":
        if pdf_res and pdf_res.extracted_text:
            return "completed"
        return "partial"
    if classification.kind in ("text", "markdown"):
        return "completed"
    if classification.kind.startswith("image"):
        if ai_res and ai_res.extracted_text:
            return "completed"
        if ocr_res and ocr_res.extracted_text and not ocr_res.needs_ai_fallback:
            return "completed"
        return "partial"
    return "failed"


def run_pipeline(file_bytes: bytes, ctx: AssetPipelineContext) -> AssetReadingBundle:
    """Process a file end-to-end. Returns a bundle; persists nothing."""
    file_bytes = file_bytes or b""
    classification = _classifier.detect(file_bytes, ctx.mime, ctx.original_filename)

    ocr_res = None
    pdf_res = None
    video_res = None
    ai_res = None

    extracted_text = ""
    visual_summary = ""

    if classification.kind.startswith("image"):
        if classification.needs_ocr:
            ocr_res = _ocr.run(file_bytes)
            extracted_text = ocr_res.extracted_text or ""
        if (not extracted_text) or (ocr_res and ocr_res.needs_ai_fallback):
            ai_res = _ai.run(file_bytes, ctx.mime, prior_text=extracted_text, openai_api_key=ctx.openai_api_key)
            if ai_res and ai_res.extracted_text:
                extracted_text = ai_res.extracted_text
            if ai_res and ai_res.visual_summary:
                visual_summary = ai_res.visual_summary
    elif classification.kind == "pdf":
        pdf_res = _pdf.run(file_bytes)
        extracted_text = pdf_res.extracted_text or ""
    elif classification.kind == "video":
        video_res = _video.run()
        visual_summary = video_res.get("visual_summary", "")
    elif classification.kind in ("text", "markdown"):
        try:
            extracted_text = file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            extracted_text = ""

    rename_res = _renamer.run(
        ctx.persona_slug,
        ctx.branch_label or ctx.branch_hint,
        classification.kind,
        extracted_text,
        visual_summary,
        ctx.original_filename,
        allow_model_refine=True,
        openai_api_key=ctx.openai_api_key,
    )

    rows = _build_rows(ctx.persona_id, classification, ocr_res, pdf_res, video_res, ai_res, rename_res)
    status = _final_status(classification, ocr_res, pdf_res, video_res, ai_res)

    return AssetReadingBundle(
        classification=classification,
        ocr=ocr_res,
        ai_fallback=ai_res,
        pdf_text=pdf_res,
        video_mock=video_res,
        rename=rename_res,
        reading_status=status,
        extracted_text=extracted_text,
        visual_summary=visual_summary,
        rows_to_persist=rows,
    )


def compose_markdown(bundle: AssetReadingBundle, persona_slug: Optional[str], branch_label: Optional[str], storage_path: Optional[str]) -> str:
    """Generate the validatable markdown for a knowledge_item content_type=asset."""
    kind = bundle.classification.kind
    kind_label = {
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
    }.get(kind, kind)
    lines = [
        f"# Asset — {bundle.rename.title}",
        "",
        "## Tipo",
        kind_label,
        "",
        "## Origem",
        "asset_card",
        "",
        "## Arquivo",
        storage_path or "-",
        "",
        "## Texto extraido",
        (bundle.extracted_text or "(sem texto)").strip(),
        "",
        "## Leitura visual",
        (bundle.visual_summary or "(sem leitura visual)").strip(),
        "",
        "## Uso recomendado",
        bundle.rename.asset_function,
        "",
        "## Conexao sugerida",
        (branch_label or bundle.rename.suggested_parent_slug or "(definir)"),
        "",
        "## Status",
        "pending_validation",
    ]
    return "\n".join(lines)


__all__ = [
    "run_pipeline",
    "compose_markdown",
    "AssetPipelineContext",
    "AssetReadingBundle",
]
