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


def test_agentic_proof_discards_invalid_question_metadata_without_blocking_reply():
    contract = {
        "branch_path_checksum": "checksum:retail",
        "closure_node_ids": ["audience:retail", "q:need", "q:style"],
        "fields": [
            {
                "key": "retail_need",
                "owner_node_id": "audience:retail",
                "required": True,
                "question_node_id": "q:need",
                "accepted_statuses": ["known"],
            },
            {
                "key": "retail_style",
                "owner_node_id": "audience:retail",
                "required": True,
                "depends_on": ["retail_need"],
                "question_node_id": "q:style",
                "accepted_statuses": ["known", "unknown"],
            },
        ],
        "questions": {
            "q:need": {"field_key": "retail_need", "text": "O que procura?"},
            "q:style": {
                "field_key": "retail_style",
                "text": "Qual estilo prefere?",
                "depends_on": ["retail_need"],
            },
        },
    }
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active",
            "checksum": "graph-checksum",
            "document_json": {"branch_anchors": ["audience:retail"]},
        },
        contract=contract,
        ledger={"graph_checksum": "graph-checksum", "facts": {}},
        proposal={
            "reply": "Entendi, algo para o dia a dia. Qual estilo você prefere?",
            "branch_action": "keep",
            "branch_anchor_node_id": "audience:retail",
            "branch_path_checksum": "checksum:retail",
            "extracted_facts": [],
            "next_question_node_id": "q:style",
            "claims": [],
        },
        message="Estou procurando algo para usar no dia a dia",
        source_message_id="inbound:1",
        package_node_ids=set(),
        package_chunk_ids=set(),
        active_branch_node_id="audience:retail",
        active_branch_node_ids=["audience:retail"],
        branch_selection_allowed=False,
        branch_switch_allowed=False,
    )

    assert proof["valid"] is True
    assert proof["delivery_authorized"] is True
    assert proof["model_reply_preserved"] is True
    assert proof["next_question_node_id"] is None
    assert proof["missing_fields"] == ["retail_need", "retail_style"]
    assert proof["required_field_count"] == 2
    assert proof["metadata_errors"] == ["next_question_dependencies_unsatisfied"]
    assert proof["blocking_metadata_errors"] == []
    assert proof["discarded_structured_components"] == [
        "next_question_node_id:next_question_dependencies_unsatisfied"
    ]


@pytest.mark.parametrize("service", ["Vitrificação", "Higienização interna"])
def test_claim_evidence_disagreement_is_a_quality_warning(service):
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active", "checksum": "graph-checksum",
            "document_json": {"branch_anchors": ["service:active"]},
        },
        contract={
            "branch_path_checksum": "path-checksum",
            "closure_node_ids": ["service:active", "faq:service"],
            "fields": [], "questions": [],
            "claims": [{"claim_type": "service_detail", "evidence_node_ids": ["faq:service"]}],
        },
        ledger={"graph_checksum": "graph-checksum", "facts": {}},
        proposal={
            "reply": f"Posso explicar {service}.",
            "branch_action": "keep", "branch_anchor_node_id": "service:active",
            "branch_path_checksum": "path-checksum",
            "claims": [{"claim_type": "service_detail", "value": {"text": service},
                        "evidence_node_ids": ["service:active"], "evidence_chunk_ids": []}],
            "cited_node_ids": ["faq:service"],
        },
        message=f"Tenho interesse em {service}", source_message_id="inbound:1",
        package_node_ids={"service:active"}, package_chunk_ids=set(),
        active_branch_node_id="service:active", branch_selection_allowed=False,
        branch_switch_allowed=False,
    )
    assert proof["valid"] is True
    assert proof["delivery_authorized"] is True
    assert proof["repair_required"] is False
    assert proof["gating_errors"] == []
    assert "claim_evidence_not_authorized:service_detail" in proof["quality_warnings"]
    assert "cited_node_outside_package:faq:service" in proof["quality_warnings"]


def test_publication_checksum_gates_while_bare_confirmation_is_quality_warning():
    proof = graph_proof_checker_v3.check(
        publication={"status": "active", "checksum": "new", "document_json": {"branch_anchors": []}},
        contract={"closure_node_ids": [], "fields": [{"key": "profile", "owner_node_id": "persona"}]},
        ledger={"graph_checksum": "old", "facts": {}},
        proposal={"reply": "Está confirmado.", "branch_action": "none", "claims": []},
        message="Olá", source_message_id="inbound:1", package_node_ids=set(),
        package_chunk_ids=set(), active_branch_node_id=None,
        branch_selection_allowed=False, branch_switch_allowed=False,
    )
    assert proof["valid"] is False
    assert proof["gating_errors"] == ["publication_checksum_mismatch"]
    assert "premature_final_confirmation" in proof["quality_warnings"]

    matching = graph_proof_checker_v3.check(
        publication={"status": "active", "checksum": "old", "document_json": {"branch_anchors": []}},
        contract={"closure_node_ids": [], "fields": [{"key": "profile", "owner_node_id": "persona"}]},
        ledger={"graph_checksum": "old", "facts": {}},
        proposal={"reply": "Está confirmado.", "branch_action": "none", "claims": []},
        message="Olá", source_message_id="inbound:1", package_node_ids=set(),
        package_chunk_ids=set(), active_branch_node_id=None,
        branch_selection_allowed=False, branch_switch_allowed=False,
    )
    assert matching["valid"] is True
    assert matching["delivery_authorized"] is True
    assert "premature_final_confirmation" in matching["quality_warnings"]


