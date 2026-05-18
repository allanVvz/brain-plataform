from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Optional
import os
import time

from services.catalog_crawler import crawl_catalog_url
from services.kb_intake_service import (
    start_bootstrap_session,
    get_session,
    chat,
    save,
    AVAILABLE_MODELS,
    attach_crawler_capture,
    attach_reading,
    prune_unpersisted_asset_readings,
    update_session_plan,
    _invalid_criar_persona,
    _session_public_state,
)

router = APIRouter(prefix="/kb-intake", tags=["kb-intake"])


class StartBody(BaseModel):
    model: str = "gpt-4o-mini"
    initial_context: str = ""
    agent_key: str = "sofia"
    persona_slug: Optional[str] = None
    source_url: Optional[str] = None
    mode: str = "legacy"
    initial_block_counts: dict[str, int] = Field(default_factory=dict)
    knowledge_plan: Optional[dict[str, Any]] = None
    memory_summary: Optional[str] = None
    bootstrap_llm: bool = True


class MessageBody(BaseModel):
    session_id: str
    message: str


class SaveBody(BaseModel):
    session_id: str
    content: str = ""
    plan_override: Optional[dict[str, Any]] = None


class CrawlBody(BaseModel):
    url: str
    session_id: Optional[str] = None


class PlanUpdateBody(BaseModel):
    knowledge_plan: dict[str, Any]
    status: Optional[str] = None
    last_change: Optional[str] = None


@router.get("/models")
def list_models():
    return [{"id": k, "name": v} for k, v in AVAILABLE_MODELS.items()]


@router.post("/start")
def start_session(body: StartBody):
    if body.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modelo nao disponivel: {body.model}")
    initial_state = {
        "mode": body.mode,
        "persona_slug": body.persona_slug,
        "source_url": body.source_url,
        "initial_block_counts": body.initial_block_counts,
        "knowledge_plan": body.knowledge_plan,
        "memory_summary": body.memory_summary,
    }
    if (body.mode or "").strip().lower() == "criar" and _invalid_criar_persona(body.persona_slug):
        raise HTTPException(400, "Selecione uma persona especifica antes de criar conhecimento.")
    return start_bootstrap_session(
        body.model,
        initial_context=body.initial_context,
        agent_key=body.agent_key,
        initial_state=initial_state,
        bootstrap_llm=body.bootstrap_llm,
    )


@router.post("/message")
def send_message(body: MessageBody):
    try:
        result = chat(body.session_id, body.message)
        return result
    except Exception as exc:
        # Full safety net: log structured event + return controlled body so
        # the chat never propagates a bare 500 to the operator.
        import traceback as _tb
        tb_text = _tb.format_exc()
        try:
            from services import sre_logger
            sre_logger.error(
                "kb_intake_message",
                f"unhandled in chat() session={(body.session_id or '')[:8]} msg_len={len(body.message or '')}: {exc}",
                exc,
            )
        except Exception:
            pass
        # Try to recover the session safely. Never let _this_ raise.
        try:
            session = get_session(body.session_id)
        except Exception:
            session = None
        try:
            from services.kb_intake_service import _emit_kb_event  # internal helper
            _emit_kb_event(
                "kb_intake_error",
                session=session or {"id": body.session_id, "classification": {}},
                source="kb-intake.message",
                status="failed",
                transcript=False,
                result={
                    "endpoint": "/kb-intake/message",
                    "step": "chat",
                    "session_id": body.session_id,
                    "exception_type": type(exc).__name__,
                    "message": str(exc)[:500],
                    "traceback_tail": tb_text.splitlines()[-12:],
                },
            )
        except Exception:
            pass
        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "exception_type": type(exc).__name__,
            "message": (
                "Nao consegui processar sua mensagem agora. Sua configuracao "
                "foi mantida — tente novamente ou clique em Salvar se ja houver plano."
            ),
            "detail": str(exc)[:300],
            "traceback_tail": tb_text.splitlines()[-12:],
            "state": (session or {}).get("mission_state") if session else None,
        }


