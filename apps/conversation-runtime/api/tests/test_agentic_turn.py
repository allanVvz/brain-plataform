from __future__ import annotations

import pytest
import httpx
from brain_contracts import ExecuteAgenticTurnV1
from pydantic import ValidationError
from routes import conversations
from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ConversationReplyV1,
    ResolvedUnderstandingV1,
    TurnUnderstandingV1,
)
from services import agentic_turn, graph_agent_runtime_v3, graph_proof_checker_v3


class _HttpClient:
    def __init__(self, response: httpx.Response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, *_args, **_kwargs):
        return self.response


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


def test_model_http_failure_keeps_only_sanitized_provider_diagnostic(monkeypatch):
    response = httpx.Response(
        402,
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
        json={
            "error": {
                "message": "Insufficient Balance",
                "type": "unknown_error",
                "code": "invalid_request_error",
                "secret": "must-not-be-persisted",
            },
            "request": {"authorization": "Bearer must-not-be-persisted"},
        },
    )
    monkeypatch.setattr(
        agentic_turn.httpx,
        "Client",
        lambda **_kwargs: _HttpClient(response),
    )

    with pytest.raises(agentic_turn.AgenticTurnError) as raised:
        agentic_turn._call_json(
            agentic_turn.ModelBinding(
                "deepseek-flash",
                "https://api.deepseek.com/chat/completions",
                "sk-must-not-be-persisted",
                "json_object",
            ),
            stage="understanding_model",
            system="Return JSON.",
            payload={"value": "fixture"},
            schema_name="fixture",
            schema={"type": "object"},
            temperature=0,
        )

    exc = raised.value
    assert str(exc) == (
        "model request failed: HTTP 402 "
        "(invalid_request_error; unknown_error; Insufficient Balance)"
    )
    assert exc.diagnostic == {
        "http_status": 402,
        "provider_error_type": "unknown_error",
        "provider_error_code": "invalid_request_error",
        "provider_message": "Insufficient Balance",
    }
    assert "must-not-be-persisted" not in repr(exc.diagnostic)


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
    assert "Capture every stated fact" in captured["system"]
    assert "expected_answer_field_key is set" in captured["system"]
    assert "free-text field preserve" in captured["system"]
    assert "audience_signals are optional" in captured["system"]


def test_two_model_calls_resolve_facts_before_reply_and_commit_once(monkeypatch):
    context = _context()
    calls: list[str] = []
    captured: dict = {}

    def fake_build_context(**kwargs):
        captured["context_message"] = kwargs["message"]
        return context

    monkeypatch.setattr(agentic_turn.conversation_runtime, "build_context", fake_build_context)
    monkeypatch.setattr(
        agentic_turn.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        agentic_turn.site_origin,
        "resolve",
        lambda _message, _persona_id: {"event_id": "site-event-1", "audience_node_id": "audience:prepare-sale"},
    )
    monkeypatch.setattr(
        agentic_turn,
        "_model_binding",
        lambda _persona_id: agentic_turn.ModelBinding(
            "fixture-model", "https://model.invalid/v1", "secret", "json_schema"
        ),
    )

    def fake_call(_binding, *, stage, **kwargs):
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
        captured["reply_system"] = kwargs["system"]
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
        persona_slug="fixture", lead_ref=7,
        message="uso proprio Código de atendimento: BI-0123456789ABCDEF",
        message_id="message-1", correlation_id="correlation-1",
        phone_number_id=None, channel_binding_id="binding-1",
        inbound_buffer_id="buffer-1",
    )

    assert calls == ["understanding_model", "reply_model"]
    assert captured["context_message"] == "uso proprio"
    assert captured["understanding"].facts[0].owner_node_id == "audience:retail"
    assert captured["commit"]["inbound_buffer_id"] == "buffer-1"
    assert captured["commit"]["site_origin"]["event_id"] == "site-event-1"
    assert captured["commit"]["expected_decision_owner"] == "n8n_agents"
    assert "warm, concise reply" in captured["reply_system"]
    assert "rather than guessing" in captured["reply_system"]
    assert "claim_contract exactly" in captured["reply_system"]
    assert result["model_calls"] == 2


