from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Optional

from services.catalog_crawler import crawl_catalog_url
from services.kb_intake_service import (
    start_bootstrap_session,
    get_session,
    chat,
    save,
    AVAILABLE_MODELS,
    attach_crawler_capture,
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
    return start_bootstrap_session(body.model, initial_context=body.initial_context, agent_key=body.agent_key, initial_state=initial_state)


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
    content = await file.read()
    fname = file.filename or "upload"
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""

    storage_path: Optional[str] = None
    file_url: Optional[str] = None
    try:
        from services.supabase_client import upload_to_storage, insert_kb_intake
        storage_path = f"kb_intake/{session_id}/{fname}"
        file_url = upload_to_storage(
            "knowledge",
            storage_path,
            content,
            file.content_type or "application/octet-stream",
        )
        insert_kb_intake({
            "filename": fname,
            "file_path": storage_path,
            "persona_id": None,
            "status": "pending",
        })
    except Exception as exc:
        from services import sre_logger
        sre_logger.warn("kb_intake_upload", f"storage/db write skipped: {exc}", exc)

    file_info = {
        "filename": fname,
        "size": len(content),
        "content_type": file.content_type or "",
        "ext": ext,
        "bytes": content,
    }
    try:
        result = chat(session_id, message, file_info=file_info)
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
        }
    if file_url:
        result["file_url"] = file_url
        result["storage_path"] = storage_path
    return result


@router.get("/session/{session_id}")
def get_session_info(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
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