@router.post("/crawl-preview")
def crawl_preview(body: CrawlBody):
    try:
        result = crawl_catalog_url(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Erro no crawler: {exc}") from exc
    if body.session_id:
        attach_crawler_capture(body.session_id, result)
    return result


@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...),
):
    upload_started = time.perf_counter()
    last_mark = upload_started
    timings_ms: dict[str, int] = {}

    def mark_timing(name: str) -> None:
        nonlocal last_mark
        now = time.perf_counter()
        timings_ms[name] = int((now - last_mark) * 1000)
        last_mark = now

    content = await file.read()
    mark_timing("read")
    fname = file.filename or "upload"
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""

    storage_path: Optional[str] = None
    file_url: Optional[str] = None
    asset_id: Optional[str] = None
    asset_reading_summary: Optional[dict] = None

    # Resolve persona from the session for asset row tagging.
    session_persona_id: Optional[str] = None
    session_persona_slug: Optional[str] = None
    try:
        sess = get_session(session_id)
        if sess:
            mission = sess.get("mission_state") or {}
            session_persona_id = mission.get("persona_id") or sess.get("persona_id")
            session_persona_slug = mission.get("persona_slug") or sess.get("persona_slug")
            if not session_persona_slug:
                session_persona_slug = (sess.get("classification") or {}).get("persona_slug")
        if session_persona_slug and not session_persona_id:
            from services import supabase_client
            persona = supabase_client.get_persona(session_persona_slug) or {}
            session_persona_id = persona.get("id")
            session_persona_slug = persona.get("slug") or session_persona_slug
            if sess and session_persona_id:
                sess["persona_id"] = session_persona_id
                sess["persona_slug"] = session_persona_slug
                mission = sess.setdefault("mission_state", {})
                mission["persona_id"] = session_persona_id
                mission["persona_slug"] = session_persona_slug
    except Exception:
        pass
    if not session_persona_id:
        prune_unpersisted_asset_readings(get_session(session_id) or {})
        return {
            "ok": False,
            "error_code": "ASSET_PERSONA_REQUIRED",
            "message": "Para persistir um asset, a sessao precisa estar vinculada a uma persona. A sessao foi reiniciada para nao manter leitura sem grafo.",
            "reset_session": True,
        }

    # 1) Upload to Storage. If this fails, do not attach the reading to Sofia:
    # local-only readings make the session remember files that do not exist in
    # the assets system.
    try:
        from services.supabase_client import upload_to_storage, insert_kb_intake
        storage_bucket = "assets-raw"
        storage_owner = session_persona_id or session_id
        storage_path = f"{storage_owner}/{fname}"
        file_url = upload_to_storage(
            storage_bucket,
            storage_path,
            content,
            file.content_type or "application/octet-stream",
        )
        insert_kb_intake({
            "filename": fname,
            "file_path": f"{storage_bucket}:{storage_path}",
            "persona_id": session_persona_id,
            "status": "pending",
        })
        mark_timing("storage")
    except Exception as exc:
        from services import sre_logger
        sre_logger.error("kb_intake_upload", f"storage/db write failed: {exc}", exc)
        prune_unpersisted_asset_readings(get_session(session_id) or {})
        return {
            "ok": False,
            "error_code": "ASSET_STORAGE_FAILED",
            "message": "Nao consegui persistir a imagem no Storage. A sessao foi reiniciada para nao manter uma leitura sem arquivo.",
            "detail": str(exc)[:300],
            "reset_session": True,
        }

    # 2) Run the asset pipeline (classifier + OCR + fallbacks) for any uploaded file.
    bundle = None
    try:
        from services.asset_pipeline import run_pipeline, AssetPipelineContext
        ctx = AssetPipelineContext(
            persona_id=session_persona_id,
            persona_slug=session_persona_slug,
            session_id=session_id,
            upload_context="sofia_chat",
            original_filename=fname,
            mime=file.content_type or "",
            branch_hint=None,
            branch_label=None,
        )
        bundle = run_pipeline(content, ctx)
        mark_timing("asset_pipeline")
    except Exception as exc:
        from services import sre_logger
        sre_logger.warn("kb_intake_upload", f"asset pipeline skipped: {exc}", exc)
        prune_unpersisted_asset_readings(get_session(session_id) or {})
        return {
            "ok": False,
            "error_code": "ASSET_PIPELINE_FAILED",
            "message": "A imagem foi enviada ao Storage, mas nao consegui registrar a leitura nos assets. A sessao foi reiniciada para nao manter contexto incompleto.",
            "detail": str(exc)[:300],
            "reset_session": True,
        }

    # 3) Persist public.assets + asset_readings for the chat upload too.
    if bundle is not None:
        try:
            from services import supabase_client
            asset_type = _bundle_to_asset_type(bundle.classification.kind)
            asset_row = supabase_client.insert_asset({
                "persona_id": session_persona_id,
                "type": asset_type,
                "name": bundle.rename.title or fname,
                "url": file_url,
                "metadata": {
                    "session_id": session_id,
                    "persona_slug": session_persona_slug,
                    "original_filename": fname,
                    "preview_path": None,
                    "reading_status": bundle.reading_status,
                    "extracted_text": (bundle.extracted_text or "")[:8000],
                    "visual_summary": bundle.visual_summary or "",
                    "video_reading_mocked": bool(bundle.video_mock),
                    "upload_context": "sofia_chat",
                    "validation_status": "context_only",
                    "kind": bundle.classification.kind,
                    "engine": (bundle.ocr.engine if bundle.ocr else None),
                    "ai_fallback_used": bundle.ai_fallback is not None and not (bundle.ai_fallback.error or ""),
                },
                "source": "upload",
                "storage_bucket": storage_bucket,
                "storage_path": storage_path,
                "mime_type": file.content_type or "",
                "file_size": len(content),
                "original_filename": fname,
                "status": "ready" if bundle.reading_status in ("completed", "mocked") else "reading",
                "upload_context": "sofia_chat",
            })
            asset_id = (asset_row or {}).get("id")
            if asset_id:
                for row in bundle.rows_to_persist:
                    payload = dict(row)
                    payload["asset_id"] = asset_id
                    try:
                        supabase_client.insert_asset_reading(payload)
                    except Exception as exc2:
                        from services import sre_logger
                        sre_logger.warn("kb_intake_upload", f"asset_reading insert failed: {exc2}", exc2)
            mark_timing("asset_db")
        except Exception as exc:
            from services import sre_logger
            sre_logger.warn("kb_intake_upload", f"asset insert skipped: {exc}", exc)

        if not asset_id:
            prune_unpersisted_asset_readings(get_session(session_id) or {})
            return {
                "ok": False,
                "error_code": "ASSET_DB_FAILED",
                "message": "A imagem foi enviada ao Storage, mas nao foi persistida no sistema de assets. A sessao foi reiniciada para evitar leitura fantasma.",
                "reset_session": True,
            }

        asset_reading_summary = bundle.to_summary()
        # 4) Attach reading to the session so Sofia sees it as context.
        try:
            attach_reading(
                session_id,
                asset_reading_summary,
                file_meta={
                    "filename": fname,
                    "size": len(content),
                    "mime": file.content_type or "",
                    "url": file_url,
                    "asset_id": asset_id,
                    "storage_bucket": storage_bucket,
                    "storage_path": storage_path,
                },
            )
            mark_timing("attach_reading")
        except Exception as exc:
            from services import sre_logger
            sre_logger.warn("kb_intake_upload", f"attach_reading skipped: {exc}", exc)

    # 5) Hand the file to chat() (existing behavior) so the assistant can react.
    file_info = {
        "filename": fname,
        "size": len(content),
        "content_type": file.content_type or "",
        "ext": ext,
        "bytes": content,
        "asset_reading": asset_reading_summary,
    }
    try:
        result = chat(session_id, message, file_info=file_info)
        mark_timing("chat_after_upload")
    except Exception as exc:
        import traceback as _tb
        tb_text = _tb.format_exc()
        try:
            from services import sre_logger
            sre_logger.error(
                "kb_intake_upload",
                f"unhandled in chat(file_info) session={(session_id or '')[:8]}: {exc}",
                exc,
            )
        except Exception:
            pass
        try:
            session = get_session(session_id)
        except Exception:
            session = None
        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "exception_type": type(exc).__name__,
            "message": "Nao consegui processar o arquivo agora. Mantive sua configuracao e voce pode tentar novamente.",
            "detail": str(exc)[:300],
            "traceback_tail": tb_text.splitlines()[-12:],
            "state": (session or {}).get("mission_state") if session else None,
            "asset_reading": asset_reading_summary,
            "asset_id": asset_id,
        }
    if file_url:
        result["file_url"] = file_url
        result["storage_path"] = storage_path
    if asset_id:
        result["asset_id"] = asset_id
    if asset_reading_summary:
        result["asset_reading"] = asset_reading_summary
    timings_ms["total"] = int((time.perf_counter() - upload_started) * 1000)
    try:
        from services import sre_logger
        sre_logger.info(
            "kb_intake_upload",
            f"upload timings session={(session_id or '')[:8]} asset={asset_id or '-'} timings_ms={timings_ms}",
        )
    except Exception:
        pass
    if os.environ.get("ENV", "").lower() in {"dev", "development", "local"} or os.environ.get("DEBUG_TIMINGS"):
        result["timings_ms"] = timings_ms
    return result


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


