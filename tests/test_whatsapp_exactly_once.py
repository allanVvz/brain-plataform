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

    assert conversations.commit(body, "internal-token") == {
        "ok": True,
        "handoff": False,
        "technical_failure": False,
        "correlation_id": "corr-route-owner",
    }
    assert captured["expected_decision_owner"] == "n8n_agents"
    assert isinstance(captured["context"], ConversationContext)
    assert isinstance(captured["decision"], ConversationDecision)
    assert isinstance(captured["response"], AgentResponse)


def test_commit_route_trims_large_knowledge_context_from_n8n_response(monkeypatch):
    """Regression for the 2026-08-10 incident: commit()'s full result can
    legitimately carry a graph_contract/RAG/proof payload well past 64KB
    (one real Aurora turn measured 80438 bytes). n8n's "Return canonical
    result" node echoes the /commit HTTP response verbatim, and the dispatch
    worker's response_limit used to truncate it mid-JSON -- turning an
    already-successful commit into a false "invalid result contract"
    failure that force-repaused the lead. The route must return a small,
    always-parseable envelope regardless of how large the internal result
    grows.
    """
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    oversized_knowledge_context = {
        "graph_contract": {"claims": [{"claim_type": f"claim-{i}", "text": "x" * 200} for i in range(400)]},
        "rag_chunks": [{"chunk_id": f"chunk-{i}", "text": "y" * 200} for i in range(200)],
    }
    assert len(json.dumps(oversized_knowledge_context).encode()) > 65_536

    full_result = {
        "ok": True,
        "handoff": False,
        "technical_failure": False,
        "message_id": "ai:corr-big",
        "outbound_buffer_id": "outbox-big",
        "reply_text": "Você consegue trazer o carro aqui para uma avaliação?",
        "route": "SDR",
        "stage": "novo",
        "knowledge_context": oversized_knowledge_context,
        "proof": {"valid": True, "ledger": oversized_knowledge_context},
        "qualification": {"missing_fields": ["nome_cliente"]},
        "graph_turn": {"ledger_id": "ledger-1"},
    }
    monkeypatch.setattr(conversation_runtime, "commit", lambda **_kwargs: full_result)

    body = conversations.CommitRequest(
        lead_ref=7,
        context=_context(),
        decision=_decision(),
        response=_response(),
        correlation_id="corr-big",
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
    )

    envelope = conversations.commit(body, "internal-token")
    serialized = json.dumps(envelope)

    assert "knowledge_context" not in envelope
    assert "proof" not in envelope
    assert "qualification" not in envelope
    assert "graph_turn" not in envelope
    assert len(serialized.encode()) < 4_096
    assert envelope == {
        "ok": True,
        "handoff": False,
        "technical_failure": False,
        "correlation_id": "corr-big",
        "message_id": "ai:corr-big",
        "outbound_buffer_id": "outbox-big",
        "reply_text": "Você consegue trazer o carro aqui para uma avaliação?",
        "route": "SDR",
        "stage": "novo",
    }

    # The exact contract the dispatch worker validates before reading
    # handoff/technical_failure -- proves the trimmed envelope still
    # satisfies it after a real JSON round-trip (not just in-memory).
    reparsed = json.loads(serialized)
    assert isinstance(reparsed, dict)
    assert any(key in reparsed for key in ("ok", "technical_failure", "handoff", "message_id"))


