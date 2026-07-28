from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from services import auth_service, integration_service, supabase_client

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationCredentialsBody(BaseModel):
    enabled: Optional[bool] = None
    service_account_json: Optional[Any] = None
    spreadsheet_id: Optional[str] = None
    api_key: Optional[str] = None
    base_id: Optional[str] = None
    # Meta (WhatsApp Business catalog)
    access_token: Optional[str] = None
    business_id: Optional[str] = None
    catalog_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class IntegrationValidateBody(BaseModel):
    service_account_json: Optional[Any] = None
    spreadsheet_id: Optional[str] = None
    api_key: Optional[str] = None
    base_id: Optional[str] = None
    access_token: Optional[str] = None
    business_id: Optional[str] = None
    catalog_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class WhatsAppBindingBody(BaseModel):
    phone_number_id: str
    whatsapp_number: str | None = None
    workflow_name: str = "WA — Outbound Sender"
    n8n_workflow_id: str | None = None
    business_id: str | None = None
    waba_id: str | None = None
    verified_name: str | None = None
    webhook_url: str | None = None
    mode: str = "disabled"
    allowlist: list[str] = []
    agent_id: str | None = None
    conversation_mode: str | None = None


def _current_user_id(request: Request) -> str:
    return auth_service.current_user(request).get("id") or ""


def _persona_or_404(slug: str, request: Request) -> dict[str, Any]:
    persona = supabase_client.get_persona(slug)
    if not persona:
        raise HTTPException(404, "Persona nao encontrada")
    auth_service.assert_persona_access(request, persona_id=persona["id"], persona_slug=slug)
    return persona


def _public_binding(binding: dict[str, Any] | None) -> dict[str, Any] | None:
    """Expose routing state without ever serializing integration secrets."""
    if not binding:
        return None
    metadata = binding.get("metadata") or {}
    return {
        "id": binding.get("id"), "persona_id": binding.get("persona_id"),
        "workflow_name": binding.get("workflow_name"), "n8n_workflow_id": binding.get("n8n_workflow_id"),
        "whatsapp_number": binding.get("whatsapp_number"),
        "whatsapp_phone_number_id": binding.get("whatsapp_phone_number_id"),
        "active": bool(binding.get("active")),
        "metadata": {
            key: metadata.get(key)
            for key in (
                "business_id",
                "waba_id",
                "verified_name",
                "mode",
                "allowlist",
                "agent_id",
                "conversation_mode",
                "decision_owner",
                "pipeline_contract",
            )
            if metadata.get(key) is not None
        },
    }


def _to_payload(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_none=True)


def _handle_validation_error(exc: Exception) -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "status": "invalid_credentials",
            "message": str(exc),
        },
    ) from exc


@router.get("/catalog")
def integrations_catalog():
    return integration_service.list_catalog()


@router.get("")
def list_integrations(request: Request):
    return integration_service.list_user_integrations(_current_user_id(request))


@router.get("/user")
def list_user_integrations(request: Request):
    return integration_service.list_user_integrations(_current_user_id(request))


