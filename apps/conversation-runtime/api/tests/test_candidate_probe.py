from types import SimpleNamespace

import pytest

from scripts.probe_conversation_candidate import validate_case


def test_candidate_rejects_interrupted_field_repeated_by_model():
    case = {
        "forbidden_asked_fields": ["nome_cliente"],
        "allowed_question_kinds": ["consultative", "none"],
        "forbid_reply_repetition": True,
    }
    result = {
        "model_calls": 2,
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
    with pytest.raises(AssertionError, match="repeated a recent"):
        validate_case(case, result)

    result["response"].proof["repetition_audit"] = {"passed": True}
    validate_case(case, result)