def test_repeated_n8n_commit_returns_existing_outbox_without_new_decision(monkeypatch):
    completed = []
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
        "claim_conversation_commit",
        lambda **_kwargs: {"state": "claimed"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "complete_conversation_commit",
        lambda **kwargs: completed.append(kwargs) or kwargs["result_payload"],
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
    assert completed[0]["result_payload"] == result


def test_repeated_n8n_handoff_commit_is_persisted_once(monkeypatch):
    state = {}
    calls = {"lead": 0, "log": 0, "event": 0}
    lead = {
        "id": 7,
        "persona_id": "persona-1",
        "channel_binding_id": "binding-1",
        "stage": "novo",
        "metadata": {},
    }
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _ref: lead,
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1"},
    )

    def claim(**_kwargs):
        if "result" in state:
            return {"state": "completed", "result": state["result"]}
        if state.get("processing"):
            return {"state": "processing"}
        state["processing"] = True
        return {"state": "claimed"}

    def complete(**kwargs):
        state["result"] = kwargs["result_payload"]
        return state["result"]

    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "claim_conversation_commit",
        claim,
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "complete_conversation_commit",
        complete,
    )
    monkeypatch.setattr(
        conversation_runtime.lead_qualification,
        "calculate",
        lambda **_kwargs: ({"score": 0}, "contatado"),
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "update_lead",
        lambda *_args, **_kwargs: calls.__setitem__("lead", calls["lead"] + 1),
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "insert_agent_log",
        lambda *_args, **_kwargs: calls.__setitem__("log", calls["log"] + 1),
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "insert_event",
        lambda *_args, **_kwargs: calls.__setitem__("event", calls["event"] + 1),
    )
    monkeypatch.setattr(
        conversation_runtime.whatsapp_outbox,
        "enqueue_outbound",
        lambda **_kwargs: pytest.fail("no-reply commit created an outbox"),
    )
    response = AgentResponse(
        reply_text=None,
        role=ConversationRoute.SDR,
        cart_state={},
        handoff_required=False,
    )
    kwargs = {
        "lead_ref": 7,
        "context": _context(),
        "decision": _decision(),
        "response": response,
        "correlation_id": "corr-no-reply",
        "phone_number_id": None,
        "channel_binding_id": "binding-1",
        "inbound_buffer_id": "buffer-in",
        "expected_decision_owner": "n8n_agents",
    }

    first = conversation_runtime.commit(**kwargs)
    duplicate = conversation_runtime.commit(**kwargs)

    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert duplicate["message_id"] is None
    # log=2: the pre-existing "decision committed" agent_log write, plus the
    # new observability event (emit_turn_event's "conversation.commit" row
    # added for trace_id-linked LLM/agent observability) -- both still only
    # fire once each for the real commit, never again on the dedup replay,
    # which is what this test is actually guarding.
    assert calls == {"lead": 1, "log": 2, "event": 1}


def test_v3_commercial_note_drops_stale_field_from_a_different_branch(monkeypatch):
    """Regression test for the 2026-08-06 finding.

    A lead carried over from before v3 (or from an earlier, unrelated
    branch/session) can still have a legacy `appointment_request` dict
    sitting in cart_state with an answer from that old session (e.g.
    modelo_veiculo). The old commit() logic merged that stale dict into
    commercial_note every turn and never cleared it, so the CRM kept
    showing an answer as "known" days after a completely different branch
    started, even though v3's own fact ledger never captured it for the
    live session. commercial_note (and the persisted cart_state) must
    reflect only what v3's own `facts` ledger currently knows.
    """
    persisted = {}
    lead = {
        "id": 7,
        "persona_id": "persona-1",
        "channel_binding_id": "binding-1",
        "stage": "novo",
        "metadata": {"commercial_note": {"modelo_veiculo": "Chevrolet Onix"}},
    }
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_lead_by_ref", lambda _ref: lead
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"}
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "claim_conversation_commit",
        lambda **_kwargs: {"state": "claimed"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "complete_conversation_commit",
        lambda **kwargs: kwargs["result_payload"],
    )

    def update_lead(_ref, update):
        persisted.update(update)

    monkeypatch.setattr(conversation_runtime.supabase_client, "update_lead", update_lead)
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_agent_log", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "commit_graph_turn_v3",
        lambda **_kwargs: {"proof_id": "proof-1", "ledger_revision": 1},
    )
    monkeypatch.setattr(
        conversation_runtime.whatsapp_outbox,
        "enqueue_outbound",
        lambda **_kwargs: pytest.fail("no-reply commit created an outbox"),
    )
    # No published document available -- commit() must degrade to
    # comparing owner_node_id against active_branch alone (the pre-
    # 2026-08-08 behavior) rather than crash or wrongly include/exclude
    # anything.
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_active_graph_publication", lambda *_a, **_k: None
    )

    context = _context().model_copy(
        update={
            "runtime_version": conversation_runtime.graph_agent_runtime_v3.RUNTIME_VERSION,
            "rag_nodes": [
                {
                    "node_type": "persona",
                    "data": {"commercial_note_fields": ["modelo_veiculo", "nome_cliente"]},
                }
            ],
        }
    )
    response = AgentResponse(
        reply_text=None,
        role=ConversationRoute.SDR,
        cart_state={
            # Legacy debris from a different, earlier branch/session.
            "appointment_request": {"modelo_veiculo": "Chevrolet Onix"},
            "active_branch_node_id": "aurora-product-interior",
            # v3's own live ledger: nome_cliente and servico belong to the
            # active branch; vehicle_color is a leftover fact from a
            # *different* branch (same key convention, different
            # owner_node_id) that should not leak into this branch's note.
            "facts": {
                "nome_cliente": {
                    "status": "known", "value": "Allan",
                    "owner_node_id": "aurora-product-interior",
                },
                "servico": {
                    "status": "known", "value": "higienizacao-interna",
                    "owner_node_id": "aurora-product-interior",
                },
                "vehicle_color": {
                    "status": "known", "value": "Prata",
                    "owner_node_id": "aurora-product-polish",
                },
            },
        },
        handoff_required=False,
        proof={"missing_fields": ["modelo_veiculo"]},
    )

    conversation_runtime.commit(
        lead_ref=7,
        context=context,
        decision=_decision(),
        response=response,
        correlation_id="corr-stale-note",
        phone_number_id=None,
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
        expected_decision_owner="n8n_agents",
    )

    commercial_note = persisted["metadata"]["commercial_note"]
    assert commercial_note.get("modelo_veiculo") is None
    assert commercial_note["nome_cliente"] == "Allan"
    assert commercial_note["servico"] == "higienizacao-interna"
    assert commercial_note.get("vehicle_color") is None
    assert "appointment_request" not in persisted["metadata"]["conversation_state"]
    assert persisted["nome"] == "Allan"
    assert persisted["interesse_produto"] == "higienizacao-interna"


