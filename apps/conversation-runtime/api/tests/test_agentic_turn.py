from __future__ import annotations

import pytest
from brain_contracts import ExecuteAgenticTurnV1
from pydantic import ValidationError
from routes import conversations
from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ResolvedUnderstandingV1,
)
from services import agentic_turn, graph_agent_runtime_v3


def _context() -> ConversationContext:
    return ConversationContext(
        persona_slug="fixture",
        agent_slug="agent",
        execution_strategy="interpret_then_respond",
        graph_version=1,
        graph_checksum="sha256:fixture",
        messages=[],
        cart={"facts_by_key": {}, "asked_field_keys": ["profile"]},
        rag_nodes=[],
        rag_paths=[],
        graph_contract={
            "fields": [{"key": "profile", "owner_node_id": "audience:retail"}],
        },
        publication_id="publication-1",
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
    )


def test_active_publication_is_not_a_shadow_session():
    active = {"id": "publication-active"}

    assert not graph_agent_runtime_v3._is_shadow_publication(active, active)
    assert graph_agent_runtime_v3._is_shadow_publication(
        {"id": "publication-candidate"}, active,
    )
    assert graph_agent_runtime_v3._is_shadow_publication(active, None)


def test_understanding_instruction_extracts_a_direct_free_text_answer(monkeypatch):
    captured: dict = {}

    def fake_call(_binding, *, system, **_kwargs):
        captured["system"] = system
        return ({"facts": [{"key": "unknown", "evidence_span": "para o dia a dia"}]}, {})

    monkeypatch.setattr(
        agentic_turn.conversation_runtime, "build_context", lambda **_kwargs: _context(),
    )
    monkeypatch.setattr(
        agentic_turn.supabase_client, "get_lead_by_ref", lambda _lead_ref: {"persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        agentic_turn, "_model_binding",
        lambda _persona_id: agentic_turn.ModelBinding("model", "https://model.invalid", "secret", "json_schema"),
    )
    monkeypatch.setattr(agentic_turn, "_call_json", fake_call)
    with pytest.raises(agentic_turn.AgenticTurnError):
        agentic_turn.execute(
            persona_slug="fixture", lead_ref=1, message="para o dia a dia",
            message_id="message-1", correlation_id="correlation-1",
            phone_number_id=None, channel_binding_id="binding-1",
            inbound_buffer_id="inbound-1",
        )
    assert "expected_answer_field_key" in captured["system"]
    assert "free-text field" in captured["system"]


def test_two_model_calls_resolve_facts_before_reply_and_commit_once(monkeypatch):
    context = _context()
    calls: list[str] = []
    captured: dict = {}

    monkeypatch.setattr(
        agentic_turn.conversation_runtime,
        "build_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        agentic_turn.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        agentic_turn,
        "_model_binding",
        lambda _persona_id: agentic_turn.ModelBinding(
            "fixture-model", "https://model.invalid/v1", "secret", "json_schema"
        ),
    )

    def fake_call(_binding, *, stage, **_kwargs):
        calls.append(stage)
        if stage == "understanding_model":
            return ({
                "contract_version": "turn_understanding_v1",
                "facts": [{
                    "key": "profile", "value": "personal", "status": "known",
                    "evidence_span": "uso proprio", "confidence": 1,
                }],
                "branch_selections": [],
                "confirmation": {"state": "none"},
                "customer_questions": [],
                "interaction_observation": {"kind": "continue_current"},
            }, {"prompt_tokens": 10, "completion_tokens": 5})
        return ({
            "contract_version": "conversation_reply_v1",
            "reply": "Entendi. O que voce procura?",
            "asked_field_key": None,
            "claims": [],
            "cited_node_ids": [],
            "cited_chunk_ids": [],
            "handoff_requested": False,
        }, {"prompt_tokens": 20, "completion_tokens": 8})

    monkeypatch.setattr(agentic_turn, "_call_json", fake_call)

    def fake_resolve(_context, *, understanding, **_kwargs):
        captured["understanding"] = understanding
        accepted = [understanding.facts[0].model_dump(mode="json")]
        return ResolvedUnderstandingV1(
            understanding=understanding,
            context=context,
            prospective_state={"facts_by_key": {"profile": accepted}},
            conversation_brief={"eligible_question_guides": []},
            context_manifest={"strategy": "graph_scoped_relevance"},
            resolution_proof={"valid": True, "accepted_facts": accepted},
        )

    monkeypatch.setattr(agentic_turn.conversation_runtime, "resolve_understanding", fake_resolve)
    monkeypatch.setattr(
        agentic_turn.conversation_runtime,
        "decide_agentic",
        lambda *_args, **_kwargs: (
            ConversationDecision(
                intent="collect_graph_fields", route="SDR", confidence=1,
                lead_stage="engajado",
            ),
            AgentResponse(
                reply_text="Entendi. O que voce procura?", role="SDR",
                cart_state={}, proof={"valid": True, "delivery_authorized": True},
            ),
        ),
    )

    def fake_commit(**kwargs):
        captured["commit"] = kwargs
        return {"ok": True, "outbound_enqueued": True}

    monkeypatch.setattr(agentic_turn.conversation_runtime, "commit", fake_commit)

    result = agentic_turn.execute(
        persona_slug="fixture", lead_ref=7, message="uso proprio",
        message_id="message-1", correlation_id="correlation-1",
        phone_number_id=None, channel_binding_id="binding-1",
        inbound_buffer_id="buffer-1",
    )

    assert calls == ["understanding_model", "reply_model"]
    assert captured["understanding"].facts[0].owner_node_id == "audience:retail"
    assert captured["commit"]["inbound_buffer_id"] == "buffer-1"
    assert captured["commit"]["expected_decision_owner"] == "n8n_agents"
    assert result["model_calls"] == 2


def test_non_literal_fact_evidence_fails_without_reply_call(monkeypatch):
    context = _context()
    monkeypatch.setattr(agentic_turn.conversation_runtime, "build_context", lambda **_kwargs: context)
    monkeypatch.setattr(agentic_turn.supabase_client, "get_lead_by_ref", lambda _lead_ref: {"persona_id": "p"})
    monkeypatch.setattr(agentic_turn, "_model_binding", lambda _persona_id: agentic_turn.ModelBinding(
        "fixture", "https://model.invalid", "secret", "json_object"
    ))
    monkeypatch.setattr(agentic_turn, "_call_json", lambda *_args, **_kwargs: ({
        "contract_version": "turn_understanding_v1",
        "facts": [{"key": "profile", "value": "personal", "status": "known",
                   "evidence_span": "texto inventado", "confidence": 1}],
        "branch_selections": [], "confirmation": {"state": "none"},
        "customer_questions": [], "interaction_observation": {"kind": "continue_current"},
    }, {}))

    try:
        agentic_turn.execute(
            persona_slug="fixture", lead_ref=7, message="uso proprio",
            message_id="m", correlation_id="c", phone_number_id=None,
            channel_binding_id="b", inbound_buffer_id="i",
        )
    except agentic_turn.AgenticTurnError as exc:
        assert exc.stage == "understanding_validation"
    else:
        raise AssertionError("invented evidence must fail closed")


def test_staged_publication_is_internal_validator_only():
    payload = {
        "persona_slug": "fixture", "lead_ref": 7, "message": "ola",
        "correlation_id": "c", "channel_binding_id": "b",
        "inbound_buffer_id": "i", "publication_id": "staged",
    }
    with pytest.raises(ValidationError):
        ExecuteAgenticTurnV1(**payload, provider="meta_cloud")
    assert ExecuteAgenticTurnV1(
        **payload, provider="internal_validator"
    ).publication_id == "staged"


def test_agentic_failure_returns_truthful_canonical_handoff(monkeypatch):
    body = ExecuteAgenticTurnV1(
        persona_slug="fixture", lead_ref=7, message="ola",
        correlation_id="c", channel_binding_id="b", inbound_buffer_id="i",
        provider="internal_validator",
    )
    monkeypatch.setattr(conversations.internal_auth, "authorize_webhook_token", lambda _token: None)
    monkeypatch.setattr(
        conversations.agentic_turn,
        "execute",
        lambda **_kwargs: (_ for _ in ()).throw(
            agentic_turn.AgenticTurnError("reply_model", "provider timeout")
        ),
    )
    monkeypatch.setattr(
        conversations,
        "_terminalize_technical_failure",
        lambda command: {
            "ok": False, "status": "technical_handoff",
            "technical_failure": True, "handoff": True,
            "outbound_enqueued": False, "stage": command.stage,
        },
    )

    result = conversations.execute_agentic(body, x_webhook_token="token")

    assert result["ok"] is False
    assert result["technical_failure"] is True
    assert result["outbound_enqueued"] is False
    assert result["stage"] == "reply_model"
