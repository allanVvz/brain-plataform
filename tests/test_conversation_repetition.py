from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import conversation_repetition


def test_shared_conversation_repetition_corpus():
    cases = json.loads(
        (ROOT / "tests" / "fixtures" / "conversation_repetition_cases.json")
        .read_text(encoding="utf-8")
    )
    for case in cases:
        result = conversation_repetition.assess_repetition(
            current_reply=case["current_reply"],
            recent_replies=case.get("previous_replies") or [],
            question_node_id=case.get("question_node_id"),
            question_text=case.get("question_text"),
            asked_question_node_ids=case.get("asked_question_node_ids") or [],
            max_attempts=case.get("max_attempts", 0),
            field_pending=bool(case.get("field_pending")),
            terminal_intent=case.get("terminal_intent"),
            previous_terminal_intent=case.get("previous_terminal_intent"),
        )
        assert result["failures"] == case["expected_failures"], case["name"]


def test_legacy_retry_setting_cannot_authorize_a_second_question_emission():
    result = conversation_repetition.assess_repetition(
        current_reply="A equipe registrou o contexto informado. Qual é o seu nome?",
        question_node_id="q:name",
        question_text="Qual é o seu nome?",
        asked_question_node_ids=["q:name"],
        max_attempts=1,
        field_pending=True,
    )
    assert result["failures"] == ["question_already_asked"]
    assert result["allowed_question_emissions"] == 1


def test_tock_volume_contextual_bridge_does_not_authorize_reasking_the_field():
    result = conversation_repetition.assess_repetition(
        current_reply=(
            "Perfeito, 4 peças! Vou registrar seu interesse. "
            "Que tipo de volume você pretende avaliar para revenda?"
        ),
        question_node_id="faq:tock-reseller-volume",
        question_text="Que tipo de volume você pretende avaliar para revenda?",
        asked_question_node_ids=["faq:tock-reseller-volume"],
        max_attempts=1,
        field_pending=True,
    )

    assert result["failures"] == ["question_already_asked"]
    assert result["contextual_bridge"]
