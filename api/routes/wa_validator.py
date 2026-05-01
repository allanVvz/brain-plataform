# -*- coding: utf-8 -*-
"""WA Validator API routes."""

import logging
import traceback

from fastapi import APIRouter, HTTPException
from services.model_router import ModelRouterError
from pydantic import BaseModel
from typing import Optional
from services import wa_validator_service

logger = logging.getLogger("wa_validator")

router = APIRouter(prefix="/wa-validator", tags=["wa-validator"])


class GenerateScriptRequest(BaseModel):
    persona_slug: str
    flow_id: str
    target_contact: str
    model: str = "gpt-4o-mini"


class RunRequest(BaseModel):
    session_id: str


class AnalyzeRequest(BaseModel):
    session_id: str
    model: str = "gpt-4o-mini"


@router.get("/bots")
def list_bots():
    return wa_validator_service.bots()


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
    except ModelRouterError as e:
        logger.error("ModelRouter exhausted all providers (model=%r): %s", body.model, e)
        raise HTTPException(503, detail={"error": "ModelRouterError", "message": str(e), "model_requested": body.model})
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("generate_script failed (model=%r)\n%s", body.model, tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "model_sent": body.model,
            "traceback": tb,
        })


@router.post("/run")
def run_session(body: RunRequest):
    try:
        return wa_validator_service.run_session(body.session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("run_session failed\n%s", tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "traceback": tb,
        })


@router.post("/run-direct")
async def run_session_direct(body: RunRequest):
    """Drive validation through the platform's own /process pipeline — no WhatsApp needed."""
    try:
        return await wa_validator_service.run_session_direct(body.session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("run_session_direct failed\n%s", tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "traceback": tb,
        })


@router.post("/analyze")
def analyze_gaps(body: AnalyzeRequest):
    try:
        return wa_validator_service.analyze_gaps(body.session_id, model=body.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ModelRouterError as e:
        logger.error("ModelRouter exhausted all providers (model=%r): %s", body.model, e)
        raise HTTPException(503, detail={"error": "ModelRouterError", "message": str(e), "model_requested": body.model})
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("analyze_gaps failed (model=%r)\n%s", body.model, tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "model_sent": body.model,
            "traceback": tb,
        })