@router.put("/user/{service}")
def upsert_user_integration(service: str, body: IntegrationCredentialsBody, request: Request):
    try:
        return integration_service.save_user_integration(
            _current_user_id(request),
            service,
            enabled=bool(body.enabled),
            credentials=_to_payload(body),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {service}") from exc
    except integration_service.IntegrationValidationError as exc:
        _handle_validation_error(exc)


@router.post("/user/{service}/validate")
def validate_user_integration(service: str, request: Request, body: Optional[IntegrationValidateBody] = None):
    try:
        payload = _to_payload(body or IntegrationValidateBody())
        return integration_service.validate_user_integration(
            _current_user_id(request),
            service,
            credentials=payload or None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {service}") from exc
    except integration_service.IntegrationValidationError as exc:
        _handle_validation_error(exc)


@router.delete("/user/{service}/credentials")
def delete_user_integration_credentials(service: str, request: Request):
    try:
        return integration_service.delete_user_credentials(_current_user_id(request), service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {service}") from exc


@router.get("/meta/whatsapp/personas/{slug}")
def get_whatsapp_binding(slug: str, request: Request):
    persona = _persona_or_404(slug, request)
    binding = next((b for b in supabase_client.get_workflow_bindings(persona["id"]) if b.get("active") and b.get("whatsapp_phone_number_id")), None)
    connection = supabase_client.get_user_integration_connection(_current_user_id(request), "meta") or {}
    return {"persona": {"id": persona["id"], "slug": persona["slug"]}, "binding": _public_binding(binding), "meta_configured": bool(connection.get("secret_ciphertext"))}


@router.put("/meta/whatsapp/personas/{slug}/binding")
def put_whatsapp_binding(slug: str, body: WhatsAppBindingBody, request: Request):
    persona = _persona_or_404(slug, request)
    if body.mode not in {"disabled", "test_allowlist", "active"}:
        raise HTTPException(400, "mode invalido")
    allowlist = [item.strip() for item in body.allowlist if item and item.strip()]
    if body.mode == "test_allowlist" and not allowlist:
        raise HTTPException(400, "test_allowlist exige allowlist")
    routing = supabase_client.get_persona_routing(slug) or {}
    conversation_mode = body.conversation_mode or (
        "n8n_agents"
        if routing.get("process_mode") == "n8n"
        else "deterministic"
    )
    if conversation_mode not in {"deterministic", "n8n_agents"}:
        raise HTTPException(400, "conversation_mode invalido")
    metadata = {
        "business_id": body.business_id,
        "waba_id": body.waba_id,
        "verified_name": body.verified_name,
        "webhook_url": body.webhook_url,
        "mode": body.mode,
        "allowlist": allowlist,
        "agent_id": body.agent_id,
        "conversation_mode": conversation_mode,
        "decision_owner": conversation_mode,
        "pipeline_contract": "conversation_v1",
    }
    try:
        binding = supabase_client.upsert_workflow_binding({"persona_id": persona["id"], "workflow_name": body.workflow_name, "n8n_workflow_id": body.n8n_workflow_id, "whatsapp_number": body.whatsapp_number, "whatsapp_phone_number_id": body.phone_number_id, "active": body.mode != "disabled", "metadata": metadata})
    except Exception as exc:
        raise HTTPException(409, "phone_number_id ja possui binding ativo") from exc
    supabase_client.insert_event({"event_type": "whatsapp.binding_updated", "entity_type": "workflow_binding", "entity_id": binding.get("id") or body.phone_number_id, "persona_id": persona["id"], "payload": {"mode": body.mode, "phone_number_id": body.phone_number_id}}, source="integrations.whatsapp")
    return _public_binding(binding)


@router.post("/meta/whatsapp/personas/{slug}/validate")
def validate_whatsapp_binding(slug: str, request: Request):
    persona = _persona_or_404(slug, request)
    binding = next((b for b in supabase_client.get_workflow_bindings(persona["id"]) if b.get("active")), None)
    if not binding:
        raise HTTPException(400, "Binding WhatsApp nao configurado")
    if not (supabase_client.get_user_integration_connection(_current_user_id(request), "meta") or {}).get("secret_ciphertext"):
        raise HTTPException(400, "Token Meta nao configurado")
    return {"ok": True, "phone_number_id": binding.get("whatsapp_phone_number_id"), "token_masked": True}


@router.post("/meta/whatsapp/personas/{slug}/test")
def test_whatsapp_webhook(slug: str, request: Request):
    persona = _persona_or_404(slug, request)
    binding = next((b for b in supabase_client.get_workflow_bindings(persona["id"]) if b.get("active")), None)
    if not binding:
        raise HTTPException(400, "Binding WhatsApp nao configurado")
    supabase_client.insert_event({"event_type": "whatsapp.webhook_test_requested", "entity_type": "workflow_binding", "entity_id": binding.get("id") or "unknown", "persona_id": persona["id"], "payload": {"phone_number_id": binding.get("whatsapp_phone_number_id")}}, source="integrations.whatsapp")
    return {"ok": True, "synthetic": True, "correlation_id": f"wa-test:{binding.get('id')}"}