def test_price_comparison_is_derived_from_published_offer_and_faq():
    document = {
        "branch_anchors": ["audience:retail"],
        "nodes": [
            {"id": "audience:retail", "node_type": "audience", "status": "validated", "data": {}},
            {"id": "group:tops", "node_type": "product_group", "status": "validated", "title": "Tops", "data": {}},
            {"id": "product:one", "node_type": "product", "status": "validated", "title": "Produto 1", "data": {}},
            {"id": "offer:one", "node_type": "offer", "status": "validated", "data": {"channel": "varejo", "status": "validated", "price": {"amount": 19.9, "currency": "BRL"}}},
            {"id": "faq:one-price", "node_type": "faq", "status": "approved", "data": {"claims": [{"claim_type": "price", "policy": "published", "evidence_node_ids": ["faq:one-price"]}], "sources": [{"node_id": "offer:one"}]}},
        ],
        "edges": [
            {"source": "group:tops", "target": "product:one", "relation_type": "contains"},
            {"source": "offer:one", "target": "product:one", "relation_type": "about_product"},
        ],
    }
    closure = {node["id"] for node in document["nodes"]}
    catalog = graph_proof_checker_v3.published_retail_price_catalog(document, closure)
    assert catalog == [{
        "product_node_id": "product:one", "product_title": "Produto 1",
        "product_group_node_id": "group:tops", "product_group_title": "Tops",
        "amount": 19.9, "currency": "BRL", "evidence_node_id": "faq:one-price",
    }]

    proof = graph_proof_checker_v3.check(
        publication={"status": "active", "checksum": "graph-checksum", "document_json": document},
        contract={
            "branch_path_checksum": "checksum:retail", "closure_node_ids": sorted(closure),
            "fields": [], "questions": [],
            "claims": [{"claim_type": "price", "policy": "published", "evidence_node_ids": ["faq:one-price"]}],
        },
        ledger={"graph_checksum": "graph-checksum", "facts": {}},
        proposal={
            "reply": "A opção de menor preço é o Produto 1, por R$ 19,90.",
            "branch_action": "keep", "branch_anchor_node_id": "audience:retail",
            "branch_path_checksum": "checksum:retail", "extracted_facts": [],
            "claims": [{
                "claim_type": "price_comparison",
                "value": {"items": [{"product_node_id": "product:one", "amount": 19.9, "currency": "BRL"}]},
                "evidence_node_ids": ["faq:one-price"], "evidence_chunk_ids": [],
            }],
        },
        message="qual é o mais barato?", source_message_id="inbound:price",
        package_node_ids={"faq:one-price"}, package_chunk_ids=set(),
        active_branch_node_id="audience:retail", active_branch_node_ids=["audience:retail"],
        branch_selection_allowed=False, branch_switch_allowed=False,
    )
    assert proof["valid"] is True


def test_price_comparison_rejects_a_model_invented_amount():
    document = {
        "branch_anchors": ["audience:retail"],
        "nodes": [
            {"id": "audience:retail", "node_type": "audience", "status": "validated", "data": {}},
            {"id": "product:one", "node_type": "product", "status": "validated", "title": "Produto 1", "data": {}},
            {"id": "offer:one", "node_type": "offer", "status": "validated", "data": {"channel": "varejo", "status": "validated", "price": {"amount": 19.9, "currency": "BRL"}}},
            {"id": "faq:one-price", "node_type": "faq", "status": "approved", "data": {"claims": [{"claim_type": "price", "policy": "published", "evidence_node_ids": ["faq:one-price"]}], "sources": [{"node_id": "offer:one"}]}},
        ],
        "edges": [{"source": "offer:one", "target": "product:one", "relation_type": "about_product"}],
    }
    closure = {node["id"] for node in document["nodes"]}
    proof = graph_proof_checker_v3.check(
        publication={"status": "active", "checksum": "graph-checksum", "document_json": document},
        contract={"branch_path_checksum": "checksum:retail", "closure_node_ids": sorted(closure), "fields": [], "questions": [], "claims": [{"claim_type": "price", "policy": "published", "evidence_node_ids": ["faq:one-price"]}]},
        ledger={"graph_checksum": "graph-checksum", "facts": {}},
        proposal={"reply": "Custa R$ 1,00.", "branch_action": "keep", "branch_anchor_node_id": "audience:retail", "branch_path_checksum": "checksum:retail", "extracted_facts": [], "claims": [{"claim_type": "price_comparison", "value": {"items": [{"product_node_id": "product:one", "amount": 1, "currency": "BRL"}]}, "evidence_node_ids": ["faq:one-price"], "evidence_chunk_ids": []}]},
        message="qual é o mais barato?", source_message_id="inbound:price",
        package_node_ids={"faq:one-price"}, package_chunk_ids=set(),
        active_branch_node_id="audience:retail", active_branch_node_ids=["audience:retail"],
        branch_selection_allowed=False, branch_switch_allowed=False,
    )
    assert "price_comparison_value_mismatch" in proof["errors"]


