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
        "cart": {"facts_by_key": {"customer_name": [{"value": "Luiza"}]}},
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
    assert "agent_behavior: 'system_message'" in initial
    assert "graph_and_cards: 'top_level_graph_contract_approved_nodes_approved_chunks'" in initial
    assert "memory: 'top_level_shared_memory'" in initial
    assert "persona_policy: { '$ref': 'graph_contract.conversation_policy' }" in initial
    assert "common_contract: commonContractPrompt" in initial
    assert "['agent_activity','journey_outcomes','recent_messages','historical_facts']" in initial
    assert "promptEstimatedTokens > 22000" in initial
    assert "messages: [...original.messages" not in repair
    assert "const originalContext = JSON.parse(original.messages[1].content" in repair
    assert "facts_by_key: originalContext.facts_by_key" in repair
    assert "shared_memory: originalContext.shared_memory" in repair


def test_aurora_sized_audio_prompt_stays_below_preventive_budget_without_losing_evidence():
    message = "[audio do cliente]: Eu queria saber como funciona o polimento de vidros."
    context, binding = _prompt_fixture(large=True, message=message)

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    legacy_prompt = {
        **prompt,
        "common_contract": context["retrieval_trace"]["common_contract"],
        "prompt_layers": {
            **prompt["prompt_layers"],
            "persona_policy": context["graph_contract"]["conversation_policy"],
        },
    }
    legacy_messages = [
        result["request_body"]["messages"][0],
        {"role": "user", "content": json.dumps(legacy_prompt, ensure_ascii=False, separators=(",", ":"))},
    ]
    legacy_estimate = (len(json.dumps(legacy_messages, ensure_ascii=False, separators=(",", ":"))) + 3) // 4

    assert legacy_estimate > 24_000
    assert result["prompt_estimated_tokens"] <= 22_000
    assert prompt["customer_message"] == message
    assert prompt["prompt_layers"]["turn"]["customer_message"] == message
    assert prompt["source_message_id"] == "wamid-audio-1"
    assert prompt["graph_contract"] == context["graph_contract"]
    assert prompt["approved_nodes"][0]["node_id"] == "faq-polimento"
    assert prompt["approved_chunks"][0]["text"] == context["rag_chunks"][0]["chunk_text"]
    assert prompt["facts_by_key"] == context["cart"]["facts_by_key"]
    assert prompt["shared_memory"]["profile_facts"] == context["shared_memory"]["profile_facts"]
    assert prompt["shared_memory"]["current_journey"] == context["shared_memory"]["current_journey"]
    assert prompt["shared_memory"]["pending_items"] == context["shared_memory"]["pending_items"]
    assert prompt["common_contract"] == {
        "$ref": "graph_contract", "scope": "common_fields_questions_claims",
    }
    assert prompt["prompt_layers"]["persona_policy"] == {
        "$ref": "graph_contract.conversation_policy",
    }
    optional = prompt["shared_memory"]
    order = ["agent_activity", "journey_outcomes", "recent_messages", "historical_facts"]
    first_retained = next((index for index, key in enumerate(order) if optional[key]), len(order))
    assert all(not optional[key] for key in order[:first_retained])


def test_tock_sized_audio_prompt_preserves_current_behavior_and_full_transcription():
    message = "[audio do cliente]: Quero comprar no varejo."
    context, binding = _prompt_fixture(large=False, message=message)

    result = _run_prompt_builder(context, binding)
    prompt = json.loads(result["request_body"]["messages"][1]["content"])

    assert result["prompt_estimated_tokens"] < 22_000
    assert prompt["customer_message"] == message
    assert prompt["prompt_layers"]["turn"]["customer_message"] == message
    for key in ("agent_activity", "journey_outcomes", "recent_messages", "historical_facts"):
        assert prompt["shared_memory"][key] == context["shared_memory"][key]


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
    assert "shared_memory: boundedMemory" in initial
    for field in (
        "journey: { id: context.journey_id",
        "pending_field_key: context.pending_field_key",
        "pending_question_node_id: context.pending_question_node_id",
        "last_handoff: context.last_handoff",
        "pending_reconfirmation: context.pending_reconfirmation",
        "time_since_last_client_message: context.time_since_last_client_message",
        "operational_mode: context.operational_mode",
        "service_catalog: context.available_services",
        "service_resolution: context.retrieval_trace",
        # semantic_score_min/semantic_margin_min lived on the removed
        # service_observations_policy object -- service_observations has no
        # successor field in the semantic interpretation contract.
        "consumed_service_spans:",
        "reserved_spans:",
        "common_contract:",
        "pending_confirmation:",
        "confirmation_templates:",
    ):
        assert field in initial


def test_completed_commit_uses_the_status_key_consumed_by_the_claim_rpc():
    assert "jsonb_build_object('status','completed'" in SQL
    assert "payload->'conversation_commit'->>'status'" in SQL


def test_unambiguous_graph_branch_cannot_trigger_a_repair_call():
    condition = _node("Graph proof needs repair")["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert "deterministic_branch_match" in condition
