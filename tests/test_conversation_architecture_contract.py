from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/111_proof_gated_outbox_and_burst_claim.sql").read_text(encoding="utf-8")
WORKFLOW = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))


def _node(name: str) -> dict:
    return next(node for node in WORKFLOW["nodes"] if node["name"] == name)


def _run_prompt_builder(context: dict, binding: dict) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is required to execute the canonical n8n code node")
    javascript = _node("Build graph grounded agent request")["parameters"]["jsCode"]
    harness = """
const fs = require('fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  'Load published graph context': fixture.context,
  'Resolve conversation policy': {decision: {route: 'SDR', intent: 'commercial'}},
  'Validate conversation binding': fixture.binding,
};
const select = (name) => ({item: {json: nodes[name]}});
const result = new Function('$', fixture.javascript)(select);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({"context": context, "binding": binding, "javascript": javascript}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _run_response_validator(
    node_name: str, model_payload: dict, *, accepted_facts: list[dict] | None = None,
    first_interpretation: dict | None = None,
) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is required to execute the canonical n8n code node")
    javascript = _node(node_name)["parameters"]["jsCode"]
    harness = """
const fs = require('fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  'Build graph grounded agent request': {llm_call_started_at: Date.now(), prompt_estimated_tokens: 1},
  'Build graph repair request': {llm_call_started_at: Date.now(), prompt_estimated_tokens: 1, repair_context_node_ids: [], repair_context_chunk_ids: [], repair_context_chunk_sources: {}},
  'Validate agent response': {model_observation: {token_usage: null, interpretation: fixture.firstInterpretation || {}}},
  'Validate conversation binding': {model: 'fixture-model'},
  'Reconcile fields with graph policy': {response: {proof: {accepted_facts: fixture.acceptedFacts || []}}},
};
const select = (name) => ({item: {json: nodes[name]}});
const result = new Function('$', '$json', fixture.javascript)(select, fixture.modelPayload);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({
            "javascript": javascript,
            "modelPayload": model_payload,
            "acceptedFacts": accepted_facts or [],
            "firstInterpretation": first_interpretation or {},
        }),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _prompt_fixture(*, large: bool, message: str) -> tuple[dict, dict]:
    policy = {"instructions": "politica-publicada " * (460 if large else 2)}
    fields = [
        {"key": "customer_name", "owner_node_id": "persona", "required": True},
        {"key": "service", "owner_node_id": "service", "required": True},
    ]
    questions = {
        "q-name": {"field_key": "customer_name", "text": "Como posso te chamar?"},
        "q-service": {"field_key": "service", "text": "Qual servico voce procura?"},
    }
    claims = [{
        "claim_type": "service_detail",
        "value": {"text": "evidencia-aprovada " * (180 if large else 1)},
        "evidence_node_ids": ["faq-polimento"],
    }]
    common_contract = {
        "fields": fields,
        "questions": questions,
        "claims": claims,
        "conversation_policy": policy,
    }
    graph_contract = {
        **common_contract,
        "branch_anchor_node_id": "service-polimento",
        "closure_node_ids": ["persona", "service-polimento", "faq-polimento"],
        "mandatory_contract_evidence": "contrato-obrigatorio " * (300 if large else 1),
    }
    optional = "memoria-opcional " * (150 if large else 1)
    context = {
        "system_prompt": "sistema-publicado " * (900 if large else 2),
        "publication_id": "publication-aurora" if large else "publication-tock",
        "graph_version": 66 if large else 6,
        "graph_checksum": "sha256:fixture",
        "graph_contract": graph_contract,
        "context_cards": [{
            "id": "faq-polimento", "node_type": "faq", "title": "Polimento de vidros",
            "content_checksum": "sha256:card", "source": "published_graph", "status": "validated",
        }],
        "rag_chunks": [{
            "chunk_id": "chunk-polimento", "source_node_id": "faq-polimento",
            "chunk_kind": "faq", "chunk_text": "chunk-obrigatorio " * (1500 if large else 3),
            "chunk_checksum": "sha256:chunk", "path_checksum": "sha256:path",
            "metadata": {"provenance": {"source": "published_graph"}},
        }],
        "shared_memory": {
            "profile_facts": [{"key": "customer_name", "value": "Luiza"}],
            "current_journey": {"id": "journey-current", "state": "collecting"},
            "pending_items": [{"field_key": "service"}],
            "agent_activity": [{"text": optional}],
            "journey_outcomes": [{"text": optional}],
            "recent_messages": [{"text": optional}],
            "historical_facts": [{"text": optional}],
            "policy_version": 1,
        },
        "messages": [{"role": "user", "content": message}],
        "cart": {
            "facts_by_key": {"customer_name": [{"value": "Luiza"}]},
            "asked_question_node_ids": [],
        },
        "retrieval_trace": {
            "common_contract": common_contract,
            "branch_candidates": [{"branch_anchor_node_id": "service-polimento", "score": 0.99}],
            "service_resolution": {"status": "resolved", "consumed_spans": ["polimento de vidros"]},
            "confirmation_templates": {"fact": "Confirma {candidate}?"},
        },
        "available_services": [{"branch_anchor_node_id": "service-polimento", "label": "Polimento"}],
        "active_branch_node_id": "service-polimento",
        "active_branch_node_ids": ["service-polimento"],
        "journey_id": "journey-current",
        "journey_sequence": 1,
        "journey_state": "collecting",
        "pending_field_key": "service",
        "pending_question_node_id": "q-service",
        "agent_slug": "sdr",
        "operational_mode": "collection",
    }
    binding = {"model": "fixture-model", "message": message, "external_message_id": "wamid-audio-1"}
    return context, binding