def test_reply_claim_contract_exposes_only_graph_authorized_price_evidence():
    resolved = ResolvedUnderstandingV1(
        understanding=TurnUnderstandingV1(),
        context=_context(),
        prospective_state={},
        conversation_brief={
            "price_comparison_catalog": [{
                "product_node_id": "product:lowest",
                "amount": 29.9,
                "currency": "BRL",
                "evidence_node_id": "faq:lowest-price",
                "unrelated": "must not reach the model contract",
            }],
        },
    )

    contract = agentic_turn._reply_claim_contract(resolved)

    assert contract["claims_are_optional"] is True
    assert contract["price_comparison"]["allowed_catalog"] == [{
        "product_node_id": "product:lowest",
        "amount": 29.9,
        "currency": "BRL",
        "evidence_node_id": "faq:lowest-price",
    }]


def test_reply_claim_contract_exposes_only_retained_graph_claim_evidence():
    context = _context().model_copy(update={
        "graph_contract": {
            "claims": [
                {
                    "claim_type": "service_detail",
                    "evidence_node_ids": ["faq:service", "faq:not-retrieved"],
                },
                {
                    "claim_type": "availability",
                    "evidence_node_ids": ["faq:availability"],
                },
            ],
        },
    })
    resolved = ResolvedUnderstandingV1(
        understanding=TurnUnderstandingV1(),
        context=context,
        prospective_state={},
        conversation_brief={},
        context_manifest={"retained_node_ids": ["faq:service", "faq:availability"]},
    )

    contract = agentic_turn._reply_claim_contract(resolved)

    assert contract["authorized_claims"] == [
        {
            "claim_type": "service_detail",
            "evidence_node_ids": ["faq:service"],
            "evidence_chunk_ids": [],
        },
        {
            "claim_type": "availability",
            "evidence_node_ids": ["faq:availability"],
            "evidence_chunk_ids": [],
        },
    ]


def test_public_information_claim_is_valid_in_reply_and_model_schema():
    reply = ConversationReplyV1.model_validate({
        "contract_version": "conversation_reply_v1",
        "reply": "Conte o serviço e os dados do veículo para pedir a avaliação.",
        "asked_field_key": None,
        "claims": [{
            "claim_type": "public_information",
            "value": {"text": "Como pedir uma avaliação"},
            "evidence_node_ids": ["faq:assessment"],
            "evidence_chunk_ids": [],
        }],
        "cited_node_ids": ["faq:assessment"],
        "cited_chunk_ids": [],
        "handoff_requested": False,
        "knowledge_gap": False,
    })

    assert reply.claims[0].claim_type == "public_information"
    assert "public_information" in agentic_turn._reply_schema()["properties"]["claims"]["items"]["properties"]["claim_type"]["enum"]


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


def test_unavailable_audience_signal_is_audited_without_blocking_valid_facts():
    context = _context().model_copy(update={
        "available_services": [{"branch_anchor_node_id": "audience:retail"}],
    })

    understanding = agentic_turn._read_understanding(
        {
            "contract_version": "turn_understanding_v1",
            "facts": [{
                "key": "profile", "value": "personal", "status": "known",
                "evidence_span": "uso proprio", "confidence": 1,
            }],
            "branch_selections": [],
            "confirmation": {"state": "none"},
            "customer_questions": [],
            "mentioned_node_ids": [],
            "audience_signals": [
                {
                    "audience_node_id": "audience:retail",
                    "evidence_span": "uso proprio", "confidence": 1,
                },
                {
                    "audience_node_id": "audience:not-published",
                    "evidence_span": "uso proprio", "confidence": 1,
                },
            ],
            "interaction_observation": {"kind": "continue_current"},
        },
        context=context,
        message="uso proprio",
        message_id="message-1",
    )

    assert [signal.audience_node_id for signal in understanding.audience_signals] == [
        "audience:retail"
    ]
    assert understanding.facts[0].field_key == "profile"
    assert understanding.validation_observations == [
        "ignored_unavailable_audience_signal:audience:not-published"
    ]


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


