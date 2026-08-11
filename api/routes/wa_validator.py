# -*- coding: utf-8 -*-
"""WA Validator API routes."""

import logging
import os
import traceback

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services import auth_service, wa_validator_service

logger = logging.getLogger("wa_validator")

router = APIRouter(prefix="/wa-validator", tags=["wa-validator"])


def _assert_runs_enabled() -> None:
    enabled = os.environ.get("WA_VALIDATOR_RUN_ENABLED", "").strip().lower() in {
        "1", "true", "yes",
    }
    if os.environ.get("ENVIRONMENT", "development").lower() == "production" and not enabled:
        raise HTTPException(503, "WA Validator runs are temporarily disabled in production.")


def _assert_session_access(request: Request, session_id: str) -> dict:
    session = wa_validator_service.get_session(session_id)
    auth_service.assert_persona_access(
        request, persona_slug=str(session.get("persona_slug") or ""),
    )
    return session


class GenerateScriptRequest(BaseModel):
    persona_slug: str
    flow_id: str
    target_contact: str
    model: str = "none"
    # "cold" (default, current behavior: fresh lead, nothing known yet),
    # "known_name" (lead already has nome_cliente on file before the script
    # runs -- tests that the agent never re-asks it), or "random" (picks
    # between the two per generation, so repeated runs cover both).
    initial_state: str | None = None


class RunRequest(BaseModel):
    session_id: str


class AnalyzeRequest(BaseModel):
    session_id: str
    model: str = "none"


@router.get("/bots")
def list_bots(request: Request):
    user = auth_service.current_user(request)
    allowed = None if auth_service.is_admin(user) else set(auth_service.allowed_persona_ids(request))
    return wa_validator_service.bots(allowed)


@router.get("/bootstrap")
def bootstrap(request: Request, persona_slug: str):
    auth_service.assert_persona_access(request, persona_slug=persona_slug)
    try:
        return wa_validator_service.bootstrap(persona_slug)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/flows")
def list_flows(request: Request, persona_slug: str | None = None):
    if persona_slug:
        auth_service.assert_persona_access(request, persona_slug=persona_slug)
    return wa_validator_service.flows(persona_slug)


@router.get("/models")
def list_models():
    return [{"id": k, "label": v} for k, v in wa_validator_service.AVAILABLE_MODELS.items()]


@router.get("/sessions")
def list_sessions(request: Request):
    sessions = wa_validator_service.list_sessions()
    user = auth_service.current_user(request)
    if auth_service.is_admin(user):
        return sessions
    visible: list[dict] = []
    for session in sessions:
        try:
            auth_service.assert_persona_access(
                request, persona_slug=str(session.get("persona_slug") or ""),
            )
        except HTTPException:
            continue
        visible.append(session)
    return visible


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str):
    try:
        return _assert_session_access(request, session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/generate-script")
def generate_script(request: Request, body: GenerateScriptRequest):
    try:
        auth_service.assert_persona_access(request, persona_slug=body.persona_slug)
        return wa_validator_service.generate_script(
            persona_slug=body.persona_slug,
            flow_id=body.flow_id,
            target_contact=body.target_contact,
            model=body.model,
            initial_state=body.initial_state,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("generate_script failed (model=%r)\n%s", body.model, tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "classifier_sent": body.model,
            "traceback": tb,
        })


@router.post("/run")
def run_session(request: Request, body: RunRequest):
    try:
        _assert_runs_enabled()
        _assert_session_access(request, body.session_id)
        return wa_validator_service.run_session(body.session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("run_session failed\n%s", tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "traceback": tb,
        })


@router.post("/run-direct")
async def run_session_direct(request: Request, body: RunRequest):
    """Drive validation through the selected conversation_v1 mode."""
    try:
        _assert_runs_enabled()
        _assert_session_access(request, body.session_id)
        return await wa_validator_service.run_session_direct(body.session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("run_session_direct failed\n%s", tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "traceback": tb,
        })


@router.post("/analyze")
def analyze_gaps(request: Request, body: AnalyzeRequest):
    try:
        _assert_session_access(request, body.session_id)
        return wa_validator_service.analyze_gaps(body.session_id, model=body.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("analyze_gaps failed (model=%r)\n%s", body.model, tb)
        raise HTTPException(500, detail={
            "error": type(e).__name__,
            "message": str(e),
            "classifier_sent": body.model,
            "traceback": tb,
        })
