from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from routes.conversations import DecisionRequest, ResolveUnderstandingRequest
from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ConversationReplyV1,
    ResolvedUnderstandingV1,
    TurnUnderstandingV1,
)
from services import (
    conversation_runtime,
    graph_agent_runtime_v3,
    graph_bundle,
    graph_compiler_v3,
)


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "n8n" / "persona-conversation-template.json"


def _context(*, strategy: str = "interpret_then_respond") -> ConversationContext:
    return ConversationContext(
        persona_slug="generic",
        agent_slug="agent",
        agent_role="sdr",
        execution_strategy=strategy,
        graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"role": "user", "content": "quero para o dia a dia"}],
        cart={},
        rag_nodes=[],
        rag_paths=[],
        graph_contract={"fields": []},
        publication_id="publication-1",
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
    )


def _understanding() -> TurnUnderstandingV1:
    return TurnUnderstandingV1(
        facts=[],
        branch_selections=[],
        confirmation={"state": "none"},
        customer_questions=[],
    )


def test_two_step_contracts_are_strict_and_single_pass_is_rejected():
    with pytest.raises(ValidationError):
        TurnUnderstandingV1.model_validate({
            "contract_version": "turn_understanding_v1",
            "facts": [],
            "branch_selections": [],
            "confirmation": {"state": "none"},
            "customer_questions": [],
            "interaction_observation": {},
            "reply": "not allowed in understanding",
        })

    with pytest.raises(ValidationError):
        _context(strategy="single_pass")

    with pytest.raises(ValidationError):
        TurnUnderstandingV1(
            branch_selections=[
                {
                    "action": "select",
                    "branch_anchor_node_id": "audience:retail",
                    "evidence_span": "varejo",
                },
                {
                    "action": "add",
                    "branch_anchor_node_id": "audience:reseller",
                    "evidence_span": "atacado",
                },
            ]
        )


def test_resolve_request_uses_named_turn_understanding_contract():
    request = ResolveUnderstandingRequest(
        context=_context(), understanding=_understanding()
    )
    assert request.understanding.contract_version == "turn_understanding_v1"


def test_compiler_publishes_role_strategy_and_rejects_unknown_strategy():
    persona = {"id": "persona-id", "slug": "generic"}
    root = {
        "id": "root-id", "node_type": "persona", "slug": "generic",
        "title": "Generic", "summary": "Generic", "tags": [],
        "status": "validated", "metadata": {
            "graph_json_node_id": "persona:generic",
            "agent_role": "sdr",
            "conversation_policy": {"execution_strategy_by_role": {
                "sdr": "interpret_then_respond", "default": "interpret_then_respond",
            }},
        },
    }
    branch = {
        "id": "branch-id", "node_type": "audience", "slug": "retail",
        "title": "Retail", "summary": "Retail", "tags": [],
        "status": "validated", "metadata": {
            "graph_json_node_id": "audience:retail",
            "capabilities": {"branch_anchor": True},
        },
    }
    relation = {
        "id": "edge-id", "source_node_id": "root-id",
        "target_node_id": "branch-id", "relation_type": "contains",
        "weight": 1, "metadata": {"active": True, "graph_json_edge_id": "edge:1"},
    }
    document = graph_compiler_v3.compile_graph(
        persona=persona, node_rows=[root, branch], edge_rows=[relation]
    )
    assert document["agent_role"] == "sdr"
    assert document["execution_strategy"] == "interpret_then_respond"
    assert document["branch_contracts"]["audience:retail"]["execution_strategy"] == "interpret_then_respond"

    root["metadata"]["agent_role"] = "closer"
    root["metadata"]["conversation_policy"]["execution_strategy_by_role"][
        "closer"
    ] = "interpret_then_respond"
    closer_document = graph_compiler_v3.compile_graph(
        persona=persona, node_rows=[root, branch], edge_rows=[relation]
    )
    assert closer_document["agent_role"] == "closer"
    assert closer_document["execution_strategy"] == "interpret_then_respond"

    root["metadata"]["agent_role"] = "sdr"
    root["metadata"]["conversation_policy"]["execution_strategy_by_role"]["sdr"] = "unknown"
    with pytest.raises(graph_compiler_v3.GraphCompilationError, match="invalid_execution_strategy"):
        graph_compiler_v3.compile_graph(
            persona=persona, node_rows=[root, branch], edge_rows=[relation]
        )


