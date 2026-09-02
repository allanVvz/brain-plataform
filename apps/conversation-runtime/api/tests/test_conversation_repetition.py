from services import conversation_repetition


def test_repeated_pending_field_accepts_natural_question_after_contextual_answer():
    result = conversation_repetition.assess_repetition(
        current_reply=(
            "Entendi, você quer algo para o dia a dia. Temos várias opções "
            "que combinam com isso. Qual tipo de peça você prefere?"
        ),
        recent_replies=[
            "Para uso próprio temos várias opções. O que você está procurando?"
        ],
        question_node_id="faq:tock-retail-need",
        question_text="O que você está procurando no momento?",
        asked_question_node_ids=["faq:tock-retail-need"],
        max_attempts=1,
        field_pending=True,
    )

    assert result["passed"] is True
    assert result["failures"] == []
    assert result["contextual_bridge"] == (
        "entendi voce quer algo para o dia a dia temos varias opcoes "
        "que combinam com isso"
    )


def test_repeated_pending_field_still_blocks_bare_natural_reask():
    result = conversation_repetition.assess_repetition(
        current_reply="Qual tipo de peça você prefere?",
        question_node_id="faq:tock-retail-need",
        question_text="O que você está procurando no momento?",
        asked_question_node_ids=["faq:tock-retail-need"],
        max_attempts=1,
        field_pending=True,
    )

    assert result["passed"] is False
    assert result["failures"] == ["contextual_bridge_required"]
    assert result["contextual_bridge"] == ""
