"""Regression guard for the validator/transport agentic deadline contract."""

import asyncio
from pathlib import Path

from services import wa_validator_service


def test_agentic_validator_wait_exceeds_transport_execution_budget():
    source = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "wa_validator_service.py"
    ).read_text(encoding="utf-8")

    assert "_AGENTIC_CANONICAL_COMMIT_WAIT_SECONDS = 150.0" in source
    assert "max(configured_wait, 45.0)" not in source


def test_agentic_validator_stops_waiting_on_canonical_technical_failure(monkeypatch):
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "audit_conversation_turn_v3",
        lambda _buffer_id: {
            "inbound_count": 1,
            "decision_count": 0,
            "proof_count": 0,
            "commit_state": None,
        },
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "list_system_events",
        lambda **_kwargs: [{
            "payload": {
                "stage": "understanding_model",
                "reason": "agentic_turn_failed:understanding_model",
                "diagnostic": {
                    "http_code": 402,
                    "message": (
                        "model request failed: HTTP 402 "
                        "(invalid_request_error; unknown_error; Insufficient Balance)"
                    ),
                    "secret": "must-not-be-exposed",
                },
            }
        }],
    )

    audit = asyncio.run(wa_validator_service._wait_for_turn_audit_v3(
        "buffer-1", max_wait_s=150,
    ))

    failure = audit["technical_failure"]
    assert failure == {
        "stage": "understanding_model",
        "reason": "agentic_turn_failed:understanding_model",
        "http_status": "402",
        "technical_message": (
            "model request failed: HTTP 402 "
            "(invalid_request_error; unknown_error; Insufficient Balance)"
        ),
    }
    message = wa_validator_service._technical_failure_message(failure)
    assert message == (
        "Canonical agentic turn failed at understanding_model "
        "(provider HTTP 402; model request failed: HTTP 402 "
        "(invalid_request_error; unknown_error; Insufficient Balance))"
    )
    assert "must-not-be-exposed" not in message
