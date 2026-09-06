from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service


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


def test_deterministic_validator_keeps_first_published_question_contract():
    audit = wa_validator_service._semantic_turn_audit(
        **_audit_inputs(conversation_mode="deterministic")
    )

    assert audit["passed"] is False
    assert "question_semantically_askable" in audit["failures"]


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


def test_semantic_turn_audit_counts_name_question_ids_not_only_similar_wording():
    inputs = _audit_inputs(conversation_mode="n8n_agents")
    inputs["contract"]["fields"][0]["key"] = "nome_cliente"
    inputs["contract"]["questions"]["q:name"]["field_key"] = "nome_cliente"
    inputs["proof_record"]["proof_result"]["missing_fields"] = [
        "nome_cliente", "objective",
    ]
    inputs["ledger_after"]["asked_question_node_ids"] = ["q:name", "q:name"]
    inputs["turn"]["text"] = "Como posso te chamar para continuarmos?"

    audit = wa_validator_service._semantic_turn_audit(**inputs)

    assert audit["criteria"]["customer_name_question_once"] is False
    assert "customer_name_question_once" in audit["failures"]
