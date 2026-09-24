from __future__ import annotations

import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_proof_checker_v3


@pytest.mark.parametrize("answer", ["Sim", "Não", "Yes", "OK"])
def test_bare_acknowledgement_is_not_a_customer_name(answer: str):
    field = {"validation": {"mode": "semantic", "semantic_type": "human_name"}}

    value, error = graph_proof_checker_v3._canonical_field_value(field, answer, answer)

    assert value == answer
    assert error == "value is not a plausible human name"
    assert graph_proof_checker_v3.is_human_full_name(
        answer, min_tokens=1,
    ) is False


def test_a_short_genuine_name_remains_valid():
    field = {"validation": {"mode": "semantic", "semantic_type": "human_name"}}

    value, error = graph_proof_checker_v3._canonical_field_value(
        field, "Ana", "Ana",
    )

    assert (value, error) == ("Ana", None)
