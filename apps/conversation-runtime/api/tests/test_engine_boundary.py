from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from routes import conversations
from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ConversationRoute,
)
from services import (
    conversation_runtime,
    graph_agent_runtime_v3,
    graph_proof_checker_v3,
)


def _context(*, runtime_version: str = graph_agent_runtime_v3.RUNTIME_VERSION) -> ConversationContext:
    return ConversationContext(
        persona_slug="boundary-persona",
        agent_slug="boundary-agent",
        graph_version=1,
        graph_checksum="checksum-boundary",
        messages=[{"role": "user", "content": "mensagem", "message_id": "in-1"}],
        cart={"facts": {}, "facts_by_key": {}, "asked_question_node_ids": []},
        rag_nodes=[],
        rag_paths=[],
        graph_contract={
            "questions": {
                "graph-question": {"text": "PERGUNTA PUBLICADA QUE NAO PODE VAZAR"},
            },
        },
        publication_id="publication-1",
        runtime_version=runtime_version,
        journey_id="journey-1",
    )


def _decision() -> ConversationDecision:
    return ConversationDecision(
        classifier="graph_proof_checker_v3",
        intent="collect_graph_fields",
        route=ConversationRoute.SDR,
        confidence=1,
        lead_stage="engajado",
    )


def test_agentic_canary_preserves_grounded_model_reply_byte_for_byte(monkeypatch):
    sentinel = "  Resposta sentinela natural, com evidencia.\nSegundo paragrafo!  "
    response = AgentResponse(
        reply_text=sentinel,
        role=ConversationRoute.SDR,
        cart_state={},
        proof={"valid": True, "delivery_authorized": True},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_decide",
        lambda context, model_observation: (_decision(), response),
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_with_structural_proof_audit",
        lambda context, decision, current: current,
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_apply_journey_policy",
        lambda context, decision, current, model_observation: (
            decision,
            current.model_copy(update={"reply_text": "PERGUNTA PUBLICADA QUE NAO PODE VAZAR?"}),
        ),
    )

    _, result = graph_agent_runtime_v3.decide(
        _context(), model_observation={"proposal": {"reply": sentinel}},
    )

    assert result.reply_text == sentinel
    assert result.proof["model_reply_preserved"] is True


def test_agentic_repair_never_runs_a_public_copy_fallback(monkeypatch):
    repair = AgentResponse(
        reply_text=None,
        role=ConversationRoute.SDR,
        cart_state={},
        proof={
            "valid": False,
            "delivery_authorized": False,
            "repair_required": True,
        },
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_decide",
        lambda context, model_observation: (_decision(), repair),
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_with_structural_proof_audit",
        lambda context, decision, current: current,
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "_apply_journey_policy",
        lambda *args, **kwargs: pytest.fail("journey fallback composed public copy"),
    )

    _, result = graph_agent_runtime_v3.decide(
        _context(), model_observation={"repair_attempt": 0},
    )

    assert result.reply_text is None
    assert result.proof["repair_required"] is True
    assert result.proof["model_reply_preserved"] is True


def test_proved_branch_selection_satisfies_selector_dependencies_same_turn():
    contract = {
        "fields": [
            {
                "key": "purchase_profile",
                "owner_node_id": "audience:retail",
                "required": True,
                "branch_selection_field": True,
                "accepted_statuses": ["known"],
            },
            {
                "key": "retail_need",
                "owner_node_id": "audience:retail",
                "required": True,
                "depends_on": ["purchase_profile"],
                "question_node_id": "faq:retail-need",
                "accepted_statuses": ["known"],
            },
        ],
    }
    operations = [{
        "action": "add",
        "branch_anchor_node_id": "audience:retail",
        "branch_path_checksum": "checksum:retail",
        "evidence_span": "uso proprio",
        "evidence_type": "exact_catalog",
        "resolution_method": "exact_catalog",
    }]
    projected = (
        graph_agent_runtime_v3._prospective_contract_facts_for_service_operations(
            contract=contract,
            contract_facts={},
            operations=operations,
            document={
                "common_contract": {"fields": [{
                    "key": "purchase_profile",
                    "branch_selection_field": True,
                }]},
                "node_by_id": {
                    "audience:retail": {
                        "slug": "uso-proprio-varejo",
                        "title": "Uso proprio / varejo",
                    },
                },
            },
            grouped_facts={},
            source_message_id="inbound:1",
            service_proof={"valid": True},
        )
    )

    assert projected["purchase_profile"]["value"] == "uso-proprio-varejo"
    askable = graph_proof_checker_v3.askable_pending_fields(contract, projected)
    assert [field["key"] for field in askable] == ["retail_need"]


