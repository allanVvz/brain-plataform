"""Internal, token-authenticated conversation steps orchestrated by n8n."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    StrictModel,
)
from services import conversation_runtime


router = APIRouter(prefix="/internal/conversations", tags=["conversations"])


def _authorize(token: str | None) -> None:
    expected = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "internal webhook token is not configured")
    if expected and not hmac.compare_digest(
        (token or "").encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(401, "invalid webhook token")


class ContextRequest(StrictModel):
    persona_slug: str
    lead_ref: int
    message: str
    message_id: str | None = None


class DecisionRequest(StrictModel):
    context: ConversationContext
    model_observation: dict | None = None


class CommitRequest(StrictModel):
    lead_ref: int
    context: ConversationContext
    decision: ConversationDecision
    response: AgentResponse
    correlation_id: str
    phone_number_id: str | None = None
    channel_binding_id: str
    inbound_buffer_id: str


class FailSafeHandoffRequest(StrictModel):
    lead_ref: int
    reason: str
    correlation_id: str


@router.post("/context", response_model=ConversationContext)
def context(
    body: ContextRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> ConversationContext:
    _authorize(x_webhook_token)
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
    _authorize(x_webhook_token)
    decision, response = conversation_runtime.decide(
        body.context,
        model_observation=body.model_observation,
    )
    return {
        "decision": decision.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }


@router.post("/commit")
def commit(
    body: CommitRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    _authorize(x_webhook_token)
    try:
        return conversation_runtime.commit(
            lead_ref=body.lead_ref,
            context=body.context,
            decision=body.decision,
            response=body.response,
            correlation_id=body.correlation_id,
            phone_number_id=body.phone_number_id,
            channel_binding_id=body.channel_binding_id,
            inbound_buffer_id=body.inbound_buffer_id,
            expected_decision_owner="n8n_agents",
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/fail-safe-handoff")
def fail_safe_handoff(
    body: FailSafeHandoffRequest,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    _authorize(x_webhook_token)
    lead = conversation_runtime.supabase_client.get_lead_by_ref(body.lead_ref) or {}
    conversation_runtime.supabase_client.handoff_whatsapp_lead(body.lead_ref)
    conversation_runtime.supabase_client.insert_event(
        {
            "event_type": "conversation.fail_safe_handoff",
            "entity_type": "lead",
            "entity_id": str(body.lead_ref),
            "persona_id": lead.get("persona_id"),
            "payload": body.model_dump(),
        },
        level="error",
        source="routes.conversations",
    )
    return {"ok": True, "handoff": True, "ai_paused": True}
