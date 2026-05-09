from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from services import auth_service, integration_service

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationCredentialsBody(BaseModel):
    enabled: Optional[bool] = None
    service_account_json: Optional[Any] = None
    spreadsheet_id: Optional[str] = None
    api_key: Optional[str] = None
    base_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class IntegrationValidateBody(BaseModel):
    service_account_json: Optional[Any] = None
    spreadsheet_id: Optional[str] = None
    api_key: Optional[str] = None
    base_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


def _current_user_id(request: Request) -> str:
    return auth_service.current_user(request).get("id") or ""


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
