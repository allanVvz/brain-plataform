from __future__ import annotations

import json
from pathlib import Path

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


def test_two_step_contracts_are_strict_and_decision_keeps_single_pass_compatibility():
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

    context = _context(strategy="single_pass")
    assert DecisionRequest(context=context, model_observation={"proposal": {}})
    with pytest.raises(ValidationError):
        DecisionRequest(context=context)

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
                "sdr": "interpret_then_respond", "default": "single_pass",
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
    ] = "single_pass"
    closer_document = graph_compiler_v3.compile_graph(
        persona=persona, node_rows=[root, branch], edge_rows=[relation]
    )
    assert closer_document["agent_role"] == "closer"
    assert closer_document["execution_strategy"] == "single_pass"

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
    validator_code = nodes["Validate turn understanding"]["parameters"]["jsCode"]
    assert "turn_understanding_unknown_fact" in validator_code
    assert "turn_understanding_invalid_branch" in validator_code
    assert "const understanding={contract_version:\"turn_understanding_v1\"" in validator_code
    assert "conversation_brief" in reply_code
    assert "evidence_chunk_ids:{type:'array',items:{type:'string'}}}}}" in reply_code
    assert "It is fine to ask nothing" in reply_code
    assert "Set contract_version to conversation_reply_v1" in reply_code
    assert "exactly these top-level keys" in reply_code
    assert "claims and citations only for factual commercial statements" in reply_code
    assert "Each claim is exactly {claim_type, value, evidence_node_ids, evidence_chunk_ids}" in reply_code
    assert "Never copy policy, metadata, or any other field from retrieved context into a claim" in reply_code


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
