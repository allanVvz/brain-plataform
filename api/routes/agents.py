"""Authenticated SDR journey and commercial conversion contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from routes.conversations import _authorize as authorize_internal
from services import auth_service, supabase_client

router = APIRouter(prefix="/agents", tags=["agents"])
internal_router = APIRouter(prefix="/internal/agents", tags=["agents"])


class PurchaseCompletedBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    external_ref: str | None = Field(default=None, max_length=300)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO code")
        return normalized

    @model_validator(mode="after")
    def require_currency_for_amount(self) -> "PurchaseCompletedBody":
        if self.amount_minor is not None and self.currency is None:
            raise ValueError("currency is required when amount_minor is present")
        return self


class ConversionStatusBody(BaseModel):
    status: Literal["cancelled", "partially_refunded", "refunded"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    refunded_amount_minor: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JourneyEventBody(BaseModel):
    event_type: Literal[
        "converted", "sale_recorded", "appointment_booked", "delivered",
        "service_completed", "cancelled",
    ]
    idempotency_key: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    external_ref: str | None = Field(default=None, max_length=300)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return PurchaseCompletedBody.validate_currency(value)

    @model_validator(mode="after")
    def require_currency_for_amount(self) -> "JourneyEventBody":
        if self.amount_minor is not None and self.currency is None:
            raise ValueError("currency is required when amount_minor is present")
        if self.event_type not in {"sale_recorded", "appointment_booked"} and (
            self.amount_minor is not None or self.items
        ):
            raise ValueError("commercial values are only accepted for conversion events")
        return self


def _lead_or_404(lead_ref: int) -> dict:
    lead = supabase_client.get_lead_by_ref(lead_ref) or {}
    if not lead or not lead.get("persona_id"):
        raise HTTPException(404, "Lead not found")
    return lead


def _record_journey_event(
    lead_ref: int, body: JourneyEventBody, responsible_user_id: str | None,
) -> dict:
    lead = _lead_or_404(lead_ref)
    try:
        return supabase_client.record_conversation_journey_event(
            p_persona_id=lead["persona_id"], p_lead_ref=lead_ref,
            p_event_type=body.event_type,
            p_idempotency_key=body.idempotency_key, p_source=body.source,
            p_occurred_at=body.occurred_at.isoformat(), p_external_ref=body.external_ref,
            p_amount_minor=body.amount_minor, p_currency=body.currency,
            p_items=body.items, p_metadata=body.metadata,
            p_responsible_user_id=responsible_user_id,
        )
    except Exception as exc:
        raise HTTPException(409, "Journey event could not be recorded") from exc


def _record_purchase(lead_ref: int, body: PurchaseCompletedBody, responsible_user_id: str | None) -> dict:
    return _record_journey_event(
        lead_ref,
        JourneyEventBody(event_type="sale_recorded", **body.model_dump()),
        responsible_user_id,
    )


@router.post("/leads/{lead_ref}/journey-events")
def journey_event(lead_ref: int, body: JourneyEventBody, request: Request) -> dict:
    lead = _lead_or_404(lead_ref)
    user = auth_service.current_user(request)
    auth_service.assert_persona_capability(request, "edit", persona_id=lead["persona_id"])
    return _record_journey_event(lead_ref, body, str(user["id"]))


@internal_router.post("/leads/{lead_ref}/journey-events")
def journey_event_internal(
    lead_ref: int, body: JourneyEventBody,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    authorize_internal(x_webhook_token)
    return _record_journey_event(lead_ref, body, None)


@router.post("/leads/{lead_ref}/purchase-completed")
def purchase_completed(lead_ref: int, body: PurchaseCompletedBody, request: Request) -> dict:
    lead = _lead_or_404(lead_ref)
    user = auth_service.current_user(request)
    auth_service.assert_persona_capability(request, "edit", persona_id=lead["persona_id"])
    return _record_purchase(lead_ref, body, str(user["id"]))


@internal_router.post("/leads/{lead_ref}/purchase-completed")
def purchase_completed_internal(
    lead_ref: int, body: PurchaseCompletedBody,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    authorize_internal(x_webhook_token)
    return _record_purchase(lead_ref, body, None)


@router.post("/sales-conversions/{conversion_id}/status")
def transition_conversion(conversion_id: UUID, body: ConversionStatusBody, request: Request) -> dict:
    user = auth_service.current_user(request)
    result = supabase_client.get_client().table("sales_conversions").select(
        "id,persona_id"
    ).eq("id", str(conversion_id)).maybe_single().execute()
    conversion = getattr(result, "data", None) or {}
    if not conversion:
        raise HTTPException(404, "Conversion not found")
    auth_service.assert_persona_capability(request, "edit", persona_id=conversion["persona_id"])
    try:
        return supabase_client.transition_sales_conversion_status(
            p_conversion_id=str(conversion_id), p_status=body.status,
            p_idempotency_key=body.idempotency_key,
            p_refunded_amount_minor=body.refunded_amount_minor,
            p_metadata=body.metadata, p_responsible_user_id=str(user["id"]),
        )
    except Exception as exc:
        raise HTTPException(409, "Conversion status could not be changed") from exc
