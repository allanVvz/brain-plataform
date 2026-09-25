from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service
from routes.wa_validator import GenerateScriptRequest


def test_release_canary_keeps_one_graph_opening_and_internal_transport(monkeypatch):
    session = {
        "id": "session-1", "status": "ready",
        "script": {
            "meta": {"pipeline_contract": "conversation_agentic_v1"},
            "driver": {
                "mode": "semantic_graph_v1",
                "opening": {"text": "Quero conhecer o serviço."},
            },
            "steps": [{"text": "outro turno"}],
        },
    }
    captured = {}
    monkeypatch.setattr(wa_validator_service, "_session_get", lambda _id: session)
    monkeypatch.setattr(
        wa_validator_service, "_session_update",
        lambda _id, **fields: captured.update(fields) or fields,
    )

    wa_validator_service.configure_single_turn_canary("session-1")

    script = captured["script"]
    assert script["steps"] == [{"text": "Quero conhecer o serviço.", "wait": 10}]
    assert script["driver"] is None
    assert script["meta"]["pipeline_contract"] == "conversation_agentic_v1"


def test_validator_request_rejects_retired_n8n_candidate_webhook():
    with pytest.raises(ValidationError):
        GenerateScriptRequest.model_validate({
            "persona_slug": "fixture-persona",
            "flow_id": "sdr_sales_retail",
            "target_contact": "internal",
            "validation_target_url": "https://n8n.example.test/webhook/qa-candidate",
        })


def _audit_inputs(*, conversation_mode: str) -> dict:
    fields = [
        {
            "key": "name",
            "owner_node_id": "persona:one",
            "required": True,
            "question_node_id": "q:name",
        },
        {
            "key": "objective",
            "owner_node_id": "branch:one",
            "required": True,
            "question_node_id": "q:objective",
        },
    ]
    contract = {
        "fields": fields,
        "questions": {
            "q:name": {"field_key": "name", "text": "Qual é o seu nome?"},
            "q:objective": {
                "field_key": "objective",
                "text": "Qual é o seu objetivo?",
            },
        },
        "conversation_policy": {"question_repetition": {"max_attempts": 1}},
    }
    return {
        "customer_step": {
            "text": "Quero algumas peças para uso próprio.",
            "intended_facts": {},
            "expected_branch_node_id": "branch:one",
        },
        "turn": {
            "text": (
                "Que bom, entendi que as peças são para você. "
                "O que você gostaria de encontrar para o dia a dia?"
            ),
            "intent": "collect_graph_fields",
            "route": "SDR",
            "handoff": False,
            "evidence_node_ids": [],
        },
        "proof_record": {
            "proof_result": {
                "accepted_facts": [],
                "missing_fields": ["name", "objective"],
                "next_question_node_id": "q:objective",
                "qualification_complete": False,
                "handoff_requested": False,
                "fallback_used": False,
                "model_proposal_errors": [],
            },
            "final_decision": {
                "intent": "collect_graph_fields",
                "evidence_node_ids": [],
            },
        },
        "ledger_before": {"revision": 0, "facts": {}},
        "ledger_after": {
            "revision": 1,
            "active_branch_node_id": "branch:one",
            "facts": {},
        },
        "contract": contract,
        "recent_replies": [],
        "previous_question_node_id": None,
        "expected_handoff": True,
        "conversation_mode": conversation_mode,
    }


def test_agentic_validator_accepts_any_askable_field_and_natural_wording():
    audit = wa_validator_service._semantic_turn_audit(
        **_audit_inputs(conversation_mode="n8n_agents")
    )

    assert audit["passed"] is True
    assert audit["asked_field"] == "objective"
    assert audit["first_missing_field"] == "name"
    assert audit["criteria"]["question_semantically_askable"] is True


def test_question_askability_is_audited_but_never_blocks_a_session():
    audit = wa_validator_service._semantic_turn_audit(
        **_audit_inputs(conversation_mode="deterministic")
    )

    assert audit["criteria"]["question_semantically_askable"] is False
    assert audit["passed"] is True
    assert audit["failures"] == []
    assert audit["non_blocking_observations"] == [
        "question_semantically_askable"
    ]


def test_reply_pattern_variations_are_audited_without_blocking_a_proved_turn():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    inputs["customer_step"].update({
        "required_reply_patterns": [r"\\bfrase\\s+literal\\b"],
        "forbidden_reply_patterns": [r"dia a dia"],
    })

    audit = wa_validator_service._semantic_turn_audit(**inputs)

    assert audit["criteria"]["required_reply_content"] is False
    assert audit["criteria"]["forbidden_reply_content_absent"] is False
    assert audit["passed"] is True
    assert audit["failures"] == []
    assert audit["non_blocking_observations"] == [
        "required_reply_content",
        "forbidden_reply_content_absent",
    ]