def test_public_information_claim_passes_with_exact_graph_evidence():
    document = {
        "branch_anchors": ["service:assessment"],
        "nodes": [
            {
                "id": "service:assessment",
                "node_type": "service",
                "status": "validated",
                "data": {},
            },
            {
                "id": "faq:assessment",
                "node_type": "faq",
                "status": "approved",
                "data": {
                    "claims": [{
                        "claim_type": "public_information",
                        "policy": {"mode": "informational"},
                        "evidence_node_ids": ["faq:assessment"],
                    }],
                },
            },
        ],
        "edges": [],
    }
    closure = {"service:assessment", "faq:assessment"}

    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active",
            "checksum": "graph-checksum",
            "document_json": document,
        },
        contract={
            "branch_path_checksum": "checksum:assessment",
            "closure_node_ids": sorted(closure),
            "fields": [],
            "questions": [],
            "claims": [{
                "claim_type": "public_information",
                "policy": {"mode": "informational"},
                "evidence_node_ids": ["faq:assessment"],
            }],
        },
        ledger={"graph_checksum": "graph-checksum", "facts": {}},
        proposal={
            "reply": "Conte o serviço e os dados do veículo para pedir a avaliação.",
            "branch_action": "keep",
            "branch_anchor_node_id": "service:assessment",
            "branch_path_checksum": "checksum:assessment",
            "extracted_facts": [],
            "claims": [{
                "claim_type": "public_information",
                "value": {"text": "Como pedir uma avaliação"},
                "evidence_node_ids": ["faq:assessment"],
                "evidence_chunk_ids": [],
            }],
        },
        message="Como pedir uma avaliação?",
        source_message_id="inbound:assessment",
        package_node_ids={"faq:assessment"},
        package_chunk_ids=set(),
        active_branch_node_id="service:assessment",
        active_branch_node_ids=["service:assessment"],
        branch_selection_allowed=False,
        branch_switch_allowed=False,
    )

    assert proof["valid"] is True


def test_runtime_rejects_question_for_a_fact_resolved_in_the_same_turn():
    rejected = graph_agent_runtime_v3._rejected_qualification_question_id(
        "q:purchase-profile", {"q:sales-readiness", "q:fulfillment"},
    )

    assert rejected == "q:purchase-profile"


def test_runtime_accepts_only_a_currently_askable_qualification_question():
    rejected = graph_agent_runtime_v3._rejected_qualification_question_id(
        "q:sales-readiness", {"q:sales-readiness", "q:fulfillment"},
    )

    assert rejected is None


def test_sdr_enters_temporary_consultative_support_before_handoff():
    assert graph_agent_runtime_v3._consultative_support_active(
        collection_complete=True,
        customer_questions=[{"kind": "price", "topic": "pedido"}],
        post_support=False,
    ) is True
    assert graph_agent_runtime_v3._consultative_support_active(
        collection_complete=False,
        customer_questions=[{"kind": "price", "topic": "pedido"}],
        post_support=False,
    ) is False
    assert graph_agent_runtime_v3._consultative_support_active(
        collection_complete=True,
        customer_questions=[],
        post_support=False,
    ) is False


def test_final_confirmation_requires_pending_same_branch_and_explicit_yes():
    ref = "qualification:service:assessment"
    context = _context().model_copy(update={
        "messages": [{"role": "user", "content": "Sim", "message_id": "in-2"}],
        "cart": {"sdr_state": "awaiting_confirmation", "pending_confirmation_ref": ref},
    })
    accepted = graph_agent_runtime_v3._qualification_confirmation_accepted
    args = {
        "confirmation": {"state": "affirm", "target_ref": ref},
        "confirmation_ref": ref,
        "qualification_complete": True,
        "active_branch_node_ids": ["service:assessment"],
        "customer_questions": [],
    }
    assert accepted(context, **args) is True
    assert accepted(context, **{**args, "confirmation_ref": "qualification:service:other"}) is False
    assert accepted(context, **{**args, "qualification_complete": False}) is False
    assert accepted(context, **{**args, "customer_questions": [{"kind": "price"}]}) is False
    assert accepted(context.model_copy(update={
        "messages": [{"role": "user", "content": "Sim, mas quero mudar", "message_id": "in-2"}],
    }), **args) is False
    assert accepted(context.model_copy(update={"cart": {}}), **args) is False


