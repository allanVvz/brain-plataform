from __future__ import annotations

import json
from pathlib import Path

from services import graph_agent_runtime_v3


CORPUS_PATH = Path(__file__).parent / "fixtures" / "sdr_flow_cases.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in CORPUS["cases"]}


def test_shared_sdr_corpus_has_unique_stable_cases():
    assert CORPUS["version"] == 1
    assert len(CASES) == len(CORPUS["cases"])
    assert {"greeting_after_handoff_oi", "greeting_after_handoff_oii"} <= set(CASES)


def test_shared_greetings_are_current_turn_intents_and_not_services():
    for case_id in ("greeting_after_handoff_oi", "greeting_after_handoff_oii"):
        message = CASES[case_id]["message"]
        assert graph_agent_runtime_v3._is_greeting(message)
        assert graph_agent_runtime_v3._is_social_or_non_service_value(message)


def test_shared_mixed_greeting_preserves_the_service_request():
    case = CASES["greeting_with_service"]
    assert graph_agent_runtime_v3._is_greeting(case["message"])
    assert not graph_agent_runtime_v3._is_bare_greeting(case["message"])
    assert case["expected_service_phrase"] in case["message"].casefold()


def test_shared_confirmation_cases_are_unambiguous():
    assert graph_agent_runtime_v3._is_explicit_confirmation(
        CASES["explicit_confirmation"]["message"]
    )
    assert graph_agent_runtime_v3._is_explicit_rejection(
        CASES["confirmation_rejected"]["message"]
    )


def test_shared_non_service_values_are_rejected():
    for case_id in ("social_reply_is_not_service", "number_is_not_service"):
        assert graph_agent_runtime_v3._is_social_or_non_service_value(
            CASES[case_id]["message"]
        )