def test_final_reply_reuses_resolved_facts_and_never_requests_repair(monkeypatch):
    original = _context()
    understanding = _understanding()
    resolved = ResolvedUnderstandingV1(
        understanding=understanding,
        context=original,
        prospective_state={"facts_by_key": {}},
        conversation_brief={
            "price_comparison_catalog": [{
                "product_node_id": "product:lowest",
                "amount": 29.9,
                "currency": "BRL",
                "evidence_node_id": "faq:lowest-retail-price",
            }],
        },
        resolution_proof={"valid": True, "accepted_facts": [{
            "field_key": "retail_need", "owner_node_id": "audience:retail",
            "status": "known", "value": "dia-a-dia",
            "source_message_id": "message-1", "evidence_span": "dia a dia",
            "confidence": 1.0, "metadata": {},
        }]},
    )
    reply = ConversationReplyV1(reply="Claro, posso te ajudar.")

    def fake_decide(context, *, model_observation):
        assert model_observation["repair_attempt"] == 0
        assert model_observation["execution_strategy"] == "interpret_then_respond"
        assert model_observation["proposal"]["extracted_facts"] == []
        assert model_observation["authorized_price_catalog"][0]["evidence_node_id"] == "faq:lowest-retail-price"
        return (
            ConversationDecision(
                intent="collect_graph_fields", route="SDR", confidence=1,
                lead_stage="engajado",
            ),
            AgentResponse(
                reply_text=reply.reply, role="SDR", cart_state={},
                proof={"valid": True, "delivery_authorized": True},
            ),
        )

    monkeypatch.setattr(graph_agent_runtime_v3, "decide", fake_decide)
    _decision, response = conversation_runtime.decide_agentic(
        original,
        resolved_understanding=resolved,
        conversation_reply=reply,
        model_observation={"token_usage": {"model_calls": 2}},
    )
    assert response.proof["accepted_facts"][0]["field_key"] == "retail_need"
    assert response.proof["semantic_repairs"] == 0
    assert response.proof["execution_strategy"] == "interpret_then_respond"


def test_final_proof_keeps_understanding_facts_branch_change_and_reply_question(monkeypatch):
    original = _context()
    understanding = TurnUnderstandingV1(
        validation_observations=["understanding_metadata_discarded:customer_question"],
    )

    fact = {
        "field_key": "vehicle", "owner_node_id": "branch:new", "status": "known",
        "value": "Ford Ka", "source_message_id": "m1", "evidence_span": "Ford Ka",
    }
    carried = {
        "field_key": "name", "owner_node_id": "persona:generic", "status": "known",
        "value": "Ana Souza", "source_message_id": "m0",
        "metadata": {"reuse_policy": "carry_over"},
    }
    resolved = ResolvedUnderstandingV1(
        understanding=understanding, context=original,
        prospective_state={}, conversation_brief={},
        eligible_fields=[{"key": "year", "question_node_id": "q:year"}],
        resolution_proof={
            "accepted_facts": [fact],
            "applied_service_operations": [{"action": "add", "branch_anchor_node_id": "branch:new"}],
            "service_resolution": {"focused_branch_node_id": "branch:new"},
        },
    )
    reply = ConversationReplyV1(reply="E o ano do carro?", asked_field_key="year")

    def fake_decide(_context, *, model_observation):
        assert model_observation["proposal"]["next_question_node_id"] == "q:year"
        return (
            ConversationDecision(
                intent="collect_graph_fields", route="SDR", confidence=1,
                lead_stage="engajado",
            ),
            AgentResponse(
                reply_text=reply.reply, role="SDR", cart_state={
                    "active_branch_node_id": "branch:new", "asked_question_node_ids": ["q:year"],
                },
                proof={
                    "valid": True, "delivery_authorized": True,
                    "accepted_facts": [carried], "asked_field_key": "year",
                    "next_question_node_id": "q:year", "quality_pass": True,
                },
            ),
        )

    monkeypatch.setattr(graph_agent_runtime_v3, "decide", fake_decide)
    _decision, response = conversation_runtime.decide_agentic(
        original, resolved_understanding=resolved, conversation_reply=reply,
    )
    assert {item["field_key"] for item in response.proof["accepted_facts"]} == {
        "vehicle", "name",
    }
    assert response.proof["applied_service_operations"][0]["branch_anchor_node_id"] == "branch:new"
    assert response.proof["asked_field_key"] == "year"
    assert response.proof["next_question_node_id"] == "q:year"
    assert response.proof["quality_pass"] is False
    assert response.proof["quality_warnings"] == [
        "understanding_metadata_discarded:customer_question"
    ]


