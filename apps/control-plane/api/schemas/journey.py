"""Shared request contracts for conversation-journey operations."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
        "converted", "conversion_reverted", "sale_recorded", "appointment_booked",
        "delivered", "service_completed", "cancelled",
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


class JourneyStateBody(BaseModel):
    target: Literal["qualificado", "convertido", "vendido", "entregue", "cancelado"]
    source: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
