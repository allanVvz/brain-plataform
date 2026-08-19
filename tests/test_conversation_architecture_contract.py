from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/111_proof_gated_outbox_and_burst_claim.sql").read_text(encoding="utf-8")
WORKFLOW = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))


def _node(name: str) -> dict:
    return next(node for node in WORKFLOW["nodes"] if node["name"] == name)


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


def test_model_prompt_receives_complete_multi_service_memory_contract():
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]
    initial_validator = _node("Validate agent response")["parameters"]["jsCode"]
    repair_validator = _node("Validate repaired agent response")["parameters"]["jsCode"]
    assert "['none','keep','select','switch','add']" in initial
    assert "required: ['action','branch_anchor_node_id','branch_path_checksum','evidence_span']" in initial
    assert "'service_operations'" in initial
    assert "'service_operations'" in initial_validator
    assert "'service_operations'" in repair_validator
    assert "'service_observations'" in initial
    assert "'service_observations'" in initial_validator
    assert "'service_observations'" in repair_validator
    assert "active_branch_node_ids: context.active_branch_node_ids" in initial
    assert "facts_by_key: context.cart && context.cart.facts_by_key" in initial
    assert "known_facts: context.known_facts" in initial
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
        "semantic_score_min: 0.78",
        "semantic_margin_min: 0.08",
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
