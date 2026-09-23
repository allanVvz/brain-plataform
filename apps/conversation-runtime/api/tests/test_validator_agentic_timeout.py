"""Regression guard for the validator/transport agentic deadline contract."""

from pathlib import Path


def test_agentic_validator_wait_exceeds_transport_execution_budget():
    source = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "wa_validator_service.py"
    ).read_text(encoding="utf-8")

    assert "_AGENTIC_CANONICAL_COMMIT_WAIT_SECONDS = 150.0" in source
    assert "max(configured_wait, 45.0)" not in source
