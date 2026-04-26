# -*- coding: utf-8 -*-
"""WA Validator API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services import wa_validator_service

router = APIRouter(prefix="/wa-validator", tags=["wa-validator"])


class GenerateScriptRequest(BaseModel):
    persona_slug: str
    flow_id: str
    target_contact: str
    model: str = "claude-haiku-4-5-20251001"


class RunRequest(BaseModel):
    session_id: str


class AnalyzeRequest(BaseModel):
    session_id: str
    model: str = "claude-haiku-4-5-20251001"


@router.get("/flows")
def list_flows():
    return wa_validator_service.flows()


@router.get("/models")
def list_models():
    return [{"id": k, "label": v} for k, v in wa_validator_service.AVAILABLE_MODELS.items()]


@router.get("/sessions")
def list_sessions():
    return wa_validator_service.list_sessions()


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return wa_validator_service.get_session(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/generate-script")
def generate_script(body: GenerateScriptRequest):
    try:
        return wa_validator_service.generate_script(
            persona_slug=body.persona_slug,
            flow_id=body.flow_id,
            target_contact=body.target_contact,
            model=body.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/run")
def run_session(body: RunRequest):
    try:
        return wa_validator_service.run_session(body.session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/analyze")
def analyze_gaps(body: AnalyzeRequest):
    try:
        return wa_validator_service.analyze_gaps(body.session_id, model=body.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