def test_v3_commercial_note_includes_a_shared_field_owned_by_the_persona(monkeypatch):
    """Regression test for the 2026-08-08 finding.

    Fixing the repeated-question bug that same day (unifying shared
    qualification fields like nome_cliente/modelo_veiculo/vehicle_year to
    a single owner -- the persona node -- across every branch, instead of
    each branch owning its own copy) broke this exact commercial_note
    filter: comparing owner_node_id to active_branch directly meant a
    fact legitimately owned by the persona (not the branch) was silently
    excluded from the note, even though it was correctly captured in v3's
    own fact ledger and shown as resolved in the lead's qualification
    metadata. Reading the active branch's own declared field owners from
    its published contract -- which includes the persona wherever the
    branch's contract says a field is persona-owned -- fixes it, while a
    fact genuinely owned by a *different, unrelated* branch must still be
    excluded (same case the sibling test above covers).
    """
    persisted = {}
    lead = {
        "id": 8,
        "persona_id": "persona-1",
        "channel_binding_id": "binding-1",
        "stage": "novo",
        "metadata": {},
    }
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_lead_by_ref", lambda _ref: lead
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"}
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "claim_conversation_commit",
        lambda **_kwargs: {"state": "claimed"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "complete_conversation_commit",
        lambda **kwargs: kwargs["result_payload"],
    )

    def update_lead(_ref, update):
        persisted.update(update)

    monkeypatch.setattr(conversation_runtime.supabase_client, "update_lead", update_lead)
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_agent_log", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "commit_graph_turn_v3",
        lambda **_kwargs: {"proof_id": "proof-1", "ledger_revision": 1},
    )
    monkeypatch.setattr(
        conversation_runtime.whatsapp_outbox,
        "enqueue_outbound",
        lambda **_kwargs: pytest.fail("no-reply commit created an outbox"),
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_active_graph_publication",
        lambda *_a, **_k: {
            "document_json": {
                "branch_contracts": {
                    "aurora-product-interior": {
                        "fields": [
                            {"key": "nome_cliente", "owner_node_id": "aurora-persona"},
                            {"key": "servico", "owner_node_id": "aurora-product-interior"},
                        ]
                    }
                }
            }
        },
    )

    context = _context().model_copy(
        update={
            "runtime_version": conversation_runtime.graph_agent_runtime_v3.RUNTIME_VERSION,
            "rag_nodes": [
                {
                    "node_type": "persona",
                    "data": {"commercial_note_fields": ["modelo_veiculo", "nome_cliente"]},
                }
            ],
        }
    )
    response = AgentResponse(
        reply_text=None,
        role=ConversationRoute.SDR,
        cart_state={
            "active_branch_node_id": "aurora-product-interior",
            "facts": {
                # Persona-owned, not the active branch itself -- the exact
                # case the old owner_node_id == active_branch check broke.
                "nome_cliente": {
                    "status": "known", "value": "Allan",
                    "owner_node_id": "aurora-persona",
                },
                "servico": {
                    "status": "known", "value": "higienizacao-interna",
                    "owner_node_id": "aurora-product-interior",
                },
                # A genuinely stale fact from an unrelated branch, absent
                # from this branch's own contract entirely -- must stay excluded.
                "vehicle_color": {
                    "status": "known", "value": "Prata",
                    "owner_node_id": "aurora-product-polish",
                },
            },
        },
        handoff_required=False,
        proof={"missing_fields": []},
    )

    conversation_runtime.commit(
        lead_ref=8,
        context=context,
        decision=_decision(),
        response=response,
        correlation_id="corr-shared-owner",
        phone_number_id=None,
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
        expected_decision_owner="n8n_agents",
    )

    commercial_note = persisted["metadata"]["commercial_note"]
    assert commercial_note["nome_cliente"] == "Allan"
    assert commercial_note["servico"] == "higienizacao-interna"
    assert commercial_note.get("vehicle_color") is None


