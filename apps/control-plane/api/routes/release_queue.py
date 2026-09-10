from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import auth_service, release_queue_service


router = APIRouter(prefix="/messaging/release-queue", tags=["release-queue"])


class RegisterBatchBody(BaseModel):
    scope: Literal["safety_paused_binding", "deploy_pause"]
    persona_id: str | None = None
    binding_id: str | None = None
    lead_buffer_ids: list[str] | None = None
    release_sha: str | None = None
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)
    stagger_seconds: int = Field(default=4, ge=1, le=300)
    window_start: str = "08:00"
    window_end: str = "20:00"
    tz: str = "America/Sao_Paulo"


class ItemOverrideBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)
    new_available_at: str | None = None


@router.post("/batches")
def register_batch(body: RegisterBatchBody, request: Request):
    """Registers a release action. For safety_paused_binding this is
    deliberately the ONLY step: it clears the binding's safety_paused flag
    and schedules its waiting_human backlog in the same database
    transaction, so an operator can never register a release and forget the
    channel is still paused."""
    user = auth_service.current_user(request)
    if body.scope == "safety_paused_binding":
        if not body.binding_id:
            raise HTTPException(422, "binding_id e obrigatorio para safety_paused_binding.")
        auth_service.assert_persona_capability(request, "edit", persona_id=body.persona_id)
        candidates = release_queue_service.build_safety_paused_batch_candidates(body.binding_id)
        lead_buffer_ids = candidates["eligible_ids"]
        persona_id = body.persona_id or (candidates["binding"] or {}).get("persona_id")
        if not lead_buffer_ids:
            return release_queue_service.resume_safety_paused_binding_without_backlog(
                persona_id=persona_id,
                binding_id=body.binding_id,
                reason=body.reason,
                idempotency_key=body.idempotency_key,
                release_sha=body.release_sha,
                actor_user_id=user.get("id"),
            )
    else:
        # deploy_pause spans every persona sharing the paused worker; only an
        # admin (not a persona-scoped operator) registers it, normally from
        # ops/vps/resume-production-workers.sh rather than the dashboard.
        if not auth_service.is_admin(user):
            raise HTTPException(403, "Apenas admin pode registrar liberacao de deploy-pause.")
        if not body.lead_buffer_ids:
            raise HTTPException(422, "lead_buffer_ids e obrigatorio para deploy_pause.")
        lead_buffer_ids = body.lead_buffer_ids
        persona_id = None

    return release_queue_service.register_release_batch(
        persona_id=persona_id,
        scope=body.scope,
        lead_buffer_ids=lead_buffer_ids,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        binding_id=body.binding_id,
        release_sha=body.release_sha,
        actor_user_id=user.get("id"),
        stagger_seconds=body.stagger_seconds,
        window_start=body.window_start,
        window_end=body.window_end,
        tz=body.tz,
    )


@router.get("/batches")
def list_batches(request: Request, persona_id: str | None = Query(None)):
    user = auth_service.current_user(request)
    if persona_id:
        auth_service.assert_persona_capability(request, "view", persona_id=persona_id)
        return release_queue_service.list_release_batches(persona_id)
    if not auth_service.is_admin(user):
        rows: list[dict] = []
        for allowed_id in auth_service.allowed_persona_ids(request):
            rows.extend(release_queue_service.list_release_batches(allowed_id))
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows
    return release_queue_service.list_release_batches()


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, request: Request):
    detail = release_queue_service.get_release_batch_detail(batch_id)
    persona_id = detail["batch"].get("persona_id")
    if persona_id:
        auth_service.assert_persona_capability(request, "view", persona_id=persona_id)
    elif not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode ver lote sem persona.")
    return detail


def _item_action(item_id: str, action: str, body: ItemOverrideBody, request: Request):
    user = auth_service.current_user(request)
    item = release_queue_service.get_release_batch_item(item_id)
    persona_id = item.get("persona_id")
    if persona_id:
        auth_service.assert_persona_capability(request, "edit", persona_id=persona_id)
    elif not auth_service.is_admin(user):
        raise HTTPException(403, "Apenas admin pode alterar item sem persona.")
    return release_queue_service.set_item_override(
        item_id=item_id,
        action=action,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        new_available_at=body.new_available_at,
        actor_user_id=user.get("id"),
    )


@router.post("/items/{item_id}/pause")
def pause_item(item_id: str, body: ItemOverrideBody, request: Request):
    return _item_action(item_id, "pause", body, request)


@router.post("/items/{item_id}/resume")
def resume_item(item_id: str, body: ItemOverrideBody, request: Request):
    return _item_action(item_id, "resume", body, request)


@router.post("/items/{item_id}/reschedule")
def reschedule_item(item_id: str, body: ItemOverrideBody, request: Request):
    if not body.new_available_at:
        raise HTTPException(422, "new_available_at e obrigatorio para reagendar.")
    return _item_action(item_id, "reschedule", body, request)
