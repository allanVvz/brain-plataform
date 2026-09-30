"""Read-only candidate identity gate; never logs credentials or tokens."""
import json
import os
import sys
from uuid import UUID, uuid4
from fastapi import HTTPException
from services import auth_service


def verify(fixture):
    assert os.environ.get("AKIA_PORTAL_AUTH_ENABLED") == "true"
    assert fixture.get("state") == "active_fixture"
    assert fixture["email"].startswith("codex-north-e2e-") and fixture["email"].endswith("@example.test")
    UUID(fixture["brainId"])
    user = auth_service.authenticate(fixture["email"], fixture["password"])
    assert user["id"] == fixture["brainId"] and user["role"] == "user"
    session = auth_service.build_session_response(user)
    assert session["personas"] == []
    assert session["navigation"]["allowed_portals"] == ["north"]
    assert session["navigation"]["surface"] == "operations"
    assert session["permissions"]["persona_access"] == []
    try:
        auth_service.authenticate(fixture["email"], "invalid-random-password-" + str(uuid4()))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Invalid credential accepted")
    try:
        auth_service.build_session_response({"id": str(uuid4()), "role": "user", "account_type": "internal"})
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Absent grants accepted")
    return {"passed": True, "mode": "north_auth_candidate", "portals": ["north"], "personas": 0, "persistent_writes": 0}


if __name__ == "__main__":
    try:
        result = verify(json.load(sys.stdin))
    except Exception:
        print(json.dumps({"passed": False, "mode": "north_auth_candidate", "error": "identity_gate_failed_no_private_data_logged"}))
        raise SystemExit(1)
    print(json.dumps(result))