def test_fact_revision_is_global_but_current_fact_scope_keeps_owner():
    assert "WHERE ledger_id = v_ledger.id AND field_key = v_fact->>'field_key';" in SQL
    assert "AND owner_node_id = v_fact->>'owner_node_id'" in SQL


def test_v3_commit_has_one_database_transaction_boundary():
    body = SQL.split("CREATE OR REPLACE FUNCTION public.commit_graph_turn_and_outbox_v3", 1)[1]
    assert "enqueue_whatsapp_envelope" in body
    assert "commit_graph_turn_v3" in body
    assert "finalize_proven_conversation_turn" in body
    assert "complete_conversation_commit" in body
    assert "v3 outbound must be created awaiting_proof" in body
    assert "refuses a preexisting outbound envelope" in body
    assert "v3 outbound requires a valid proof result" in body


def test_worker_claim_never_selects_awaiting_proof_and_serializes_batch():
    assert "b.status <> 'awaiting_proof'" in SQL
    assert "active.batch_key = b.batch_key AND active.status = 'processing'" in SQL
    assert "interval '4 seconds'" in SQL
    assert "'coalesced', true" in SQL
    assert "proof.proof_result->>'valid'" in SQL
    assert "created_at-previous_created_at>interval '4 seconds'" in SQL


def test_model_prompt_is_compact_and_budgeted_before_both_calls():
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]
    repair = _node("Build graph repair request")["parameters"]["jsCode"]
    assert "rendered_content" not in initial
    assert "prompt_budget_exceeded" in initial and "24000" in initial
    assert "prompt_budget_exceeded:repair" in repair and "24000" in repair
    assert "Math.ceil(text.length / 4)" in initial
    assert "Math.ceil(text.length / 4)" in repair
    assert "TextEncoder" not in initial and "TextEncoder" not in repair
    assert "recent_messages" in initial
    assert "agent_behavior: context.system_prompt" not in initial
    assert "graph_and_cards: { graph_contract:" not in initial
    assert (
        "graph_and_cards: 'top_level_graph_contract_approved_nodes_approved_chunks', "
        "memory: boundedMemory"
    ) not in initial
    assert "const usefulMemory" in initial
    assert "approved_nodes: approvedNodes" in initial
    assert "approved_chunks: approvedChunks" in initial
    assert "conversation_policy:" in initial
    assert "const promptGraphContract" in initial
    assert "graph_contract: promptGraphContract" in initial
    assert "graph_contract: context.graph_contract" not in initial
    assert "commonContractPrompt" not in initial
    assert "service_catalog:" not in initial
    assert "agent_activity" not in initial
    assert "journey_outcomes" not in initial
    assert "historical_facts" not in initial
    assert "promptEstimatedTokens > 22000" in initial
    assert "messages: [...original.messages" not in repair
    assert "const originalPrompt = JSON.parse(original.messages[1].content" in repair
    assert "Correct only the invalid component" in repair
    assert "temperature: 0" in repair
    assert "preserved_response" in repair
    assert "approved_faq" not in repair