def test_two_step_proof_failure_preserves_sanitized_reason(monkeypatch):
    original = _context()
    resolved = ResolvedUnderstandingV1(
        understanding=_understanding(),
        context=original,
        prospective_state={"facts_by_key": {}},
        resolution_proof={"valid": True, "accepted_facts": []},
    )

    monkeypatch.setattr(
        graph_agent_runtime_v3,
        "decide",
        lambda _context, *, model_observation: (
            ConversationDecision(
                intent="answer_question", route="SDR", confidence=1,
                lead_stage="engajado",
            ),
            AgentResponse(
                reply_text="Ainda preciso confirmar.", role="SDR", cart_state={},
                proof={
                    "valid": False,
                    "delivery_authorized": False,
                    "errors": ["claim_without_evidence:stock"],
                },
            ),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="conversation reply proof failed:claim_without_evidence:stock",
    ):
        conversation_runtime.decide_agentic(
            original,
            resolved_understanding=resolved,
            conversation_reply=ConversationReplyV1(reply="Ainda preciso confirmar."),
            model_observation={"token_usage": {"model_calls": 2}},
        )


def test_missing_model_call_telemetry_is_diagnostic_not_a_delivery_gate():
    telemetry = conversation_runtime.build_turn_telemetry(
        turn_id="preview-1",
        token_usage={},
        response_generated=True,
        delivery_allowed=True,
    )

    assert telemetry == {
        "turn_id": "preview-1",
        "model_calls": 0,
        "response_generated": True,
        "delivery_allowed": True,
        "telemetry_missing": True,
    }


def test_template_routes_sdr_two_step_without_semantic_repair_and_fails_safe():
    workflow = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    connections = workflow["connections"]
    true_path = connections["Interpret then respond strategy"]["main"][0][0]["node"]
    false_path = connections["Interpret then respond strategy"]["main"][1][0]["node"]
    assert true_path == "Build turn understanding request"
    assert false_path == "Model required for turn"
    assert connections["Prove resolved conversation reply"]["main"][0][0]["node"] == "Align reply with qualification state"
    assert connections["Prove resolved conversation reply"]["main"][1][0]["node"] == "Normalize two-step failure"
    normalizer = next(node for node in workflow["nodes"] if node["name"] == "Normalize two-step failure")
    normalizer_code = normalizer["parameters"]["jsCode"]
    assert "technical_conversation_failure_v1" in normalizer_code
    assert "typeof raw==='string'" in normalizer_code
    assert connections["Normalize two-step failure"]["main"][0][0]["node"] == "Fail-safe two-step handoff"
    fail_safe = next(node for node in workflow["nodes"] if node["name"] == "Fail-safe two-step handoff")
    assert "/internal/v1/conversations/technical-failure" in fail_safe["parameters"]["url"]
    fail_safe_body = fail_safe["parameters"]["body"]
    assert fail_safe_body == "={{JSON.stringify($json.failure)}}"
    assert "??" not in fail_safe_body
    assert "(()=>" not in fail_safe_body
    two_step_names = {
        "Build turn understanding request", "Bound understanding model",
        "Validate turn understanding", "Resolve understanding and scoped RAG",
        "Build natural conversation reply request", "Bound conversation reply model",
        "Validate natural conversation reply", "Prove resolved conversation reply",
    }
    for name in two_step_names:
        assert connections[name]["main"][1][0]["node"] == "Normalize two-step failure"
    reachable = set()
    pending = [true_path]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for outputs in (connections.get(name) or {}).values():
            for branch in outputs:
                pending.extend(edge["node"] for edge in branch)
    assert "Bound model graph repair" not in reachable
    assert len(connections["Fail-safe two-step handoff"]["main"]) == 2
    assert all(
        branch[0]["node"] == "Return canonical result"
        for branch in connections["Fail-safe two-step handoff"]["main"]
    )


def test_two_step_model_requests_use_provider_compatible_structured_output():
    workflow = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    for name in (
        "Build turn understanding request",
        "Build natural conversation reply request",
    ):
        code = nodes[name]["parameters"]["jsCode"]
        assert "structured_output_mode" in code
        assert "includes('deepseek')" not in code
        assert "json_object" in code and "json_schema" in code
        assert "thinking:{type:'disabled'}" in code
    reply_code = nodes["Build natural conversation reply request"]["parameters"]["jsCode"]
    understanding_code = nodes["Build turn understanding request"]["parameters"]["jsCode"]
    assert "Read the inbound and return only one JSON object" in understanding_code
    assert "field_key, owner_node_id, source_message_id or metadata" in understanding_code
    assert (
        "pending_confirmation_ref:context.pending_confirmation_ref"
        in understanding_code
    )
    assert "a bare yes or no answers that confirmation" in understanding_code
    assert "confirmation.target_ref exactly to pending_confirmation_ref" in understanding_code
    assert "expected_answer_field_key:expectedAnswerFieldKey" in understanding_code
    assert "customer_message answers it, facts must include that exact key" in understanding_code
    assert "each customer question is {kind,topic,entity_node_ids,evidence_span}" in understanding_code
    assert "A literal question from customer_message must appear in customer_questions" in understanding_code
    assert "output_schema:binding.structured_output_mode==='json_object'?schema:null" in understanding_code
    assert "Follow payload.output_schema exactly when it is present" in understanding_code
    assert "Do not use legacy keys such as detected_intent" in understanding_code
    validator_code = nodes["Validate turn understanding"]["parameters"]["jsCode"]
    assert "turn_understanding_unknown_fact" in validator_code
    assert "turn_understanding_invalid_branch" in validator_code
    assert "const understanding={contract_version:'turn_understanding_v1'" in validator_code
    assert "turn_understanding_invalid_observation_shape" in validator_code
    # n8n's Code node passes (value, index, array) to map callbacks. Passing
    # the sandboxed String callable directly raised the index ("0 [line 25]")
    # whenever the model returned a customer question with entity references.
    assert ".map(String)" not in validator_code
    assert ".map(function(value){return String(value);})" in validator_code
    assert "conversation_brief" in reply_code
    assert "evidence_chunk_ids:{type:'array',items:{type:'string'}}}}}" in reply_code
    assert "It is fine to ask nothing" in reply_code
    assert "operational_mode is post_qualification_support" in reply_code
    assert "do not promise, announce, or imply a transfer" in reply_code
    assert "Set contract_version to conversation_reply_v1" in reply_code
    assert "exactly these top-level keys" in reply_code
    assert "claims and citations only for factual commercial statements" in reply_code
    assert "cannot be guaranteed, or still needs confirmation is not a commercial claim" in reply_code
    assert "Each claim is exactly {claim_type, value, evidence_node_ids, evidence_chunk_ids}" in reply_code
    assert "value is always an object, never text, number, list, or null" in reply_code
    assert "use an object with a text property containing the factual statement" in reply_code
    assert "Never copy policy, metadata, or any other field from retrieved context into a claim" in reply_code
    reply_validator = nodes["Validate natural conversation reply"]["parameters"]["jsCode"]
    assert "conversation_reply_extra_claim" in reply_validator
    assert "conversation_reply_invalid_claim_value" in reply_validator
    assert "conversation_reply_invalid_citations" in reply_validator


def test_turn_understanding_validator_handles_question_entity_references():
    if not shutil.which("node"):
        pytest.skip("node is required to execute the canonical n8n code node")
    workflow = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    code = next(
        node["parameters"]["jsCode"]
        for node in workflow["nodes"]
        if node["name"] == "Validate turn understanding"
    )
    understanding = {
        "contract_version": "turn_understanding_v1",
        "facts": [],
        "branch_selections": [],
        "confirmation": {"state": "none"},
        "customer_questions": [{
            "kind": "stock",
            "topic": "estoque para a proxima semana",
            "entity_node_ids": ["product:daily"],
            "evidence_span": "garantir estoque para a proxima semana",
        }],
        "interaction_observation": {
            "kind": "continue_current", "evidence_span": "", "confidence": 1,
        },
    }
    harness = r"""
const fs = require('fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  'Load published graph context': {graph_contract: {fields: []}},
  'Validate conversation binding': {model: 'fixture-model', external_message_id: 'message-1'},
  'Build turn understanding request': {llm_call_started_at: Date.now()},
};
const select = (name) => ({item: {json: nodes[name]}});
const payload = {choices: [{message: {content: JSON.stringify(fixture.understanding)}}]};
const strictString = function(value) {
  if (arguments.length !== 1) throw new Error(globalThis.String(arguments[1]));
  return globalThis.String(value);
};
const result = new Function('$', '$json', 'String', fixture.javascript)(select, payload, strictString);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({"javascript": code, "understanding": understanding}),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["understanding"]["customer_questions"][0]["entity_node_ids"] == [
        "product:daily"
    ]


def test_tock_understanding_persists_retail_need_before_reply_and_refocuses_rag(monkeypatch):
    bundle_path = (
        ROOT.parent.parent / "data" / "graph_bundles" / "tock-fatal"
        / "graph-first-consultative-handoff-v36.json"
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    document = graph_bundle.compile_bundle(graph_bundle.normalize_bundle(bundle))
    publication = {
        "id": "publication-v36", "version": 36,
        "checksum": document["checksum"], "status": "active",
        "document_json": document,
    }
    retail = "audience:tock-retail"
    contract = document["branch_contracts"][retail]
    retail_need = next(field for field in contract["fields"] if field["key"] == "retail_need")
    context = ConversationContext(
        persona_slug="tock-fatal", agent_slug="vitoria", agent_role="sdr",
        execution_strategy="interpret_then_respond", graph_version=36,
        graph_checksum=document["checksum"],
        messages=[{
            "role": "user", "content": "Quero algo para usar no dia a dia",
            "message_id": "message-1",
        }],
        cart={"facts": {}, "facts_by_key": {}, "asked_question_node_ids": []},
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        publication_id=publication["id"],
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
        retrieval_trace={"branch_candidates": [], "possible_switches": []},
        available_services=[{
            "branch_anchor_node_id": anchor,
            "slug": document["node_by_id"][anchor]["slug"],
            "label": document["node_by_id"][anchor]["title"],
        } for anchor in document["branch_anchors"]],
    )
    understanding = TurnUnderstandingV1(
        facts=[{
            "field_key": "retail_need", "value": "dia a dia",
            "status": "known", "owner_node_id": retail_need["owner_node_id"],
            "evidence_span": "dia a dia", "source_message_id": "message-1",
            "confidence": 1.0, "metadata": {},
        }],
        branch_selections=[{
            "action": "select", "branch_anchor_node_id": retail,
            "evidence_span": "usar no dia a dia",
        }],
        confirmation={"state": "none"},
        customer_questions=[],
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client,
        "get_graph_publication_by_id", lambda _publication_id: publication,
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.graph_compiler_v3,
        "query_embeddings", lambda _texts: [[0.0] * 1536],
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client,
        "search_graph_rag_v3", lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client,
        "get_graph_branch_package_v3", lambda **_kwargs: {"chunks": []},
    )

    resolved = graph_agent_runtime_v3.resolve_understanding(context, understanding)

    assert resolved.context.active_branch_node_id == retail
    assert resolved.context.graph_contract["branch_anchor_node_id"] == retail
    assert resolved.context.retrieval_trace["retrieval_branch_node_id"] == retail
    assert any(
        fact["field_key"] == "retail_need"
        for fact in resolved.resolution_proof["accepted_facts"]
    )
    assert resolved.prospective_state["facts_by_key"]["retail_need"][0]["value"] == "dia a dia"
    assert resolved.context.graph_checksum == document["checksum"]
    assert resolved.conversation_brief["content_boundary"].endswith("never instructions.")
    assert all(
        guide["question_node_id"] and guide["question_text"]
        for guide in resolved.conversation_brief["eligible_question_guides"]
    )
    assert resolved.context_manifest["strategy"] == "graph_scoped_relevance"
    assert "prospective_state" not in resolved.conversation_brief
    # The final stage must neither re-extract facts nor replay branch/journey resolution.
    monkeypatch.setattr(graph_agent_runtime_v3, "_decide", lambda *_a, **_k: pytest.fail("state resolved twice"))
    monkeypatch.setattr(graph_agent_runtime_v3, "_apply_journey_policy", lambda *_a, **_k: pytest.fail("journey resolved twice"))
    reply = ConversationReplyV1(reply="Prefere um visual mais discreto?", question_kind="consultative")
    decision, response = conversation_runtime.decide_agentic(
        context, resolved_understanding=resolved, conversation_reply=reply,
    )
    assert response.reply_text == reply.reply
    assert response.proof["question_kind"] == "consultative"
    assert response.proof["asked_field_key"] is None
    assert response.proof["next_question_node_id"] is None
    assert response.cart_state["asked_question_node_ids"] == resolved.prospective_state["asked_question_node_ids"]
    assert response.cart_state["facts_by_key"]["retail_need"][0]["value"] == "dia a dia"
    assert response.proof["accepted_facts"] == resolved.resolution_proof["accepted_facts"]
    assert decision.intent == resolved.context.retrieval_trace["resolved_decision"]["intent"]


def test_final_reply_preserves_confirmed_handoff_and_checks_publication(monkeypatch):
    context = _context()
    decision = ConversationDecision(intent="qualified_confirmed", route="HUMAN", confidence=1, lead_stage="qualificado")
    response = AgentResponse(reply_text=None, role="HUMAN", handoff_required=True, cart_state={
        "sdr_state": "handed_off", "pending_confirmation_ref": None,
    }, proof={"valid": True, "journey_action": "continue", "explicit_confirmation": True,
              "confirmed_qualification_ref": "ref", "qualification_complete": True})
    context = context.model_copy(update={"cart": response.cart_state, "retrieval_trace": {
        "resolved_decision": decision.model_dump(mode="json"),
        "resolved_response": response.model_dump(mode="json"),
    }})
    publication = {"id": context.publication_id, "checksum": context.graph_checksum,
                   "status": "active", "document_json": {}}
    monkeypatch.setattr(graph_agent_runtime_v3, "_turn_publication", lambda _context: publication)
    monkeypatch.setattr(graph_agent_runtime_v3, "_decide", lambda *_a, **_k: pytest.fail("second resolution"))
    observation = {"proposal": {"reply": "Vou encaminhar seu pedido para a equipe."},
                   "interpretation": {"question_kind": "none", "asked_field_key": None}}
    final_decision, final_response = graph_agent_runtime_v3.decide(context, model_observation=observation)
    assert final_decision.route == decision.route
    assert final_response.handoff_required is True
    assert final_response.proof["explicit_confirmation"] is True
    assert final_response.proof["confirmed_qualification_ref"] == "ref"
    assert final_response.proof["journey_action"] == "continue"
    assert final_response.cart_state["pending_confirmation_ref"] is None
    assert final_response.proof["question_kind"] == "none"
    publication["checksum"] = "changed"
    with pytest.raises(RuntimeError, match="publication changed"):
        graph_agent_runtime_v3.decide(context, model_observation=observation)
