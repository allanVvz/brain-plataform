"""Portal-side consent routes: thin wrappers around the same
supabase_client.list_contact_consents/insert_contact_consent the admin
`apps/conversation-runtime` leads routes use -- same DB table, same RPC,
only the auth/persona-scoping boundary differs (a client session can't
reach /leads/* at all, per the account_type=="client" middleware gate).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routes import portal
from services import auth_service


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch):
    monkeypatch.setattr(auth_service, "assert_persona_capability", lambda *_a, **_k: None)
    monkeypatch.setattr(auth_service, "current_user", lambda _request: {"id": "11111111-1111-1111-1111-111111111111"})


@pytest.fixture(autouse=True)
def _fake_persona(monkeypatch):
    monkeypatch.setattr(
        portal.supabase_client, "get_persona",
        lambda slug: {"id": "persona-1", "slug": slug} if slug == "vz-lupas" else None,
    )


@pytest.fixture(autouse=True)
def _fake_lead(monkeypatch):
    monkeypatch.setattr(
        portal.supabase_client, "get_lead_by_ref",
        lambda ref: {"id": ref, "persona_id": "persona-1"} if ref == 42 else None,
    )


def test_list_consents_delegates_with_persona_scope(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        portal.supabase_client, "list_contact_consents",
        lambda **kwargs: captured.update(kwargs) or [{"status": "granted"}],
    )

    result = portal.portal_lead_consents(42, request=None, persona_slug="vz-lupas", channel=None, purpose=None)

    assert result == [{"status": "granted"}]
    assert captured == {"lead_id": 42, "persona_id": "persona-1", "channel": None, "purpose": None}


def test_grant_consent_requires_purpose_idempotency_and_reason():
    body = portal.PortalConsentChangeBody(purpose="", idempotency_key="", reason="")
    with pytest.raises(HTTPException) as exc:
        portal.portal_grant_lead_consent(42, body, request=None, persona_slug="vz-lupas")
    assert exc.value.status_code == 422


def test_grant_consent_writes_granted_status(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        portal.supabase_client, "insert_contact_consent",
        lambda data, audit_payload=None: captured.update(data=data, audit_payload=audit_payload) or {"id": "c1"},
    )

    body = portal.PortalConsentChangeBody(
        purpose="ofertas_e_novidades", idempotency_key="key-1", reason="cliente pediu por telefone",
    )
    result = portal.portal_grant_lead_consent(42, body, request=None, persona_slug="vz-lupas")

    assert result == {"ok": True, "consent": {"id": "c1"}}
    assert captured["data"]["status"] == "granted"
    assert captured["data"]["granted_at"] is not None
    assert captured["data"]["revoked_at"] is None
    assert captured["data"]["persona_id"] == "persona-1"


def test_revoke_consent_writes_revoked_status(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        portal.supabase_client, "insert_contact_consent",
        lambda data, audit_payload=None: captured.update(data=data) or {"id": "c2"},
    )

    body = portal.PortalConsentChangeBody(
        purpose="ofertas_e_novidades", idempotency_key="key-2", reason="cliente pediu para parar",
    )
    portal.portal_revoke_lead_consent(42, body, request=None, persona_slug="vz-lupas")

    assert captured["data"]["status"] == "revoked"
    assert captured["data"]["revoked_at"] is not None
    assert captured["data"]["granted_at"] is None


def test_lead_from_another_persona_is_404():
    body = portal.PortalConsentChangeBody(purpose="p", idempotency_key="k", reason="r")
    with pytest.raises(HTTPException) as exc:
        portal.portal_grant_lead_consent(999, body, request=None, persona_slug="vz-lupas")
    assert exc.value.status_code == 404
