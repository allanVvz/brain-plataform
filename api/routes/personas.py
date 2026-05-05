import logging
import secrets
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from schemas.persona import PersonaCreate, PersonaUpdate
from services import auth_service, supabase_client

router = APIRouter(prefix="/personas", tags=["personas"])
logger = logging.getLogger("personas")


class RoutingUpdate(BaseModel):
    process_mode: str | None = None
    outbound_webhook_url: str | None = None
    outbound_webhook_secret: str | None = None
    inbound_webhook_token: str | None = None
    rotate_inbound_token: bool | None = None


def _mask_routing(routing: dict) -> dict:
    """Hide secret/token values from GET responses; return only presence flag."""
    if not routing:
        return routing
    return {
        "slug": routing.get("slug"),
        "id": routing.get("id"),
        "process_mode": routing.get("process_mode") or "internal",
        "outbound_webhook_url": routing.get("outbound_webhook_url"),
        "has_outbound_webhook_secret": bool(routing.get("outbound_webhook_secret")),
        "has_inbound_webhook_token": bool(routing.get("inbound_webhook_token")),
        "migration_applied": bool(routing.get("migration_applied")),
        "routing_source": routing.get("routing_source") or "default",
    }


@router.get("")
def list_personas(request: Request):
    user = auth_service.current_user(request)
    access = auth_service.allowed_access(request)
    return auth_service.filter_personas_for_user(user, supabase_client.get_personas(), access)


@router.get("/{slug}")
def get_persona(slug: str, request: Request):
    persona = supabase_client.get_persona(slug)
    if not persona:
        raise HTTPException(404, "Persona not found")
    auth_service.assert_persona_access(request, persona_id=persona.get("id"), persona_slug=slug)
    return persona


@router.post("")
def create_persona(body: PersonaCreate, request: Request):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode criar personas")
    supabase_client.upsert_persona(body.model_dump())
    return supabase_client.get_persona(body.slug)


@router.patch("/{slug}")
def update_persona(slug: str, body: PersonaUpdate, request: Request):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode editar personas")
    supabase_client.upsert_persona({"slug": slug, **body.model_dump(exclude_none=True)})
    return supabase_client.get_persona(slug)


@router.get("/{slug}/routing")
def get_routing(slug: str, request: Request):
    routing = supabase_client.get_persona_routing(slug)
    if not routing:
        raise HTTPException(404, "Persona not found")
    auth_service.assert_persona_access(request, persona_id=routing.get("id"), persona_slug=slug)
    return _mask_routing(routing)


@router.patch("/{slug}/routing")
def update_routing(slug: str, body: RoutingUpdate, request: Request):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode editar routing")
    current = supabase_client.get_persona_routing(slug)
    if not current:
        raise HTTPException(404, "Persona not found")
    if not current.get("migration_applied"):
        raise HTTPException(
            409,
            "Migration 011 not applied. Apply supabase/migrations/011_persona_routing.sql before editing persona routing.",
        )
    payload: dict = {}
    rotated_token: str | None = None
    if body.process_mode is not None:
        if body.process_mode not in {"internal", "n8n"}:
            raise HTTPException(400, "process_mode must be 'internal' or 'n8n'")
        payload["process_mode"] = body.process_mode
    if body.outbound_webhook_url is not None:
        payload["outbound_webhook_url"] = body.outbound_webhook_url.strip() or None
    if body.outbound_webhook_secret is not None:
        payload["outbound_webhook_secret"] = body.outbound_webhook_secret or None
    if body.inbound_webhook_token is not None:
        payload["inbound_webhook_token"] = body.inbound_webhook_token or None
    if body.rotate_inbound_token:
        rotated_token = secrets.token_urlsafe(32)
        payload["inbound_webhook_token"] = rotated_token
    if not payload:
        return _mask_routing(current)
    updated = supabase_client.update_persona_routing(slug, payload)
    response = _mask_routing(updated or current)
    if rotated_token:
        response["inbound_webhook_token"] = rotated_token
    return response


@router.post("/{slug}/routing/test")
def test_outbound_webhook(slug: str, request: Request):
    """Fires a synthetic ping at the persona's outbound webhook so the
    operator can confirm n8n is wired up correctly. Returns the upstream
    status code and any error string."""
    routing = supabase_client.get_persona_routing(slug)
    if not routing:
        raise HTTPException(404, "Persona not found")
    auth_service.assert_persona_access(request, persona_id=routing.get("id"), persona_slug=slug)
    url = routing.get("outbound_webhook_url")
    if not url:
        raise HTTPException(400, "outbound_webhook_url not configured")
    headers = {"Content-Type": "application/json"}
    secret = routing.get("outbound_webhook_secret")
    if secret:
        headers["X-Webhook-Secret"] = secret
    payload = {
        "ping": True,
        "persona_slug": slug,
        "issued_at": int(time.time()),
        "source": "ai-brain.routing.test",
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        return {"ok": 200 <= resp.status_code < 300, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as exc:
        logger.warning("routing test failed for %s: %s", slug, exc)
        return {"ok": False, "status": None, "error": str(exc)[:300]}