def test_validation_lead_commit_persists_the_reply_without_a_real_send(monkeypatch):
    """wa_validator sessions must get a persisted reply, never a real send.

    Confirmed live 2026-08-08 (first pass): running the WA Validator against
    Aurora in n8n_agents mode produced a real, well-formed agent reply, but
    commit() 409'd on whatsapp_outbox._recipient_for_lead -- the validator's
    synthetic lead has no real phone/JID by design. Giving it a fake-but-
    valid-shaped phone to dodge the 409 was explicitly rejected (a worker
    could then queue a real send to it). The first fix skipped the outbox
    entirely for validation leads, but enqueue_outbound is also the only
    thing that writes the agent's reply into the `messages` table --
    skipping it meant the validation-leads conversation view showed only
    the customer's side, never the bot's.

    Confirmed live 2026-08-08 (second pass): the correct fix calls
    supabase_client.enqueue_whatsapp_envelope directly (the same primitive
    enqueue_outbound itself calls) with a buffer status outside
    claim_whatsapp_buffer's claimable set ('buffered', 'retry',
    'pending_send' -- migration 065), so the row is written for display but
    no dispatch worker will ever pick it up.
    """
    lead = {
        "id": 7,
        "persona_id": "persona-1",
        "channel_binding_id": "binding-1",
        "stage": "novo",
        "metadata": {"validation": {"is_validation": True, "session_id": "sess-1"}},
    }
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_lead_by_ref", lambda _ref: lead
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"}
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "claim_conversation_commit",
        lambda **_kwargs: {"state": "claimed"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "complete_conversation_commit",
        lambda **kwargs: kwargs["result_payload"],
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_whatsapp_buffer_by_idempotency",
        lambda _key: None,
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "update_lead", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_agent_log", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        conversation_runtime.whatsapp_outbox,
        "enqueue_outbound",
        lambda **_kwargs: pytest.fail(
            "validation lead reached the real WhatsApp outbox"
        ),
    )
    captured_envelopes = []

    def fake_enqueue_envelope(*, buffer, message):
        captured_envelopes.append({"buffer": buffer, "message": message})
        return {"buffer_id": "buffer-out-1", "status": buffer["status"]}

    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "enqueue_whatsapp_envelope",
        fake_enqueue_envelope,
    )

    result = conversation_runtime.commit(
        lead_ref=7,
        context=_context(),
        decision=_decision(),
        response=_response(),
        correlation_id="corr-validation",
        phone_number_id=None,
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-in",
        expected_decision_owner="n8n_agents",
    )

    assert result["reply_text"] == "Ola!"
    assert result["outbound_buffer_id"] == "buffer-out-1"
    assert len(captured_envelopes) == 1
    envelope = captured_envelopes[0]
    assert envelope["buffer"]["status"] not in {"buffered", "retry", "pending_send"}
    assert envelope["message"]["role"] == "assistant"
    assert envelope["message"]["content"] == "Ola!"
    assert envelope["message"]["direction"] == "outbound"


