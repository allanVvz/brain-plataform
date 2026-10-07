"""Connection cards for the client settings page: public fields only."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from routes import portal
from services import auth_service

META_ID = "11111111-aaaa-4aaa-8aaa-111111111111"
EVO_ID = "22222222-bbbb-4bbb-8bbb-222222222222"
SECRETS = ("ciphertext-meta", "ciphertext-evolution", "webhook-secret-value", "api-token-value")


def _bindings(meta_active=True):
    return [
        {
            "id": META_ID, "persona_id": "persona-1", "channel": "whatsapp",
            "provider": "meta_cloud", "active": meta_active,
            "connection_status": "connected", "whatsapp_phone_number_id": "1274565599076808",
            "whatsapp_number": "+5511900000000",
            "provider_secret_ciphertext": SECRETS[0],
            "metadata": {"waba_id": "1846969632685202", "verified_name": "Tock Fatal",
                         "chatwoot": {"enabled": True, "account_id": 1, "inbox_id": 1,
                                      "login_email": "atendimento@example.test",
                                      "webhook_secret": SECRETS[2], "api_token": SECRETS[3]}},
        },
        {
            "id": EVO_ID, "persona_id": "persona-1", "channel": "whatsapp",
            "provider": "evolution_baileys", "active": not meta_active,
            "connection_status": "connecting", "provider_instance_key": "instance-demo",
            "provider_secret_ciphertext": SECRETS[1], "metadata": {},
        },
    ]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CHATWOOT_BASE_URL", "https://chat.example.test/")
    monkeypatch.delenv("CHATWOOT_BRIDGE_BINDING_ID", raising=False)


@pytest.fixture
def fake(monkeypatch):
    state = {"bindings": _bindings(), "capabilities": {"manage"}, "admin": False, "actions": []}
    monkeypatch.setattr(
        portal.supabase_client, "get_persona",
        lambda slug: {"id": "persona-1", "slug": slug} if slug == "tock-fatal" else None,
    )
    monkeypatch.setattr(portal.supabase_client, "get_workflow_bindings", lambda _pid: state["bindings"])

    def capability(_request, capability, **_kwargs):
        if capability != "view" and capability not in state["capabilities"]:
            raise HTTPException(403, "sem permissao")

    monkeypatch.setattr(auth_service, "assert_persona_capability", capability)
    monkeypatch.setattr(auth_service, "current_user", lambda _request: {"id": "user-1"})
    monkeypatch.setattr(auth_service, "is_admin", lambda _user: state["admin"])
    monkeypatch.setattr(
        portal.transport_client, "evolution_action",
        lambda binding_id, action, **_kw: state["actions"].append((binding_id, action)) or {
            "status": "connecting", "qr": {"base64": "data:image/png;base64,AAAA"},
        },
    )
    monkeypatch.setattr(portal, "_evolution_webhook_target", lambda *_a: ("https://hook.test", "cb"))
    return state


def test_channels_returns_three_cards_without_any_secret(fake):
    result = portal.persona_channels(request=None, persona_slug="tock-fatal")

    assert result["active_provider"] == "meta_cloud"
    assert result["meta_cloud"] == {
        "configured": True, "active": True, "status": "connected",
        "phone_number_id": "1274565599076808", "whatsapp_number": "+5511900000000",
        "waba_id": "1846969632685202", "verified_name": "Tock Fatal", "token_configured": True,
    }
    assert result["evolution"]["configured"] is True
    assert result["evolution"]["active"] is False
    assert result["evolution"]["instance_key"] == "instance-demo"
    assert result["chatwoot"]["base_url"] == "https://chat.example.test"
    assert result["chatwoot"]["login_email"] == "atendimento@example.test"
    serialized = json.dumps(result)
    for secret in SECRETS:
        assert secret not in serialized


def test_channels_for_persona_without_bindings_still_lists_cards(fake):
    fake["bindings"] = []
    result = portal.persona_channels(request=None, persona_slug="tock-fatal")

    assert result["active_provider"] is None
    assert result["evolution"]["configured"] is False
    assert result["meta_cloud"]["configured"] is False
    assert result["meta_cloud"]["token_configured"] is False
    assert result["chatwoot"] == {"configured": False, "enabled": False}


def test_view_only_user_sees_cards_but_cannot_manage(fake):
    fake["capabilities"] = set()
    result = portal.persona_channels(request=None, persona_slug="tock-fatal")
    assert result["can_manage"] is False
    assert result["can_manage_provider"] is False


def test_qr_requires_manage_and_targets_evolution_even_when_meta_is_active(fake):
    fake["capabilities"] = set()
    with pytest.raises(HTTPException) as denied:
        portal.persona_evolution_qr(request=None, persona_slug="tock-fatal")
    assert denied.value.status_code == 403
    assert fake["actions"] == []

    fake["capabilities"] = {"manage"}
    response = portal.persona_evolution_qr(request=None, persona_slug="tock-fatal")
    assert fake["actions"] == [(EVO_ID, "get_qr_code")]
    assert response.headers["cache-control"] == "no-store"


def test_qr_without_evolution_binding_is_404(fake):
    fake["bindings"] = _bindings()[:1]
    with pytest.raises(HTTPException) as missing:
        portal.persona_evolution_qr(request=None, persona_slug="tock-fatal")
    assert missing.value.status_code == 404


def test_global_chatwoot_env_applies_only_to_its_bridge_binding(fake, monkeypatch):
    fake["bindings"][0]["metadata"].pop("chatwoot")
    monkeypatch.setenv("CHATWOOT_BRIDGE_BINDING_ID", META_ID)
    monkeypatch.setenv("CHATWOOT_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_INBOX_ID", "1")
    monkeypatch.setenv("CHATWOOT_LOGIN_EMAIL", "contato@example.test")
    card = portal.persona_channels(request=None, persona_slug="tock-fatal")["chatwoot"]
    assert card["enabled"] is True and card["inbox_id"] == "1"
    assert card["login_email"] == "contato@example.test"

    monkeypatch.setenv("CHATWOOT_BRIDGE_BINDING_ID", "someone-else")
    assert portal.persona_channels(request=None, persona_slug="tock-fatal")["chatwoot"] == {
        "configured": False, "enabled": False,
    }


def test_business_hours_view_returns_only_the_public_fields(fake, monkeypatch):
    monkeypatch.setattr(
        portal.supabase_client, "get_persona",
        lambda slug: {"id": "persona-1", "slug": slug, "config": {"business_hours": {"end": "22:00"}}},
    )
    monkeypatch.setattr(portal.supabase_client, "get_active_graph_publication", lambda _id: {
        "document_json": {"nodes": [{"node_type": "persona", "data": {"conversation_policy": {"business_hours": {
            "enabled": True, "start": "08:00", "end": "20:00", "timezone": "America/Sao_Paulo",
            "rule_node_id": "rule:x"}}}}]},
    })
    assert portal.persona_business_hours(request=None, persona_slug="tock-fatal") == {
        "enabled": True, "start": "08:00", "end": "22:00",
        "timezone": "America/Sao_Paulo", "source": "agent",
    }
