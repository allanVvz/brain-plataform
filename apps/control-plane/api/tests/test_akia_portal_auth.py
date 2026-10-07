import pytest
from fastapi import HTTPException
from services import auth_service


USER = {"id": "user-1", "role": "viewer", "account_type": "client", "is_active": True}


def arrange(monkeypatch, grants):
    monkeypatch.setenv("AKIA_PORTAL_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: grants)


def test_operation_only_user_can_login_with_explicit_grant(monkeypatch):
    arrange(monkeypatch, ["north"])
    result = auth_service.build_session_response(USER)
    assert result["personas"] == []
    assert result["permissions"]["persona_access"] == []
    assert result["navigation"] == {"surface": "operations", "home_url": "/north/client", "allowed_portals": ["north"]}


def test_no_persona_and_no_portal_grant_still_denied(monkeypatch):
    arrange(monkeypatch, [])
    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response(USER)
    assert exc.value.status_code == 403


def test_feature_disabled_preserves_brain_contract_and_never_calls_rpc(monkeypatch):
    arrange(monkeypatch, ["north"])
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED")
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: pytest.fail("RPC must not run"))
    persona = {"id": "p1", "slug": "aurora"}
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [persona])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [{"persona_id": "p1", "can_view": True}])
    result = auth_service.build_session_response(USER)
    assert "allowed_portals" not in result["navigation"]
    assert result["navigation"]["surface"] == "client_portal"
    assert result["personas"][0]["id"] == "p1"


def test_rpc_error_fails_closed_as_503(monkeypatch):
    monkeypatch.setattr(auth_service.supabase_client, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(HTTPException) as exc:
        auth_service._akia_portal_grants("user-1")
    assert exc.value.status_code == 503


def test_operations_only_login_fails_closed_when_grants_unavailable(monkeypatch):
    arrange(monkeypatch, [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: (_ for _ in ()).throw(HTTPException(503, "unavailable")))
    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response(USER)
    assert exc.value.status_code == 503


def test_internal_north_staff_can_login_without_persona_when_north_grant_is_explicit(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: ["north"])

    result = auth_service.build_session_response({
        "id": "north-staff", "role": "operator", "account_type": "internal",
    })

    assert result["personas"] == []
    assert result["navigation"]["surface"] == "operations"
    assert result["navigation"]["home_url"] == "/north/admin"
    # The portal gateway adds scoped navigation after checking the same grant.
    assert "allowed_portals" not in result["navigation"]


def test_agency_north_staff_can_login_without_persona_when_north_grant_is_explicit(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: ["north"])

    result = auth_service.build_session_response({
        "id": "north-agency-staff", "role": "user", "account_type": "agency",
    })

    assert result["personas"] == []
    assert result["navigation"]["surface"] == "operations"
    assert result["navigation"]["home_url"] == "/north/admin"
    assert "allowed_portals" not in result["navigation"]


def test_agency_staff_without_persona_or_north_grant_stays_denied(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: [])

    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response({
            "id": "unassigned-agency-staff", "role": "user", "account_type": "agency",
        })

    assert exc.value.status_code == 403


@pytest.mark.parametrize("account_type", ["internal", "agency"])
def test_operations_only_staff_fails_closed_when_portal_grant_lookup_is_unavailable(monkeypatch, account_type):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: (_ for _ in ()).throw(HTTPException(503, "unavailable")))

    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response({
            "id": "staff", "role": "user", "account_type": account_type,
        })

    assert exc.value.status_code == 503


def test_client_without_persona_does_not_use_staff_grant_fallback_when_portal_auth_is_disabled(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: pytest.fail("client fallback must not query portal grants"))

    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response({
            "id": "client", "role": "user", "account_type": "client",
        })

    assert exc.value.status_code == 403


def test_internal_user_without_persona_or_north_grant_stays_denied(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: [])

    with pytest.raises(HTTPException) as exc:
        auth_service.build_session_response({
            "id": "unassigned-internal", "role": "operator", "account_type": "internal",
        })

    assert exc.value.status_code == 403


def test_internal_staff_with_persona_keeps_legacy_login_without_portal_rpc(monkeypatch):
    monkeypatch.delenv("AKIA_PORTAL_AUTH_ENABLED", raising=False)
    persona = {"id": "p1", "slug": "legacy-brain-persona"}
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [persona])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [{"persona_id": "p1", "can_view": True}])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: pytest.fail("legacy persona login must not query portal grants"))

    result = auth_service.build_session_response({
        "id": "legacy-staff", "role": "operator", "account_type": "internal",
    })

    assert result["personas"][0]["slug"] == "legacy-brain-persona"


def test_existing_brain_persona_still_logs_in_when_operations_unavailable(monkeypatch):
    arrange(monkeypatch, [])
    monkeypatch.setattr(auth_service, "get_auth_personas", lambda: [{"id": "p1", "slug": "aurora"}])
    monkeypatch.setattr(auth_service, "get_user_access", lambda _id: [{"persona_id": "p1", "can_view": True}])
    monkeypatch.setattr(auth_service, "_akia_portal_grants", lambda _id: (_ for _ in ()).throw(HTTPException(503, "unavailable")))
    result = auth_service.build_session_response(USER)
    assert result["personas"][0]["id"] == "p1"
    assert result["navigation"]["allowed_portals"] == []


def test_rpc_uses_service_projection_and_validates_modes(monkeypatch):
    captured = {}
    class Client:
        def rpc(self, name, params):
            captured.update(name=name, params=params)
            return self
        def execute(self):
            return type("Response", (), {"data": ["north", "north"]})()
    monkeypatch.setattr(auth_service.supabase_client, "get_client", Client)
    assert auth_service._akia_portal_grants("user-1") == ["north"]
    assert captured == {"name": "akia_portal_grants", "params": {"p_user_id": "user-1"}}