@router.get("/session/{session_id}")
def get_session_info(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    prune_unpersisted_asset_readings(session)
    live_state = _session_public_state(session)
    return {
        "id": session["id"],
        "stage": session["stage"],
        "model": session["model"],
        "classification": {k: v for k, v in session["classification"].items() if k != "file_bytes"},
        "message_count": len(session["messages"]),
        "state": session.get("mission_state"),
        "resumed_from_session_id": session.get("resumed_from_session_id"),
        "resume_source": session.get("resume_source"),
        "resume_summary": session.get("resume_summary"),
        **live_state,
    }


@router.patch("/session/{session_id}/plan")
def patch_session_plan(session_id: str, body: PlanUpdateBody):
    result = update_session_plan(
        session_id,
        body.knowledge_plan,
        status=body.status,
        source="kb-intake.sidebar",
        last_change=body.last_change or "frontend plan sync",
    )
    if result.get("ok") is False:
        raise HTTPException(400, result)
    return result


@router.post("/save")
def save_knowledge(body: SaveBody):
    try:
        result = save(body.session_id, body.content, body.plan_override)
    except Exception as exc:
        # Safety net: surface unhandled exceptions in the response body so the
        # frontend (and the operator) can see the real cause without digging
        # through stderr. Remove once the save path is stable.
        import traceback as _tb
        tb_text = _tb.format_exc()
        try:
            from services import sre_logger
            sre_logger.error("kb_intake_save", f"unhandled in save(): {exc}", exc)
        except Exception:
            pass
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Unhandled exception in save(): {exc}",
                "exception_type": type(exc).__name__,
                "traceback": tb_text.splitlines()[-20:],
            },
        )

    if "error" in result:
        try:
            from services import sre_logger
            sre_logger.warn(
                "kb_intake_save",
                f"save rejected session={body.session_id[:8]} error={result.get('error')} classification={result.get('classification')}",
            )
        except Exception:
            pass
        raise HTTPException(400, result)
    return result