def test_agentic_validator_accepts_optional_collect_once_name_before_required_field():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    name_field = inputs["contract"]["fields"][0]
    name_field.update({
        "key": "nome_cliente",
        "required": False,
        "collection_mode": "ask_once_optional",
    })
    inputs["contract"]["questions"]["q:name"]["field_key"] = "nome_cliente"
    inputs["proof_record"]["proof_result"].update({
        "missing_fields": ["objective"],
        "next_question_node_id": "q:name",
    })
    inputs["turn"]["text"] = "Como voce prefere que eu te chame?"

    audit = wa_validator_service._semantic_turn_audit(**inputs)

    assert audit["passed"] is True
    assert audit["asked_field"] == "nome_cliente"
    assert audit["first_missing_field"] == "objective"
    assert audit["criteria"]["question_semantically_askable"] is True


def test_validator_uses_understanding_resolution_for_committed_branch_operation():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    operation = {
        "action": "add",
        "branch_anchor_node_id": "branch:one",
        "branch_path_checksum": "sha256:branch",
        "evidence_span": "uso prÃ³prio",
        "evidence_type": "confirmed_candidate",
    }
    inputs["proof_record"]["proof_result"].update({
        "service_resolution": {"operations": [], "consumed_spans": []},
        "understanding_service_resolution": {
            "operations": [operation],
            "consumed_spans": [
                {"text": "uso prÃ³prio", "evidence_type": "confirmed_candidate"},
            ],
        },
        "applied_service_operations": [operation],
        "consumed_service_spans": [],
    })

    audit = wa_validator_service._semantic_turn_audit(**inputs)

    assert audit["criteria"]["service_operations_match_resolution"] is True
    assert audit["criteria"]["service_operations_have_authorized_evidence"] is True
    assert audit["passed"] is True


def test_agentic_validator_accepts_consultative_turn_when_no_field_is_askable():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    inputs["contract"]["fields"] = []
    inputs["contract"]["questions"] = {}
    inputs["proof_record"]["proof_result"].update({
        "missing_fields": ["unresolved_without_question"],
        "next_question_node_id": None,
        "confirmation_state": "consultative_support",
        "consultative_support": True,
    })
    inputs["turn"]["text"] = (
        "Posso explicar as condições publicadas. Qual ponto você quer esclarecer?"
    )

    audit = wa_validator_service._semantic_turn_audit(**inputs)

    assert audit["criteria"]["question_semantically_askable"] is True


def test_sales_driver_answers_unresolved_question_without_requiring_branch_switch_repetition():
    driver = {
        "switch": {
            "after_answered_fields": 0,
            "text": "Na verdade, e para uso proprio.",
            "expected_branch_node_id": "branch:retail",
        },
        "answers": {
            "nome_cliente": {
                "text": "Pode me chamar de Beatriz",
                "value": "Beatriz",
            },
        },
    }
    state = {}

    branch_switch = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="nome_cliente",
        answered_fields=set(),
        active_anchor="branch:reseller",
        expected_active_branches=["branch:reseller"],
    )
    name_answer = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="",
        answered_fields=set(),
        active_anchor="branch:retail",
        expected_active_branches=["branch:retail"],
    )

    assert branch_switch["kind"] == "branch_switch"
    assert state["switch_interrupted_field"] == "nome_cliente"
    assert name_answer == {
        "text": "Pode me chamar de Beatriz",
        "kind": "field_answer",
        "intended_facts": {"nome_cliente": "Beatriz"},
        "expected_branch_node_id": "branch:retail",
        "expected_active_branch_node_ids": ["branch:retail"],
    }


def test_sales_driver_answers_optional_name_before_final_confirmation():
    driver = {
        "answers": {
            "nome_cliente": {"text": "Pode me chamar de Beatriz", "value": "Beatriz"},
        },
        "confirmation": {"text": "Sim"},
    }
    state = {}

    step = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="nome_cliente",
        answered_fields=set(),
        active_anchor="branch:retail",
        expected_active_branches=["branch:retail"],
        qualification_complete=True,
    )

    assert step["kind"] == "field_answer"
    assert step["intended_facts"] == {"nome_cliente": "Beatriz"}
    assert state.get("confirmation_sent") is None


def test_semantic_turn_audit_flags_immediate_name_retry_but_allows_later_resume():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    inputs["contract"]["fields"][0]["key"] = "nome_cliente"
    inputs["contract"]["questions"]["q:name"]["field_key"] = "nome_cliente"
    inputs["proof_record"]["proof_result"]["missing_fields"] = [
        "nome_cliente", "objective",
    ]
    inputs["proof_record"]["proof_result"]["next_question_node_id"] = "q:name"
    inputs["ledger_before"]["asked_question_node_ids"] = ["q:name"]
    inputs["ledger_after"]["asked_question_node_ids"] = ["q:name", "q:name"]
    inputs["turn"]["text"] = "Entendi sua preferência. Para continuar, qual é o seu nome?"
    inputs["recent_replies"] = ["Qual é o seu nome?"]

    immediate = wa_validator_service._semantic_turn_audit(**inputs)

    assert immediate["criteria"]["customer_name_question_timing"] is False
    assert "customer_name_question_timing" in immediate["non_blocking_observations"]
    assert immediate["criteria"]["question_repetition_budget"] is True

    inputs["recent_replies"].append("Sua dúvida foi respondida. Podemos seguir quando quiser.")
    later = wa_validator_service._semantic_turn_audit(**inputs)

    assert later["criteria"]["customer_name_question_timing"] is True
    assert later["criteria"]["question_repetition_budget"] is True
    assert later["passed"] is True
