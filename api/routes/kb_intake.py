from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.catalog_crawler import crawl_catalog_url
from services.kb_intake_service import (
    create_session, get_session, chat, save, AVAILABLE_MODELS, get_agent_profile, attach_crawler_capture,
)

router = APIRouter(prefix="/kb-intake", tags=["kb-intake"])


class StartBody(BaseModel):
    model: str = "gpt-4o-mini"
    initial_context: str = ""
    agent_key: str = "sofia"


class MessageBody(BaseModel):
    session_id: str
    message: str


class SaveBody(BaseModel):
    session_id: str
    content: str = ""


class CrawlBody(BaseModel):
    url: str
    session_id: Optional[str] = None


@router.get("/models")
def list_models():
    return [{"id": k, "name": v} for k, v in AVAILABLE_MODELS.items()]


@router.post("/start")
def start_session(body: StartBody):
    if body.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modelo não disponível: {body.model}")
    session = create_session(body.model, initial_context=body.initial_context, agent_key=body.agent_key)
    agent = get_agent_profile(session.get("agent_key"))
    return {
        "session_id": session["id"],
        "model": session["model"],
        "model_name": AVAILABLE_MODELS[body.model],
        "agent": {"key": session.get("agent_key"), "name": agent["name"], "role": agent["role"]},
        "welcome": (
            f"{agent['greeting']} Envie um texto, cole um conteúdo ou faça upload de um arquivo. "
            "Se faltar contexto, vou perguntar o que falta antes de propor entries, links, copys ou salvar no vault."
        ),
    }


@router.post("/message")
def send_message(body: MessageBody):
    try:
        result = chat(body.session_id, body.message)
    except Exception as exc:
        raise HTTPException(500, f"Erro interno: {exc}") from exc
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


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

    # Persist to Supabase Storage + kb_intake table (best-effort)
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
        raise HTTPException(500, f"Erro interno: {exc}") from exc
    if "error" in result:
        raise HTTPException(400, result["error"])
    if file_url:
        result["file_url"] = file_url
        result["storage_path"] = storage_path
    return result


@router.get("/session/{session_id}")
def get_session_info(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "id": session["id"],
        "stage": session["stage"],
        "model": session["model"],
        "classification": {k: v for k, v in session["classification"].items() if k != "file_bytes"},
        "message_count": len(session["messages"]),
    }


@router.post("/save")
def save_knowledge(body: SaveBody):
    result = save(body.session_id, body.content)
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
