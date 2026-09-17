import pytest

from services import conversation_workflow_service


@pytest.mark.parametrize(
    "operation",
    [
        conversation_workflow_service.provision,
        conversation_workflow_service.provision_validation_candidate,
        conversation_workflow_service.resync_workflow_for_persona,
    ],
)
def test_legacy_n8n_conversation_mutations_are_retired(operation):
    with pytest.raises(RuntimeError, match="retired"):
        operation()


def test_historical_workflow_audit_is_fail_closed():
    result = conversation_workflow_service.check_workflow_wiring()
    assert result == {
        "ok": False,
        "reason": conversation_workflow_service._RETIRED,
        "diagnostics": {"retired": True},
    }
