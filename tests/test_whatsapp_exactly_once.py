from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import conversations, messages, whatsapp
from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ConversationRoute,
)
from services import conversation_runtime
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker


class RequestStub:
    def __init__(self, payload: dict):
        self.payload = payload
        self.raw = json.dumps(payload).encode()

    async def body(self):
        return self.raw

    async def json(self):
        return self.payload


def _context() -> ConversationContext:
    return ConversationContext(
        persona_slug="baita-conveniencia",
        agent_slug="vitoria",
        graph_version=1,
        graph_checksum="checksum",
        messages=[{"role": "user", "content": "Oi"}],
        cart={},
        rag_nodes=[],
        rag_paths=[],
    )


def _decision() -> ConversationDecision:
    return ConversationDecision(
        intent="greeting",
        route=ConversationRoute.SDR,
        confidence=1,
        lead_stage="contatado",
    )


def _response() -> AgentResponse:
    return AgentResponse(
        reply_text="Ola!",
        role=ConversationRoute.SDR,
        cart_state={},
    )


def test_manual_send_reuses_client_uuid_and_returns_same_envelope(monkeypatch):
    client_id = uuid.uuid4()
    calls = []
    monkeypatch.setattr(
        messages.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {
            "id": 7,
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
        },
    )
    monkeypatch.setattr(
        messages.auth_service,
        "assert_persona_access",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        messages.agents_service,
        "resolve_for_stage",
        lambda *_args, **_kwargs: (None, None),
    )

    def enqueue(**kwargs):
        calls.append(kwargs)
        return {
            "buffer_id": "buffer-1",
            "message_id": f"manual:{client_id}",
            "status": "pending_send",
            "deduplicated": len(calls) > 1,
        }

    monkeypatch.setattr(messages.whatsapp_outbox, "enqueue_outbound", enqueue)
    monkeypatch.setattr(messages.event_emitter, "emit", lambda *_args, **_kwargs: None)
    body = messages.SendMessageBody(
        lead_ref=7,
        client_message_id=client_id,
        texto="Oi",
    )

    first = messages.send_message(body, object())
    duplicate = messages.send_message(body, object())

    assert first["message_id"] == duplicate["message_id"] == f"manual:{client_id}"
    assert first["buffer_id"] == duplicate["buffer_id"] == "buffer-1"
    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert {call["idempotency_key"] for call in calls} == {f"manual:{client_id}"}


def test_internal_commit_requires_channel_binding_id():
    with pytest.raises(ValidationError):
        conversations.CommitRequest(
            lead_ref=7,
            context=_context(),
            decision=_decision(),
            response=_response(),
            correlation_id="corr-1",
            inbound_buffer_id="buffer-in",
        )


def test_n8n_commit_rejects_deterministic_binding(monkeypatch):
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {
            "id": 7,
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "deterministic"},
        },
    )

    with pytest.raises(
        RuntimeError,
        match="decision owner does not authorize",
    ):
        conversation_runtime.commit(
            lead_ref=7,
            context=_context(),
            decision=_decision(),
            response=_response(),
            correlation_id="corr-owner-guard",
            phone_number_id=None,
            channel_binding_id="binding-1",
            inbound_buffer_id="buffer-in",
            expected_decision_owner="n8n_agents",
        )


def test_internal_commit_declares_n8n_as_expected_owner(monkeypatch):
    captured = {}
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    monkeypatch.setattr(
        conversation_runtime,
        "commit",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )
    body = conversations.CommitRequest(
        lead_ref=7,
        context=_context(),
        decision=_decision(),
        response=_response(),
        correlation_id="corr-route-owner",
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
    )

    assert conversations.commit(body, "internal-token") == {"ok": True}
    assert captured["expected_decision_owner"] == "n8n_agents"