def test_optional_collect_once_field_is_askable_then_stops_without_blocking_completion():
    contract = {
        "branch_path_checksum": "checksum:retail",
        "closure_node_ids": ["audience:retail", "q:name"],
        "fields": [{
            "key": "nome_cliente",
            "owner_node_id": "persona:one",
            "required": False,
            "collection_mode": "ask_once_optional",
            "question_node_id": "q:name",
            "accepted_statuses": ["known"],
        }],
        "questions": {
            "q:name": {
                "field_key": "nome_cliente",
                "text": "Como voce prefere que eu te chame?",
            },
        },
    }

    first = graph_proof_checker_v3.askable_pending_fields(
        contract, {}, asked_question_node_ids=[],
    )
    after_ask = graph_proof_checker_v3.askable_pending_fields(
        contract, {}, asked_question_node_ids=["q:name"],
    )

    assert [field["key"] for field in first] == ["nome_cliente"]
    assert after_ask == []
    assert graph_proof_checker_v3.pending_fields(contract, {}) == []
    assert graph_proof_checker_v3.required_field_count(contract, {}) == 0


def test_agentic_proof_accepts_graph_authored_optional_collect_once_question():
    contract = {
        "branch_path_checksum": "checksum:retail",
        "closure_node_ids": ["audience:retail", "q:name"],
        "fields": [{
            "key": "nome_cliente",
            "owner_node_id": "persona:one",
            "required": False,
            "collection_mode": "ask_once_optional",
            "question_node_id": "q:name",
            "accepted_statuses": ["known"],
        }],
        "questions": {
            "q:name": {
                "field_key": "nome_cliente",
                "text": "Como voce prefere que eu te chame?",
            },
        },
    }
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active",
            "checksum": "graph-checksum",
            "document_json": {"branch_anchors": ["audience:retail"]},
        },
        contract=contract,
        ledger={
            "graph_checksum": "graph-checksum",
            "facts": {},
            "asked_question_node_ids": [],
        },
        proposal={
            "reply": "Como voce prefere que eu te chame?",
            "branch_action": "keep",
            "branch_anchor_node_id": "audience:retail",
            "branch_path_checksum": "checksum:retail",
            "extracted_facts": [],
            "next_question_node_id": "q:name",
            "claims": [],
        },
        message="Quero comprar para uso proprio.",
        source_message_id="inbound:1",
        package_node_ids=set(),
        package_chunk_ids=set(),
        active_branch_node_id="audience:retail",
        active_branch_node_ids=["audience:retail"],
        branch_selection_allowed=False,
        branch_switch_allowed=False,
    )

    assert proof["valid"] is True
    assert proof["metadata_errors"] == []
    assert proof["next_question_node_id"] == "q:name"
    assert proof["qualification_complete"] is True


def test_decision_request_rejects_legacy_single_pass_input():
    with pytest.raises(ValidationError):
        conversations.DecisionRequest.model_validate({
            "context": _context().model_dump(),
            "model_observation": {"proposal": {"reply": "modelo"}},
        })


def _legacy_test_decide_route_calls_only_agentic_entrypoint(monkeypatch):
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
    assert result["agent_role"] == body.context.agent_role
    assert result["execution_strategy"] == body.context.execution_strategy


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


def _function_def(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def test_decide_binds_every_name_it_reads():
    """`_decide` grew a committed-state branch that read `repetition_action`
    while nothing bound it -- a latent NameError that only surfaced once an
    agentic turn could progress past the service-operation proof gate. Guard
    the whole function against reintroducing an unbound local."""
    services = Path(__file__).resolve().parents[1] / "services"
    source = (services / "graph_agent_runtime_v3.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    module_names: set[str] = set()
    for node in module.body:  # module scope only -- never descend into defs
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        module_names.add(sub.id)

    import builtins

    func = _function_def(source, "_decide")
    bound = set(module_names) | set(dir(builtins))
    bound |= {arg.arg for arg in func.args.args + func.args.kwonlyargs}
    if func.args.vararg:
        bound.add(func.args.vararg.arg)
    if func.args.kwarg:
        bound.add(func.args.kwarg.arg)
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for arg in getattr(node.args, "args", []):
                bound.add(arg.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)

    read = {
        node.id
        for node in ast.walk(func)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert read <= bound, f"unbound names read in _decide: {sorted(read - bound)}"