def test_aurora_sized_audio_prompt_stays_below_preventive_budget_without_losing_evidence():
    message = "[audio do cliente]: Eu queria saber como funciona o polimento de vidros."
    context, binding = _prompt_fixture(large=True, message=message)

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    assert result["prompt_estimated_tokens"] <= 22_000
    assert prompt["customer_message"] == message
    assert prompt["source_message_id"] == "wamid-audio-1"
    assert [field["key"] for field in prompt["graph_contract"]["fields"]] == [
        "customer_name", "service",
    ]
    assert all("already_asked" in field for field in prompt["graph_contract"]["fields"])
    assert "questions" not in prompt["graph_contract"]
    assert "claims" not in prompt["graph_contract"]
    assert "closure_node_ids" not in prompt["graph_contract"]
    assert "mandatory_contract_evidence" not in prompt["graph_contract"]
    assert prompt["conversation_policy"] == context["graph_contract"]["conversation_policy"]
    assert prompt["approved_nodes"][0]["node_id"] == "faq-polimento"
    assert prompt["approved_chunks"][0]["text"] == context["rag_chunks"][0]["chunk_text"]
    assert prompt["facts_by_key"] == context["cart"]["facts_by_key"]
    assert prompt["memory"]["profile_facts"] == context["shared_memory"]["profile_facts"]
    assert prompt["memory"]["current_journey"] == context["shared_memory"]["current_journey"]
    assert prompt["memory"]["pending_items"] == context["shared_memory"]["pending_items"]
    assert "common_contract" not in prompt
    assert "prompt_layers" not in prompt


def test_tock_sized_audio_prompt_preserves_current_behavior_and_full_transcription():
    message = "[audio do cliente]: Quero comprar no varejo."
    context, binding = _prompt_fixture(large=False, message=message)

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])

    assert result["prompt_estimated_tokens"] < 22_000
    assert prompt["customer_message"] == message
    assert prompt["memory"]["recent_messages"] == context["shared_memory"]["recent_messages"]
    assert set(prompt["memory"]) == {
        "profile_facts", "current_journey", "pending_items", "recent_messages",
        "last_handoff", "product_interests", "asked_topics",
    }


def test_prompt_exposes_spent_questions_as_semantic_topics_without_question_ids():
    context, binding = _prompt_fixture(
        large=False, message="Qual e o preco e o pedido minimo?",
    )
    context["cart"]["asked_question_node_ids"] = ["q-service"]

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])

    assert prompt["memory"]["asked_topics"] == ["service"]
    service = next(
        field for field in prompt["graph_contract"]["fields"]
        if field["key"] == "service"
    )
    assert service["already_asked"] is True
    assert "q-service" not in result["request_body"]["messages"][1]["content"]


def test_large_published_graph_is_projected_to_a_conversational_contract():
    message = "ooii"
    context, binding = _prompt_fixture(large=False, message=message)
    context["graph_contract"].update({
        "claims": [
            {
                "claim_type": "commercial_fact",
                "value": {"description": f"published claim {index}"},
                "evidence_node_ids": [f"faq:{index}"],
            }
            for index in range(293)
        ],
        "closure_node_ids": [f"node:{index}" for index in range(542)],
        "eligible_faq_node_ids": [f"faq:{index}" for index in range(299)],
    })

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])

    assert result["prompt_estimated_tokens"] < 22_000
    assert prompt["customer_message"] == message
    assert prompt["approved_chunks"][0]["text"] == context["rag_chunks"][0]["chunk_text"]
    assert [field["key"] for field in prompt["graph_contract"]["fields"]] == [
        field["key"] for field in context["graph_contract"]["fields"]
    ]
    assert "claims" not in prompt["graph_contract"]
    assert "closure_node_ids" not in prompt["graph_contract"]
    assert "eligible_faq_node_ids" not in prompt["graph_contract"]


def test_model_prompt_receives_complete_multi_service_memory_contract():
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]
    initial_validator = _node("Validate agent response")["parameters"]["jsCode"]
    repair_validator = _node("Validate repaired agent response")["parameters"]["jsCode"]
    # branch_action + service_operations (multi-op array, actions
    # ['add','keep','drop']) were folded into the single semantic
    # branch_selection object; its action enum is the superset of both
    # (service_operations contributed 'drop', branch_action the rest).
    assert "['none','keep','select','switch','add','drop']" in initial
    assert "required: ['action','branch_anchor_node_id','evidence_span']" in initial
    assert "active_branch_node_ids: context.active_branch_node_ids" in initial
    assert "facts_by_key: context.cart && context.cart.facts_by_key" in initial
    assert "known_facts: context.known_facts" not in initial
    assert "memory: usefulMemory" in initial
    for field in (
        "identity: { agent_slug: context.agent_slug",
            "publication: { version: context.graph_version",
        "customer_message: binding.message",
        "branch_candidates: context.retrieval_trace",
        "graph_contract: promptGraphContract",
        "approved_nodes: approvedNodes",
        "approved_chunks: approvedChunks",
        "pending_confirmation_ref: context.pending_confirmation_ref",
    ):
        assert field in initial