def test_repeated_n8n_commit_returns_existing_outbox_without_new_decision(monkeypatch):
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {
            "id": 7,
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
            "stage": "contatado",
            "metadata": {"qualification": {"score": 1}},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {
                "decision_owner": "n8n_agents",
                "transport_mode": "provider_direct",
            },
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_whatsapp_buffer_by_idempotency",
        lambda _key: {"id": "outbox-1", "status": "pending_send"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "update_lead",
        lambda *_args, **_kwargs: pytest.fail("duplicate commit mutated lead"),
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "insert_agent_log",
        lambda *_args, **_kwargs: pytest.fail("duplicate commit logged a decision"),
    )

    result = conversation_runtime.commit(
        lead_ref=7,
        context=_context(),
        decision=_decision(),
        response=_response(),
        correlation_id="corr-1",
        phone_number_id=None,
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
    )

    assert result["deduplicated"] is True
    assert result["message_id"] == "ai:corr-1"
    assert result["outbound_buffer_id"] == "outbox-1"


def test_thousand_repeated_inbound_events_yield_one_decision_outbox_and_provider_call(
    monkeypatch,
):
    binding = {
        "id": "binding-1",
        "persona_id": "persona-1",
        "provider": "meta_cloud",
        "active": True,
        "connection_status": "connected",
        "metadata": {
            "mode": "active",
            "decision_owner": "deterministic",
            "transport_mode": "provider_direct",
        },
    }
    envelopes: dict[str, dict] = {}

    def enqueue_envelope(*, buffer, message):
        key = buffer["idempotency_key"]
        duplicate = key in envelopes
        envelopes.setdefault(
            key,
            {
                "buffer_id": "inbox-1",
                "buffer": buffer,
                "message": message,
            },
        )
        return {
            "buffer_id": envelopes[key]["buffer_id"],
            "message_id": message["sender_id"],
            "status": buffer["status"],
            "deduplicated": duplicate,
        }

    monkeypatch.setattr(whatsapp, "_binding", lambda _phone: binding)
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "ensure_channel_lead",
        lambda **_kwargs: {
            "id": 7,
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
        },
    )
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "enqueue_whatsapp_envelope",
        enqueue_envelope,
    )
    monkeypatch.setattr(whatsapp.event_emitter, "emit", lambda *_args, **_kwargs: None)
    repeated_message = {
        "id": "wamid-1",
        "from": "5551982608510",
        "type": "text",
        "text": {"body": "Oi"},
    }
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "business-1"},
                    "messages": [repeated_message for _ in range(1000)],
                },
            }],
        }],
    }

    result = asyncio.run(whatsapp._process_inbound(payload))

    assert result == {"accepted": 1, "duplicate": 999, "ignored": 0}
    assert len(envelopes) == 1

    decisions = []
    completions = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _id: {"id": "persona-1", "slug": "baita-conveniencia"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _id: {
            "id": 7,
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
            "external_contact_id": "5551982608510",
            "metadata": {},
            "ai_paused": False,
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _id: binding,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.mark_whatsapp_attempt",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.conversation_runtime.execute_pipeline",
        lambda **kwargs: decisions.append(kwargs)
        or {"handoff": False, "classifier": "deterministic_v1", "route": "SDR"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: completions.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )
    worker = WhatsAppDispatchWorker()
    worker._dispatch_inbound({
        "id": "inbox-1",
        "direction": "inbound",
        "persona_id": "persona-1",
        "lead_ref": 7,
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "business-1",
        "external_message_id": "wamid-1",
        "correlation_id": "meta:binding-1:wamid-1",
        "payload": {"text": "Oi"},
    })
    assert len(decisions) == 1

    provider_calls = []
    outbound_results = []

    class Provider:
        def send_text(self, _binding, recipient, text):
            provider_calls.append((recipient, text))
            return {"messages": [{"id": "provider-1"}]}

    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.get_provider",
        lambda _name: Provider(),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_outbound",
        lambda *args, **kwargs: outbound_results.append((args, kwargs)),
    )
    worker._dispatch_outbound({
        "id": "outbox-1",
        "direction": "outbound",
        "persona_id": "persona-1",
        "lead_ref": 7,
        "channel_binding_id": "binding-1",
        "correlation_id": "meta:binding-1:wamid-1",
        "payload": {"text": "Ola!", "sender_type": "agent"},
    })

    assert len(provider_calls) == 1
    assert len(outbound_results) == 1


def test_provider_timeout_is_never_retried_automatically(monkeypatch):
    waiting = []
    violations = []
    binding = {
        "id": "binding-1",
        "persona_id": "persona-1",
        "provider": "evolution_baileys",
        "active": True,
        "metadata": {"transport_mode": "provider_direct"},
    }

    class Provider:
        def send_text(self, *_args, **_kwargs):
            raise TimeoutError("ambiguous timeout")

    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _id: binding,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _id: {
            "id": 7,
            "external_contact_id": "5551982608510",
            "metadata": {},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.mark_whatsapp_attempt",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: waiting.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.record_whatsapp_safety_violation",
        lambda **kwargs: violations.append(kwargs) or {},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.release_whatsapp_buffer",
        lambda *_args, **_kwargs: pytest.fail("ambiguous send was retried"),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.get_provider",
        lambda _name: Provider(),
    )
    row = {
        "id": "outbox-1",
        "direction": "outbound",
        "persona_id": "persona-1",
        "lead_ref": 7,
        "channel_binding_id": "binding-1",
        "correlation_id": "corr-1",
        "payload": {"text": "Oi"},
        "attempt_count": 1,
        "max_attempts": 5,
    }
    worker = WhatsAppDispatchWorker()

    try:
        worker._dispatch_outbound(row)
    except Exception as exc:
        worker._retry_or_dead_letter(row, exc)

    assert waiting[-1][0][:2] == ("outbox-1", "waiting_human")
    assert violations[-1]["violation_key"] == "attempt-failed:provider:outbox-1"
