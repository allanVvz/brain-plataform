from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "vps" / "verify_first_claim.py"
INBOUND = "11111111-1111-4111-8111-111111111111"


def invoke(payload: dict):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inbound-id", INBOUND],
        input=json.dumps(payload), capture_output=True, text=True,
    )


def test_exactly_once_audit_passes():
    result = invoke({
        "inbound_id": INBOUND,
        "inbound_count": 1,
        "decision_count": 1,
        "proof_count": 1,
        "valid_proof_count": 1,
        "commit_state": "completed",
        "outbound_count": 1,
        "outbound_released_after_proof": True,
    })
    assert result.returncode == 0, result.stderr


def test_duplicate_decision_fails_closed():
    result = invoke({
        "inbound_id": INBOUND,
        "inbound_count": 1,
        "decision_count": 2,
        "proof_count": 1,
        "valid_proof_count": 1,
        "commit_count": 1,
        "commit_state": "completed",
        "outbound_count": 1,
        "outbound_released_after_proof": True,
    })
    assert result.returncode != 0
    assert "one_decision" in result.stderr
