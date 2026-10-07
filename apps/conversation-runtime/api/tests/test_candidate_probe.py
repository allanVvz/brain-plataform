from types import SimpleNamespace

import pytest

from scripts.probe_conversation_candidate import quality_observations, select_cases, validate_case


def test_candidate_can_select_one_baked_case_for_the_affected_persona():
    cases = select_cases("human-conversation-2026-09-25", "tock-consultative-answer-with-name-pending")
    assert [case["name"] for case in cases] == ["tock-consultative-answer-with-name-pending"]
    with pytest.raises(ValueError, match="must match exactly once"):
        select_cases("human-conversation-2026-09-25", "missing-case")
    greeting = select_cases("human-conversation-2026-09-25", "tock-greeting-ooi-question-metadata")
    assert greeting[0]["message"] == "ooi"


def test_candidate_rejects_public_question_without_question_kind():
    result = {
        "model_calls": 2,
        "context": SimpleNamespace(graph_contract={}, retrieval_trace={}),
        "response": SimpleNamespace(reply_text="Como posso ajudar?", proof={
            "valid": True, "delivery_authorized": True, "accepted_facts": [],
            "question_kind": "none", "asked_field_key": None,
        }),
    }
    validate_case({}, result)
    assert "candidate_public_question_kind_missing" in quality_observations({}, result)


def test_candidate_rejects_interrupted_field_repeated_by_model():
    case = {
        "forbidden_asked_fields": ["nome_cliente"],
        "allowed_question_kinds": ["consultative", "none"],
        "forbid_reply_repetition": True,
    }
    result = {
        "model_calls": 2,
        "context": SimpleNamespace(
            graph_contract={
                "fields": [{"key": "nome_cliente", "question_node_id": "faq:name",
                            "validation": {"semantic_type": "human_full_name"}}],
                "questions": {"faq:name": {"text": "Como você prefere que eu te chame?"}},
            },
            retrieval_trace={},
        ),
        "response": SimpleNamespace(
            reply_text="Como prefere que eu te chame?",
            proof={"valid": True, "delivery_authorized": True,
                   "accepted_facts": [], "asked_field_key": "nome_cliente",
                   "question_kind": "qualification",
                   "repetition_audit": {"passed": False}},
        ),
    }

    validate_case(case, result)
    assert "candidate_interrupted_field_repeated_in_metadata" in quality_observations(case, result)

    result["response"].proof.update(asked_field_key=None, question_kind="none")
    validate_case(case, result)
    assert "candidate_interrupted_field_repeated_in_text" in quality_observations(case, result)
    result["response"].proof["repetition_audit"] = {"passed": True}
    assert "candidate_interrupted_field_repeated_in_text" in quality_observations(case, result)


def test_candidate_rejects_utzig_name_question_marked_consultative():
    result = {
        "model_calls": 2,
        "context": SimpleNamespace(
            graph_contract={
                "fields": [{"key": "nome_cliente", "question_node_id": "faq:name",
                            "validation": {"semantic_type": "human_full_name"}}],
                "questions": {"faq:name": {"field_key": "nome_cliente",
                                           "text": "Como você prefere que eu te chame?"}},
            }, retrieval_trace={},
        ),
        "response": SimpleNamespace(
            reply_text="Posso te chamar de Utzig?",
            proof={"valid": True, "delivery_authorized": True,
                   "accepted_facts": [], "asked_field_key": None,
                   "question_kind": "consultative"},
        ),
    }
    validate_case({}, result)
    assert "candidate_question_metadata_mismatch" in quality_observations({}, result)
