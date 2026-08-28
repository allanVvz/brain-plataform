from schemas.conversation import SemanticInterpretation
from services.semantic_conversation_policy import (
    interpretation_reply,
    interpretation_to_proposal,
)


def test_complete_answer_is_never_concatenated_with_compat_question():
    question = "Que tipo de volume voce pretende avaliar para revenda?"
    interpretation = SemanticInterpretation.model_validate({
        "response": {
            "answer": f"Posso te orientar. {question}",
            "question": question,
            "question_field_key": "volume",
        },
    })

    proposal = interpretation_to_proposal(interpretation)

    assert interpretation_reply(interpretation).count(question) == 1
    assert proposal.reply.count(question) == 1
    assert proposal.answer_text == proposal.reply
    assert proposal.question_text == ""
    assert proposal.next_question_field_key == "volume"


def test_compat_question_is_used_only_when_answer_is_empty():
    interpretation = SemanticInterpretation.model_validate({
        "response": {
            "answer": "",
            "question": "Como posso ajudar?",
            "question_field_key": None,
        },
    })

    proposal = interpretation_to_proposal(interpretation)

    assert proposal.reply == "Como posso ajudar?"
    assert proposal.question_text == ""
