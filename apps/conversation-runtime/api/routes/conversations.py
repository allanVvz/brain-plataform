"""Internal, token-authenticated conversation steps orchestrated by n8n."""
from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Header, HTTPException
from brain_contracts import (
    CanonicalConversationResultV1,
    ExecuteAgenticTurnV1,
    TechnicalConversationFailureV1,
)
from pydantic import Field, field_validator

from schemas.conversation import (
    AgentResponse,
    ConversationReplyV1,
    ConversationContext,
    ConversationDecision,
    ResolvedUnderstandingV1,
    StrictModel,
    TurnUnderstandingV1,
)
from services import agentic_turn, conversation_runtime, internal_auth, transport_client
from services import supabase_client


class CatalogAuthorizationRequest(StrictModel):
    response_buffer_id: str
    persona_id: str


router = APIRouter(prefix="/internal/v1/conversations", tags=["conversations"])


@router.post("/authorize-catalog-response")
def authorize_catalog_response(body: CatalogAuthorizationRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token")):
    internal_auth.authorize_webhook_token(x_webhook_token)
    rows = (supabase_client.get_client().table("conversation_turn_proofs")
            .select("publication_id,proof_result").eq("outbound_id", body.response_buffer_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(409, "Catalog response has no committed proof")
    proof = rows[0].get("proof_result") or {}
    publication = supabase_client.get_active_graph_publication(body.persona_id) or {}
    images = proof.get("catalog_images") or []
    identity = {k: publication.get(k) for k in ("id", "version", "checksum")}
    if (proof.get("delivery_authorized") is not True
            or str(publication.get("persona_id")) != body.persona_id
            or str(publication.get("id")) != str(rows[0]["publication_id"])
            or not 1 <= len(images) <= 3
            or any(image.get("publication") != identity for image in images)):
        raise HTTPException(409, "Catalog response publication expired or proof invalid")
    return {"images": images}


class ContextRequest(StrictModel):
    persona_slug: str
    lead_ref: int
    message: str
    message_id: str | None = None
    # Turn/trace id for observability -- the same lead_buffer.id already
    # sent as inbound_buffer_id to /commit, forwarded here too so every
    # step of a turn (context/decide/commit) logs under one shared id.
    # Optional so a not-yet-updated n8n workflow doesn't hard-fail.
    trace_id: str | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class DecisionRequest(StrictModel):
    context: ConversationContext
    resolved_understanding: ResolvedUnderstandingV1
    conversation_reply: ConversationReplyV1
    token_usage: dict = Field(default_factory=dict)
    trace_id: str | None = None
    # ConversationContext carries no lead identity of its own (by design --
    # /decide reasons only from context + model_observation) -- forwarded
    # separately, purely for observability logging (lead_id column).
    lead_ref: int | None = None

class ResolveUnderstandingRequest(StrictModel):
    context: ConversationContext
    understanding: TurnUnderstandingV1
    trace_id: str | None = None
    lead_ref: int | None = None
    token_usage: dict[str, Any] = Field(default_factory=dict)


class CommitRequest(StrictModel):
    lead_ref: int
    context: ConversationContext
    decision: ConversationDecision
    response: AgentResponse
    correlation_id: str
    phone_number_id: str | None = None
    channel_binding_id: str
    inbound_buffer_id: str
    n8n_execution_id: str | None = None


class FailSafeHandoffRequest(StrictModel):
    lead_ref: int
    reason: str
    correlation_id: str
    diagnostic: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class ExecuteRequest(StrictModel):
    persona_slug: str
    lead_ref: int
    message: str
    message_id: str | None = None
    correlation_id: str
    phone_number_id: str | None = None
    channel_binding_id: str
    inbound_buffer_id: str

    @field_validator("message")
    @classmethod
    def execute_message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class QueuePreviewRequest(StrictModel):
    """One operator-requested, non-deliverable preview for a technical turn."""
    persona_slug: str
    lead_ref: int
    message: str
    message_id: str | None = None
    correlation_id: str
    phone_number_id: str | None = None
    channel_binding_id: str
    inbound_buffer_id: str

    @field_validator("message")
    @classmethod
    def preview_message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized



@router.post("/execute")
def execute(
    body: ExecuteRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Execute a deterministic inbound behind the private service boundary."""
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        result = conversation_runtime.execute_deterministic_pipeline(**body.model_dump())
        envelope = conversation_runtime.dispatch_result_envelope(
            result, correlation_id=body.correlation_id
        )
        if result.get("classifier") is not None:
            envelope["classifier"] = result["classifier"]
        return envelope
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except conversation_runtime.ConversationCommitFailed as exc:
        raise HTTPException(409, detail=exc.canonical_result()) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/execute-agentic")
def execute_agentic(
    body: ExecuteAgenticTurnV1,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Execute one two-stage turn and always return a canonical envelope."""
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        result = agentic_turn.execute(
            **body.model_dump(exclude={"contract_version"})
        )
        return conversation_runtime.dispatch_result_envelope(
            result, correlation_id=body.correlation_id
        )
    except Exception as exc:  # every failed stage terminalizes exactly once
        stage = getattr(exc, "stage", None) or type(exc).__name__
        command = TechnicalConversationFailureV1(
            lead_ref=body.lead_ref,
            buffer_id=body.inbound_buffer_id,
            correlation_id=body.correlation_id,
            stage=str(stage)[:100],
            reason=f"agentic_turn_failed:{stage}"[:1000],
            diagnostic={
                "workflow_template": "runtime_agentic_v1",
                "execution_strategy": "interpret_then_respond",
                "failed_node": str(stage)[:100],
                "message": str(exc)[:1000],
                "proposal_summary": getattr(exc, "diagnostic", {}),
            },
        )
        return _terminalize_technical_failure(command)


@router.post("/queue-preview")
def queue_preview(
    body: QueuePreviewRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Generate a proof-gated reply preview without admitting provider send.

    The control plane claims the technical inbound before calling this route.
    Unlike the ordinary worker route, an operator retry failure is returned to
    the queue and never creates another technical handoff cascade.
    """
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        result = agentic_turn.execute(**body.model_dump(), preview_only=True)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    return conversation_runtime.dispatch_result_envelope(
        result, correlation_id=body.correlation_id
    )


@router.post("/context", response_model=ConversationContext)
def context(
    body: ContextRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> ConversationContext:
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        return conversation_runtime.build_context(**body.model_dump())
    except conversation_runtime.PublishedGraphUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/decide")
def decide(
    body: DecisionRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        decision, response = conversation_runtime.decide_agentic(
            body.context,
            model_observation={"token_usage": body.token_usage},
            resolved_understanding=body.resolved_understanding,
            conversation_reply=body.conversation_reply,
            trace_id=body.trace_id,
            lead_ref=body.lead_ref,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "agent_role": body.context.agent_role,
        "execution_strategy": body.context.execution_strategy,
        "decision": decision.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }


@router.post("/resolve-understanding", response_model=ResolvedUnderstandingV1)
def resolve_understanding(
    body: ResolveUnderstandingRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> ResolvedUnderstandingV1:
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        return conversation_runtime.resolve_understanding(
            body.context,
            understanding=body.understanding,
            trace_id=body.trace_id,
            lead_ref=body.lead_ref,
            token_usage=body.token_usage,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/commit")
def commit(
    body: CommitRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    internal_auth.authorize_webhook_token(x_webhook_token)
    try:
        result = conversation_runtime.commit(
            lead_ref=body.lead_ref,
            context=body.context,
            decision=body.decision,
            response=body.response,
            correlation_id=body.correlation_id,
            phone_number_id=body.phone_number_id,
            channel_binding_id=body.channel_binding_id,
            inbound_buffer_id=body.inbound_buffer_id,
            expected_decision_owner="n8n_agents",
            n8n_execution_id=body.n8n_execution_id,
        )
        return conversation_runtime.dispatch_result_envelope(
            result, correlation_id=body.correlation_id
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except conversation_runtime.ConversationCommitFailed as exc:
        raise HTTPException(409, detail=exc.canonical_result()) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/fail-safe-handoff")
def fail_safe_handoff(
    body: FailSafeHandoffRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Compatibility route for workflows published before the v1 envelope."""
    internal_auth.authorize_webhook_token(x_webhook_token)
    if not body.trace_id:
        return CanonicalConversationResultV1(
            ok=False,
            status="technical_failure_unconfirmed",
            correlation_id=body.correlation_id,
            technical_failure=True,
            error="legacy fail-safe request has no inbound buffer identity",
        ).model_dump(mode="json")
    command = TechnicalConversationFailureV1(
        lead_ref=body.lead_ref,
        buffer_id=body.trace_id,
        correlation_id=body.correlation_id,
        stage=str(body.diagnostic.get("failed_node") or "legacy_workflow"),
        reason=body.reason,
        diagnostic=body.diagnostic,
    )
    return _terminalize_technical_failure(command)


@router.post("/technical-failure")
def technical_failure(
    body: TechnicalConversationFailureV1,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Terminalize one failed turn and request one technical handoff."""
    internal_auth.authorize_webhook_token(x_webhook_token)
    return _terminalize_technical_failure(body)


def _terminalize_technical_failure(
    body: TechnicalConversationFailureV1,
) -> dict[str, Any]:
    """Best-effort orchestration with a truthful, non-public result envelope."""
    lead = conversation_runtime.supabase_client.get_lead_by_ref(body.lead_ref) or {}
    failures: list[str] = []
    terminalization: dict[str, Any] = {}
    try:
        # Determine the recovery level before committing its outbound.  The
        # commit itself is a successful atomic decision and therefore records
        # a success event; persist this failure again afterwards so the next
        # canonical inbound still sees the consecutive streak.
        failure_streak = conversation_runtime.record_conversation_failure(
            lead_ref=body.lead_ref,
            inbound_buffer_id=body.buffer_id,
            persona_id=str(lead.get("persona_id") or "") or None,
            kind="technical_failure",
            reason=body.reason,
        )
        persona = conversation_runtime.supabase_client.get_persona_by_id(
            str(lead.get("persona_id") or "")
        ) or {}
        context = conversation_runtime.build_context(
            persona_slug=str(persona.get("slug") or ""), lead_ref=body.lead_ref,
            message="[technical recovery]", message_id=body.buffer_id,
            trace_id=body.buffer_id,
        )
        publication = conversation_runtime.supabase_client.get_graph_publication_by_id(
            str(context.publication_id or "")
        ) or {}
        nodes = (publication.get("document_json") or {}).get("nodes") or []
        policy = next((
            (node.get("data") or {}).get("technical_recovery")
            for node in nodes if node.get("node_type") == "persona"
            and (node.get("data") or {}).get("technical_recovery")
        ), {}) or {}
        recovery = policy.get("second_failure" if failure_streak >= 2 else "first_failure") or {}
        text = str(recovery.get("text") or "").strip()
        if not text:
            raise RuntimeError("published technical recovery text is unavailable")
        handoff_required = failure_streak >= 2
        decision = ConversationDecision(
            classifier="graph_technical_recovery_v1",
            intent="technical_handoff" if handoff_required else "technical_clarification",
            route="HUMAN" if handoff_required else "SDR", confidence=1,
            lead_stage=str(lead.get("stage") or "novo"),
            handoff_reason="consecutive_technical_failures" if handoff_required else None,
        )
        response = AgentResponse(
            reply_text=text, role=decision.route, cart_state=context.cart,
            handoff_required=handoff_required,
            proof={"valid": True, "delivery_authorized": True,
                   "technical_recovery": {"streak": failure_streak, "policy": "published"}},
        )
        recovery_result = conversation_runtime.commit(
            lead_ref=body.lead_ref, context=context, decision=decision, response=response,
            correlation_id=body.correlation_id, phone_number_id=None,
            channel_binding_id=str(lead.get("channel_binding_id") or ""),
            inbound_buffer_id=body.buffer_id, expected_decision_owner="n8n_agents",
        )
        # The same deterministic event is intentionally reasserted after the
        # success-shaped atomic recovery commit, so it remains the leading
        # event for the next inbound without duplicating its audit record.
        failure_streak = conversation_runtime.record_conversation_failure(
            lead_ref=body.lead_ref,
            inbound_buffer_id=body.buffer_id,
            persona_id=str(lead.get("persona_id") or "") or None,
            kind="technical_failure",
            reason=body.reason,
        )
    except Exception as exc:
        failures.append(f"failure_streak:{type(exc).__name__}")
        # If the immutable failure event was already written, retain its
        # known level even when the later recovery preparation is unavailable.
        # Only an unavailable audit state itself uses the conservative level.
        failure_streak = (
            int(locals()["failure_streak"])
            if "failure_streak" in locals() else 2
        )
    handoff_required = failure_streak >= 2
    try:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                f"brain-ai:conversation.technical_{'handoff' if handoff_required else 'failure'}:{body.buffer_id}",
            )
        )
        audit_event_type = (
            "conversation.technical_handoff"
            if handoff_required else "conversation.technical_failure"
        )
        existing = conversation_runtime.supabase_client.list_system_events(
            entity_type="lead_buffer",
            entity_id=body.buffer_id,
            event_types=[audit_event_type],
            limit=1,
        )
        if not existing:
            inserted = conversation_runtime.supabase_client.insert_event(
                {
                    "id": event_id,
                    "event_type": audit_event_type,
                    "entity_type": "lead_buffer",
                    "entity_id": body.buffer_id,
                    "persona_id": lead.get("persona_id"),
                    "payload": body.model_dump(mode="json"),
                },
                level="error",
                source="routes.conversations",
            )
            if inserted is None:
                # A concurrent retry may have won the deterministic event ID.
                existing = conversation_runtime.supabase_client.list_system_events(
                    entity_type="lead_buffer",
                    entity_id=body.buffer_id,
                    event_types=[audit_event_type],
                    limit=1,
                )
                if not existing:
                    raise RuntimeError("technical failure audit was not persisted")
        conversation_runtime.emit_turn_event(
            agent_name="conversation.error",
            trace_id=body.buffer_id,
            lead_ref=body.lead_ref,
            persona_id=lead.get("persona_id"),
            status="error",
            error_msg=body.reason,
            metadata={
                "conversation_id": body.lead_ref,
                "step": body.stage,
                "failure_streak": failure_streak,
                "handoff_required": handoff_required,
            },
        )
    except Exception as exc:
        failures.append(f"audit:{type(exc).__name__}")
    confirmed = not failures
    return CanonicalConversationResultV1(
        ok=False,
        status=(
            "technical_handoff" if confirmed and handoff_required
            else "technical_failure_unconfirmed"
        ),
        correlation_id=body.correlation_id,
        buffer_id=body.buffer_id,
        technical_failure=True,
        handoff=confirmed and handoff_required,
        ai_paused=confirmed and handoff_required,
        outbound_enqueued=bool((locals().get("recovery_result") or {}).get("outbound_id")),
        terminalization_status=terminalization.get("status"),
        error=";".join(failures) or None,
    ).model_dump(mode="json")
