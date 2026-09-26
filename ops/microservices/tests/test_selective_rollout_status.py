import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-selective-rollout-status.py"
SPEC = importlib.util.spec_from_file_location("selective_rollout_status", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
verify_output = MODULE.verify_output


def test_selective_release_ignores_unaffected_service_drift():
    output = """gateway                slot=blue   up to date
control-plane          slot=green  BEHIND
conversation-runtime   slot=green  up to date
transport              slot=blue   up to date
workers pending blue/green replacement (3):
  brain-ai-control-plane-knowledge-green-1
  brain-ai-control-plane-integrations-green-1
  brain-ai-control-plane-validator-green-1
"""

    verify_output("conversation-runtime", output)


def test_selective_release_rejects_target_service_drift():
    output = "conversation-runtime   slot=green  BEHIND\n"

    with pytest.raises(ValueError, match="not up to date: conversation-runtime"):
        verify_output("conversation-runtime", output)


def test_selective_release_rejects_target_worker_drift():
    output = """conversation-runtime   slot=green  up to date
workers pending blue/green replacement (1):
  brain-ai-runtime-validator-green-1
"""

    with pytest.raises(ValueError, match="workers pending replacement"):
        verify_output("conversation-runtime", output)


def test_selective_release_rejects_missing_target_status():
    with pytest.raises(ValueError, match="not up to date: transport"):
        verify_output("transport", "gateway                slot=blue   up to date\n")
