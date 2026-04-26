from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.kb_intake_service import (
    create_session, get_session, chat, save, AVAILABLE_MODELS,
)

router = APIRouter(prefix="/kb-intake", tags=["kb-intake"])


class StartBody(BaseModel):
    model: str = "claude-sonnet-4-6"


class MessageBody(BaseModel):
    session_id: str
    message: str


class SaveBody(BaseModel):
    session_id: str
    content: str = ""


@router.get("/models")
def list_models():
    return [{"id": k, "name": v} for k, v in AVAILABLE_MODELS.items()]


@router.post("/start")
def start_session(body: StartBody):
    if body.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modelo não disponível: {body.model}")
    session = create_session(body.model)
    return {
        "session_id": session["id"],
        "model": session["model"],
        "model_name": AVAILABLE_MODELS[body.model],
        "welcome": (
            "Olá! Sou o **KB Classifier**. Envie um texto, cole um conteúdo ou "
            "faça upload de um arquivo. Vou fazer algumas perguntas para classificar "
            "corretamente antes de salvar no vault."
        ),
    }


@router.post("/message")
def send_message(body: MessageBody):
    result = chat(body.session_id, body.message)
    if "error" in result:
        raise HTTPException(400, result["error"])
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
    file_info = {
        "filename": fname,
        "size": len(content),
        "content_type": file.content_type or "",
        "ext": ext,
        "bytes": content,
    }
    result = chat(session_id, message, file_info=file_info)
    if "error" in result:
        raise HTTPException(400, result["error"])
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
        raise HTTPException(400, result["error"])
    return result
