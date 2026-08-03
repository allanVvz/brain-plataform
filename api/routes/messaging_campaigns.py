from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import auth_service, campaigns_service, supabase_client


router = APIRouter(prefix="/messaging", tags=["messaging-campaigns"])


class CampaignPreviewBody(BaseModel):
    persona_id: str
    name: str | None = None
    objective: str | None = None
    purpose: str
    campaign_kind: Literal["consent_request", "promotional"]
    import_batch_ids: list[str] = Field(min_length=1)
    audience_id: str
    provider: Literal["meta_cloud"] = "meta_cloud"
    template_name: str | None = None
    template_language: str = "pt_BR"
    message: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    policy_overrides: dict[str, Any] = Field(default_factory=dict)


class CampaignCreateBody(CampaignPreviewBody):
    expected_revision: int = 0
    expected_preview_checksum: str = Field(min_length=16, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class CampaignStatusBody(BaseModel):
    expected_revision: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


def _assert_campaign_access(request: Request, campaign_id: str, capability: str = "view") -> dict:
    detail = campaigns_service.get_campaign_detail(campaign_id)
    auth_service.assert_persona_capability(
        request,
        capability,
        persona_id=detail["campaign"].get("persona_id"),
    )
    return detail


@router.get("/campaigns")
def list_campaigns(request: Request, persona_id: str | None = Query(None)):
    user = auth_service.current_user(request)
    if persona_id:
        auth_service.assert_persona_capability(request, "view", persona_id=persona_id)
        return campaigns_service.list_campaigns(persona_id)
    if not auth_service.is_admin(user):
        rows: list[dict] = []
        for allowed_id in auth_service.allowed_persona_ids(request):
            rows.extend(campaigns_service.list_campaigns(allowed_id))
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows
    return campaigns_service.list_campaigns()


@router.post("/campaigns/preview")
def preview_campaign(body: CampaignPreviewBody, request: Request):
    auth_service.assert_persona_capability(request, "edit", persona_id=body.persona_id)
    return campaigns_service.preview_campaign(body.model_dump())


@router.post("/campaigns")
def create_campaign(body: CampaignCreateBody, request: Request):
    auth_service.assert_persona_capability(request, "edit", persona_id=body.persona_id)
    user = auth_service.current_user(request)
    return campaigns_service.create_campaign_draft(
        body.model_dump(),
        actor_user_id=user.get("id"),
    )


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request):
    return _assert_campaign_access(request, campaign_id)


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, body: CampaignStatusBody, request: Request):
    detail = _assert_campaign_access(request, campaign_id, "edit")
    if detail["campaign"].get("status") not in {"draft", "validated", "scheduled", "running", "paused"}:
        raise HTTPException(409, "Campanha nao pode ser pausada neste estado.")
    return campaigns_service.update_campaign_status(
        campaign_id,
        expected_revision=body.expected_revision,
        status="paused",
        idempotency_key=body.idempotency_key,
        reason=body.reason,
        actor_user_id=auth_service.current_user(request).get("id"),
    )


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, body: CampaignStatusBody, request: Request):
    _assert_campaign_access(request, campaign_id, "edit")
    return campaigns_service.update_campaign_status(
        campaign_id,
        expected_revision=body.expected_revision,
        status="cancelled",
        idempotency_key=body.idempotency_key,
        reason=body.reason,
        actor_user_id=auth_service.current_user(request).get("id"),
    )


@router.get("/provider-health")
def provider_health(request: Request, persona_id: str = Query(...)):
    auth_service.assert_persona_capability(request, "view", persona_id=persona_id)
    persona = supabase_client.get_persona_by_id(persona_id)
    rollout_enabled = campaigns_service.rollout_one_enabled(persona)
    binding = supabase_client.get_active_whatsapp_binding(persona_id)
    if not binding:
        return {
            "provider": None, "ready": False, "status": "not_configured",
            "campaigns_enabled": False, "rollout_one_enabled": rollout_enabled,
        }
    provider = binding.get("provider")
    status = str(binding.get("connection_status") or "unknown").lower()
    return {
        "provider": provider,
        "ready": bool(
            provider == "meta_cloud"
            and status in {"connected", "open"}
            and binding.get("provider_secret_ciphertext")
            and binding.get("whatsapp_phone_number_id")
        ),
        "status": status,
        "campaigns_enabled": rollout_enabled and provider == "meta_cloud",
        "rollout_one_enabled": rollout_enabled,
        "evolution_experimental": provider == "evolution_baileys",
    }