def test_invalid_branch_proof_still_commits_individually_accepted_persona_fact(monkeypatch):
    lead = {
        "id": 7, "persona_id": "persona-1", "channel_binding_id": "binding-1",
        "stage": "novo", "metadata": {},
    }
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_lead_by_ref", lambda _ref: lead,
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1", "persona_id": "persona-1", "active": True,
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "claim_conversation_commit",
        lambda **_kwargs: {"state": "claimed"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "complete_conversation_commit",
        lambda **kwargs: kwargs["result_payload"],
    )
    monkeypatch.setattr(conversation_runtime.supabase_client, "update_lead", lambda *_a, **_k: None)
    monkeypatch.setattr(conversation_runtime.supabase_client, "insert_agent_log", lambda *_a, **_k: None)
    monkeypatch.setattr(conversation_runtime.supabase_client, "insert_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        conversation_runtime.whatsapp_outbox, "enqueue_outbound",
        lambda **_kwargs: {"buffer_id": "outbound-1", "status": "pending_send"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_whatsapp_buffer_by_idempotency",
        lambda _key: None,
    )
    captured = {}
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "commit_graph_turn_v3",
        lambda **kwargs: captured.update(kwargs) or {"ledger_revision": 1},
    )
    fact = {
        "field_key": "can_visit_in_person", "status": "known", "value": True,
        "owner_node_id": "persona:generic", "source_message_id": "msg-1",
        "evidence_span": "Levo até vocês", "confidence": 0.95,
    }
    context = _context().model_copy(update={
        "runtime_version": conversation_runtime.graph_agent_runtime_v3.RUNTIME_VERSION,
        "publication_id": "publication-1",
        "retrieval_trace": {"ledger_revision": 0},
    })
    response = _response().model_copy(update={
        "proof": {
            "valid": False, "errors": ["keep_without_active_branch"],
            "accepted_facts": [fact],
        },
        "cart_state": {"facts": {}, "asked_question_node_ids": []},
    })

    conversation_runtime.commit(
        lead_ref=7, context=context, decision=_decision(), response=response,
        correlation_id="corr-fact", phone_number_id=None,
        channel_binding_id="binding-1", inbound_buffer_id="buffer-in",
        expected_decision_owner="n8n_agents",
    )

    assert captured["p_facts"] == [fact]


def test_concurrent_commit_reentry_pauses_the_lead(monkeypatch):
    violations = []
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
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "claim_conversation_commit",
        lambda **_kwargs: {"state": "processing"},
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "record_whatsapp_safety_violation",
        lambda **kwargs: violations.append(kwargs) or {},
    )

    with pytest.raises(RuntimeError, match="already processing"):
        conversation_runtime.commit(
            lead_ref=7,
            context=_context(),
            decision=_decision(),
            response=_response(),
            correlation_id="corr-reentry",
            phone_number_id=None,
            channel_binding_id="binding-1",
            inbound_buffer_id="buffer-in",
            expected_decision_owner="n8n_agents",
        )

    assert violations[0]["lead_ref"] == 7
    assert violations[0]["violation_key"] == (
        "conversation_commit_reentry:buffer-in"
    )


def test_thousand_repeated_inbound_events_yield_one_decision_outbox_and_provider_call(
    monkeypatch,
):
    binding = {
        "id": "binding-1",
        "persona_id": "persona-1",
        "provider": "meta_cloud",
        "active": True,
        "connection_status": "connected",
        "whatsapp_phone_number_id": "business-1",
        "provider_secret_ciphertext": "encrypted-token",
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
        "connection_status": "connected",
        "provider_instance_key": "brain-persona-1",
        "provider_secret_ciphertext": "encrypted-token",
        "metadata": {
            "decision_owner": "deterministic",
            "transport_mode": "provider_direct",
        },
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