def test_decision_request_requires_model_observation():
    with pytest.raises(ValidationError):
        conversations.DecisionRequest.model_validate({"context": _context().model_dump()})


def test_decide_route_calls_only_agentic_entrypoint(monkeypatch):
    monkeypatch.setattr(
        conversations.internal_auth,
        "authorize_webhook_token",
        lambda token: None,
    )
    monkeypatch.setattr(
        conversations.conversation_runtime,
        "decide_deterministic",
        lambda *args, **kwargs: pytest.fail("deterministic engine was reached"),
    )
    monkeypatch.setattr(
        conversations.conversation_runtime,
        "decide_agentic",
        lambda *args, **kwargs: (
            _decision(),
            AgentResponse(
                reply_text="modelo",
                role=ConversationRoute.SDR,
                cart_state={},
                proof={"valid": True, "model_reply_preserved": True},
            ),
        ),
    )
    body = conversations.DecisionRequest(
        context=_context(), model_observation={"proposal": {"reply": "modelo"}},
    )

    result = conversations.decide(body, x_webhook_token="token")

    assert result["response"]["reply_text"] == "modelo"


def test_agentic_entrypoint_rejects_deterministic_context():
    with pytest.raises(RuntimeError, match="requires a graph_agent_runtime_v3 context"):
        conversation_runtime.decide_agentic(
            _context(runtime_version="conversation_v2"),
            model_observation={},
        )


def test_commit_fails_closed_when_binding_owner_differs(monkeypatch):
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda lead_ref: {
            "id": str(lead_ref),
            "persona_id": "persona-1",
            "channel_binding_id": "binding-1",
        },
    )
    monkeypatch.setattr(
        conversation_runtime.supabase_client,
        "get_workflow_binding_by_id",
        lambda binding_id: {
            "id": binding_id,
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "deterministic"},
        },
    )

    with pytest.raises(RuntimeError, match="decision owner"):
        conversation_runtime.commit(
            lead_ref=7,
            context=_context(),
            decision=_decision(),
            response=AgentResponse(
                reply_text="modelo",
                role=ConversationRoute.SDR,
                cart_state={},
                proof={"valid": True},
            ),
            correlation_id="correlation-1",
            phone_number_id=None,
            channel_binding_id="binding-1",
            inbound_buffer_id="buffer-1",
            expected_decision_owner="n8n_agents",
        )


def _reachable_calls(function: ast.FunctionDef) -> set[str]:
    calls: set[str] = set()

    def visit_statements(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.If) and isinstance(statement.test, ast.Constant):
                visit_statements(statement.body if statement.test.value else statement.orelse)
            else:
                for node in ast.walk(statement):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            calls.add(node.func.id)
                        elif isinstance(node.func, ast.Attribute):
                            calls.add(node.func.attr)
            if isinstance(statement, (ast.Return, ast.Raise)):
                break

    visit_statements(function.body)
    return calls


def test_agentic_modules_have_no_reachable_deterministic_composition():
    services = Path(__file__).resolve().parents[1] / "services"
    agent_source = (services / "graph_agent_runtime_v3.py").read_text(encoding="utf-8")
    proof_source = (services / "graph_proof_checker_v3.py").read_text(encoding="utf-8")
    assert "deterministic_composer" not in agent_source
    assert "deterministic_composer" not in proof_source
    assert "_select_faq_candidate" not in agent_source
    assert "compose_published_question" not in proof_source
    assert "_terminal_reply" not in agent_source
    assert "_repetition_ladder" not in agent_source
    assert "missing_fields[0]" not in agent_source
    assert "published_fallback" not in agent_source

    tree = ast.parse(agent_source)
    guarded = {
        "_normalize_premature_servico_requestion",
        "_normalize_stale_next_question_after_branch_change",
        "_reconcile_direct_answer_to_pending_field",
        "_unanswered_fact_after_question_limit",
    }
    productive = {
        node.name: _reachable_calls(node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"decide", "_decide"}
    }
    assert productive.keys() == {"decide", "_decide"}
    assert not (set().union(*productive.values()) & guarded)