def test_model_contract_uses_semantic_question_metadata_and_separates_audience_from_product():
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]
    validators = [
        _node("Validate agent response")["parameters"]["jsCode"],
        _node("Validate repaired agent response")["parameters"]["jsCode"],
    ]

    # The model authors both text segments and selects only a semantic field
    # key. Graph ids remain an internal proof/ledger concern.
    assert "question_field_key" in initial
    assert "never a graph question id" in initial
    assert "next_question_node_id" not in initial
    assert "questions: Object.fromEntries" not in initial
    for validator in validators:
        assert "responseSource.question_field_key" in validator
        assert "next_question_node_id: null" in validator

    # Audience/channel nodes are context; product/group interest is a
    # separate unresolved field. Keep this distinction portable instead of
    # adding persona literals to runtime code.
    assert "Never repeat a known or already_asked topic" in initial
    assert "Audience is purchase context, never a product" in initial


@pytest.mark.parametrize(
    "node_name", ["Validate agent response", "Validate repaired agent response"]
)
def test_n8n_validators_forward_separate_model_answer_and_semantic_question(node_name):
    interpretation = {
        "intents": [],
        "state_relation": "continue",
        "answers_field_key": None,
        "confirmation": {
            "state": "none", "target_ref": None, "evidence_span": "",
            "correction_field_key": None, "correction_value": None,
        },
        "branch_selections": [],
        "facts": [],
        "invalidated_facts": [],
        "entities": [],
        "questions": [],
        "claims": [],
        "recommended_next_action": "ask_field",
        "cited_node_ids": [],
        "cited_chunk_ids": [],
        "response": {
            "answer": "O pedido minimo varia conforme o produto.",
            "question": "Qual grupo de produtos voce quer conhecer?",
            "question_field_key": "product_interest",
        },
        "handoff_requested": False,
    }
    result = _run_response_validator(node_name, {
        "choices": [{"message": {"content": json.dumps(interpretation)}}],
    })

    parsed = result["model_observation"]["interpretation"]
    assert parsed["next_question_node_id"] is None
    assert parsed["next_question_field_key"] == "product_interest"
    assert parsed["response"] == interpretation["response"]
    assert parsed["reply"] == (
        "O pedido minimo varia conforme o produto. "
        "Qual grupo de produtos voce quer conhecer?"
    )


def test_repaired_validator_preserves_facts_accepted_before_question_repair():
    interpretation = {
        "intents": [], "state_relation": "continue", "answers_field_key": None,
        "confirmation": {
            "state": "none", "target_ref": None, "evidence_span": "",
            "correction_field_key": None, "correction_value": None,
        },
        "branch_selections": [], "facts": [], "invalidated_facts": [],
        "entities": [], "questions": [], "claims": [],
        "recommended_next_action": "answer_question",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "response": {
            "answer": "Prazer, Ana.", "question": None,
            "question_field_key": None,
        },
        "handoff_requested": False,
    }
    accepted = [{
        "field_key": "name", "value": "Ana", "status": "known",
        "owner_node_id": "persona:test", "evidence_span": "Ana",
        "source_message_id": "msg:1", "metadata": {},
    }]

    result = _run_response_validator(
        "Validate repaired agent response",
        {"choices": [{"message": {"content": json.dumps(interpretation)}}]},
        accepted_facts=accepted,
    )

    assert result["model_observation"]["interpretation"]["facts"] == accepted


def test_n8n_repairs_repetition_with_the_model_before_commit():
    gate = _node("Graph proof needs repair")["parameters"]["conditions"]["conditions"][0][
        "leftValue"
    ]
    repair = _node("Build graph repair request")["parameters"]["jsCode"]
    repaired_validator = _node("Validate repaired agent response")["parameters"]["jsCode"]

    assert "proof.repair_required" in gate
    assert "repetition_audit" not in gate
    assert "invalid or repeated" in repair
    assert "response.question" in repair
    assert "preserved_accepted_facts: proof.accepted_facts" in repair
    assert "const preservedFacts" in repaired_validator
    assert "preservedFacts.filter" in repaired_validator


def test_completed_commit_uses_the_status_key_consumed_by_the_claim_rpc():
    assert "jsonb_build_object('status','completed'" in SQL
    assert "payload->'conversation_commit'->>'status'" in SQL


def test_every_backend_repair_requirement_reaches_the_model_repair_call():
    condition = _node("Graph proof needs repair")["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert "proof.repair_required" in condition
    assert "deterministic_branch_match" not in condition
