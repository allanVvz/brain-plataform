"""Temporary v2/v3 wire compatibility at the private service boundary.

The compatibility parser is intentionally kept in the contracts package.  It
lets a rolling deployment accept a v2 canonical inbound while every newly
emitted event uses v3.  Domain services must consume the normalized v3 model
and never contain their own version branching.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ContractVersion(StrEnum):
    V2 = "2"
    V3 = "3"


class _EnvelopeBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inbound_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    persona_slug: str = Field(min_length=1)
    lead_ref: str = Field(min_length=1)
    channel_binding_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    received_at: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    content: dict[str, Any]


class ConversationEventV2(_EnvelopeBase):
    """Legacy event accepted only during the rolling v2 -> v3 migration."""

    contract_version: ContractVersion = ContractVersion.V2


class ConversationEventV3(_EnvelopeBase):
    """Canonical event emitted by transport and owned by runtime."""

    contract_version: ContractVersion = ContractVersion.V3
    canonical_inbound_id: str = Field(min_length=1)


def parse_conversation_event(payload: dict[str, Any]) -> ConversationEventV3:
    """Parse a v2 or v3 wire event into the canonical v3 representation."""
    version = str(payload.get("contract_version") or ContractVersion.V2)
    if version == ContractVersion.V3:
        return ConversationEventV3.model_validate(payload)
    if version == ContractVersion.V2:
        v2 = ConversationEventV2.model_validate(payload)
        return ConversationEventV3(
            **v2.model_dump(exclude={"contract_version"}),
            canonical_inbound_id=v2.inbound_id,
        )
    raise ValidationError.from_exception_data(
        "ConversationEvent",
        [{"type": "literal_error", "loc": ("contract_version",),
          "input": version, "ctx": {"expected": "'2' or '3'"}}],
    )
