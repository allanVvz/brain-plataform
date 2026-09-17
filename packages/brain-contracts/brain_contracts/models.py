from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    publication_id: UUID | None = None

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

    @model_validator(mode="after")
    def _staged_publication_is_validator_only(self) -> "CanonicalInboundEnvelope":
        if self.publication_id and self.provider != "internal_validator":
            raise ValueError("publication_id is restricted to internal_validator")
        return self


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


class TechnicalConversationFailureV1(ContractModel):
    """Sanitized command used to terminalize one failed conversation turn."""

    contract_version: Literal["technical_conversation_failure_v1"] = (
        "technical_conversation_failure_v1"
    )
    lead_ref: int = Field(gt=0)
    buffer_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    stage: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
    diagnostic: dict[str, Any] = Field(default_factory=dict)

    @field_validator("diagnostic", mode="before")
    @classmethod
    def _sanitize_diagnostic(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        allowed = {
            "workflow_template",
            "execution_strategy",
            "failed_node",
            "message",
            "http_code",
        }
        sanitized: dict[str, Any] = {}
        for key in allowed:
            if key not in value:
                continue
            item = value.get(key)
            if isinstance(item, str):
                sanitized[key] = item[:1000]
            elif isinstance(item, (int, float, bool)) or item is None:
                sanitized[key] = item
        return sanitized


class ExecuteAgenticTurnV1(ContractModel):
    """Private transport-to-runtime command for one canonical inbound."""

    contract_version: Literal["execute_agentic_turn_v1"] = "execute_agentic_turn_v1"
    persona_slug: str = Field(min_length=1)
    lead_ref: int = Field(gt=0)
    message: str = Field(min_length=1)
    message_id: str | None = None
    correlation_id: str = Field(min_length=1)
    phone_number_id: str | None = None
    channel_binding_id: str = Field(min_length=1)
    inbound_buffer_id: str = Field(min_length=1)
    provider: Literal["meta_cloud", "evolution", "internal_validator"] | None = None
    publication_id: str | None = None

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

    @model_validator(mode="after")
    def _staged_publication_is_validator_only(self) -> "ExecuteAgenticTurnV1":
        if self.publication_id and self.provider != "internal_validator":
            raise ValueError("publication_id is restricted to internal_validator")
        return self


class CanonicalConversationResultV1(ContractModel):
    """Small webhook result; failures never masquerade as customer replies."""

    contract_version: Literal["canonical_conversation_result_v1"] = (
        "canonical_conversation_result_v1"
    )
    ok: bool
    status: Literal[
        "committed", "technical_handoff", "technical_failure_unconfirmed"
    ]
    correlation_id: str = Field(min_length=1)
    buffer_id: str | None = None
    technical_failure: bool = False
    handoff: bool = False
    ai_paused: bool = False
    outbound_enqueued: bool = False
    terminalization_status: str | None = None
    error: str | None = None


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
