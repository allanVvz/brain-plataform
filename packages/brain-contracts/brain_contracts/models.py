from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"] = "1.0"


class CanonicalInboundEnvelope(ContractModel):
    # v2 remains accepted only during the rolling migration.  Transport emits
    # v3, whose canonical_inbound_id is the idempotency key runtime owns.
    contract_version: Literal["2", "3"] = "3"
    inbound_id: str = Field(min_length=1)
    canonical_inbound_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    persona_id: UUID
    persona_slug: str = Field(min_length=1)
    lead_ref: str = Field(min_length=1)
    channel_binding_id: UUID
    provider: Literal["meta_cloud", "evolution", "internal_validator"]
    received_at: datetime
    message_type: str = Field(min_length=1)
    content: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_envelope(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        version = str(normalized.get("contract_version") or "3")
        # The original 1.0 envelope is treated as v2 wire compatibility, not
        # a third runtime branch.  New producers must omit it or send v3.
        if version == "1.0":
            version = "2"
        normalized["contract_version"] = version
        normalized.setdefault("canonical_inbound_id", normalized.get("inbound_id"))
        return normalized


class PublishedGraphContext(ContractModel):
    publication_id: UUID
    persona_id: UUID
    version: int = Field(ge=1)
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph: dict[str, Any]


class ConversationObservation(ContractModel):
    inbound_id: str
    lead_ref: str
    publication_id: UUID
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    identified_service_slug: str | None = None
    customer_intent: str | None = None


class ConversationDecision(ContractModel):
    decision_id: UUID
    inbound_id: str
    publication_id: UUID
    intent: str
    route: str
    reply: str | None = None
    missing_fields: tuple[str, ...] = ()
    handoff_reason: str | None = None
    evidence_node_ids: tuple[UUID, ...] = ()


class ProofCommit(ContractModel):
    proof_id: UUID
    decision_id: UUID
    inbound_id: str
    publication_id: UUID
    graph_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    committed_at: datetime
    outbound_allowed: bool


class OutboundEnvelope(ContractModel):
    outbound_id: UUID
    proof_id: UUID
    decision_id: UUID
    inbound_id: str
    persona_id: UUID
    lead_ref: str
    channel_binding_id: UUID
    content: dict[str, Any]


class InternalPrincipalClaims(ContractModel):
    subject: UUID
    role: Literal["admin", "user", "operator", "viewer", "service"]
    persona_ids: tuple[UUID, ...]
    service: str
    issued_at: datetime
    expires_at: datetime
    nonce: str


class BuildHealth(ContractModel):
    status: Literal["ok", "ready", "not_ready"]
    service: str
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    build_digest: str
    contracts_version: Literal["1.0.0"] = "1.0.0"
    schema_version: int
    required_schema_version: int
    slot: Literal["blue", "green", "unknown"] = "unknown"
    checks: dict[str, bool] = Field(default_factory=dict)