def test_candidate_proof_requires_matching_running_validator_session(monkeypatch):
    session_id = "12345678-1234-1234-1234-123456789012"
    session = {
        "id": session_id, "status": "running", "persona_slug": "fixture",
        "lead_ref": 7, "channel_binding_id": "binding-1",
        "publication_id": "publication-1",
        "script": {"meta": {
            "publication_id": "publication-1", "graph_checksum": "sha256:fixture",
        }},
    }
    monkeypatch.setattr(
        agentic_turn.supabase_client, "get_wa_validator_session",
        lambda _session_id: session,
    )
    lead = {
        "lead_id": "validator_12345678",
        "metadata": {"validation": {"is_validation": True, "session_id": session_id}},
    }
    values = dict(
        publication_id="publication-1", context=_context(), lead=lead,
        lead_ref=7, persona_slug="fixture", channel_binding_id="binding-1",
    )
    validator = agentic_turn._validated_candidate_publication_id
    assert validator(provider="internal_validator", **values) == "publication-1"
    assert validator(provider="meta_cloud", **values) is None
    assert validator(provider="internal_validator", **{**values, "lead": {}}) is None
    assert validator(provider="internal_validator", **{
        **values, "channel_binding_id": "other-binding",
    }) is None
    session["publication_id"] = "another-publication"
    assert validator(provider="internal_validator", **values) is None


def test_compiled_proof_requires_exact_validator_publication_id():
    def proof(status, candidate_id=None):
        return graph_proof_checker_v3.check(
            publication={
                "id": "candidate-1", "status": status, "checksum": "sha256:fixture",
                "document_json": {"branch_anchors": []},
            },
            contract={"fields": []},
            ledger={"graph_checksum": "sha256:fixture", "facts": {}},
            proposal={"branch_action": "none", "extracted_facts": [], "claims": []},
            message="ola", source_message_id="message-1",
            package_node_ids=set(), package_chunk_ids=set(),
            active_branch_node_id=None, branch_selection_allowed=False,
            branch_switch_allowed=False,
            validation_publication_id=candidate_id,
        )

    assert "publication_not_active" in proof("compiled")["gating_errors"]
    assert "publication_not_active" in proof("compiled", "other")["gating_errors"]
    assert "publication_not_active" not in proof("compiled", "candidate-1")["errors"]
    assert "publication_not_active" in proof("draft", "candidate-1")["gating_errors"]


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
            agentic_turn.AgenticTurnError(
                "reply_model",
                "model request failed: HTTP 402",
                diagnostic={
                    "http_status": 402,
                    "provider_error_code": "invalid_request_error",
                    "provider_message": "Insufficient Balance",
                },
            )
        ),
    )
    captured = {}

    def fake_terminalize(command):
        captured["command"] = command
        return {
            "ok": False, "status": "technical_handoff",
            "technical_failure": True, "handoff": True,
            "outbound_enqueued": False, "stage": command.stage,
        }

    monkeypatch.setattr(
        conversations,
        "_terminalize_technical_failure",
        fake_terminalize,
    )

    result = conversations.execute_agentic(body, x_webhook_token="token")

    assert result["ok"] is False
    assert result["technical_failure"] is True
    assert result["outbound_enqueued"] is False
    assert result["stage"] == "reply_model"
    assert captured["command"].diagnostic == {
        "workflow_template": "runtime_agentic_v1",
        "execution_strategy": "interpret_then_respond",
        "failed_node": "reply_model",
        "message": "model request failed: HTTP 402",
        "http_code": 402,
    }
