from types import SimpleNamespace

import pytest

from scripts.probe_conversation_candidate import select_cases, validate_case


def test_candidate_can_select_one_baked_case_for_the_affected_persona():
    cases = select_cases("human-conversation-2026-09-25", "tock-consultative-answer-with-name-pending")
    assert [case["name"] for case in cases] == ["tock-consultative-answer-with-name-pending"]
    with pytest.raises(ValueError, match="must match exactly once"):
        select_cases("human-conversation-2026-09-25", "missing-case")


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

    with pytest.raises(AssertionError, match="repeated the interrupted"):
        validate_case(case, result)

    result["response"].proof.update(asked_field_key=None, question_kind="none")
    with pytest.raises(AssertionError, match="public text"):
        validate_case(case, result)

    result["response"].proof["repetition_audit"] = {"passed": True}
    with pytest.raises(AssertionError, match="public text"):
        validate_case(case, result)
