"""Contract tests for the durable, persona-isolated WhatsApp runtime."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from fastapi import HTTPException
from routes import integrations, whatsapp
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker, _retry_delay


class RequestStub:
    def __init__(self, payload: dict):
        self.payload = payload
        self.raw = __import__("json").dumps(payload).encode()
        self.headers: dict[str, str] = {}

    async def body(self):
        return self.raw

    async def json(self):
        return self.payload


def test_meta_signature_is_required_when_app_secret_is_configured(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", "test-secret")
    body = b'{"ok":true}'
    valid = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    whatsapp._verify_signature(body, valid)
    with pytest.raises(HTTPException) as exc:
        whatsapp._verify_signature(body, "sha256=not-valid")
    assert exc.value.status_code == 401


def test_meta_signature_configuration_is_required_by_default(monkeypatch):
    monkeypatch.delenv("META_WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.delenv("META_WHATSAPP_ALLOW_UNSIGNED_LOCAL", raising=False)
    with pytest.raises(HTTPException) as exc:
        whatsapp._verify_signature(b"{}", None)
    assert exc.value.status_code == 503


def test_allowlist_normalizes_phone_format_and_rejects_other_senders():
    binding = {"metadata": {"mode": "test_allowlist", "allowlist": ["+55 (51) 98260-8510"]}}
    assert whatsapp._allowed(binding, "5551982608510") is True
    assert whatsapp._allowed(binding, "5551999990000") is False


def test_inbound_is_routed_only_by_business_phone_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("META_WHATSAPP_ALLOW_UNSIGNED_LOCAL", "true")
    binding = {
        "id": "binding-baita",
        "persona_id": "baita-id",
        "provider": "meta_cloud",
        "metadata": {
            "mode": "test_allowlist",
            "allowlist": ["5551982608510"],
        },
    }
    calls: list[dict] = []
    monkeypatch.setattr(whatsapp, "_binding", lambda phone: binding if phone == "business-baita" else None)
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "ensure_channel_lead",
        lambda **kwargs: {"id": 44, "persona_id": kwargs["persona_id"]},
    )
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "enqueue_whatsapp_envelope",
        lambda **item: calls.append(item)
        or {"buffer_id": "buffer-1", "deduplicated": False},
    )
    monkeypatch.setattr(whatsapp.supabase_client, "insert_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(whatsapp.event_emitter, "emit", lambda *args, **kwargs: None)
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "business-baita"},
        "contacts": [{"wa_id": "5551982608510", "profile": {"name": "Teste"}}],
        "messages": [{"id": "wamid-1", "from": "5551982608510", "type": "text", "text": {"body": "Oi"}}],
    }}]}]}
    result = asyncio.run(whatsapp.inbound(RequestStub(payload)))
    assert result == {"accepted": 1, "duplicate": 0, "ignored": 0}
    assert calls[0]["buffer"]["persona_id"] == "baita-id"
    assert calls[0]["buffer"]["channel_binding_id"] == "binding-baita"
    assert calls[0]["buffer"]["idempotency_key"] == (
        "inbound:meta_cloud:binding-baita:wamid-1"
    )


def test_inbound_duplicate_does_not_create_a_second_message(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("META_WHATSAPP_ALLOW_UNSIGNED_LOCAL", "true")
    binding = {
        "id": "binding-baita",
        "persona_id": "baita-id",
        "provider": "meta_cloud",
        "metadata": {"mode": "active"},
    }
    monkeypatch.setattr(whatsapp, "_binding", lambda _phone: binding)
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "ensure_channel_lead",
        lambda **_kwargs: {"id": 44},
    )
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "enqueue_whatsapp_envelope",
        lambda **_item: {"buffer_id": "buffer-1", "deduplicated": True},
    )
    payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "business-baita"}, "messages": [{"id": "wamid-1", "from": "5551982608510", "type": "text", "text": {"body": "Oi"}}]}}]}]}
    assert asyncio.run(whatsapp.inbound(RequestStub(payload))) == {"accepted": 0, "duplicate": 1, "ignored": 0}


def test_delivery_callback_routes_every_observation_through_binding(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("META_WHATSAPP_ALLOW_UNSIGNED_LOCAL", "true")
    updates: list[tuple] = []
    monkeypatch.setattr(
        whatsapp,
        "_binding",
        lambda phone: {"id": "binding-1"} if phone == "business-baita" else None,
    )
    monkeypatch.setattr(
        whatsapp.supabase_client,
        "update_whatsapp_delivery_by_binding",
        lambda *args: updates.append(args),
    )
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "business-baita"},
        "statuses": [
        {"id": "wamid-1", "status": "delivered"}, {"id": "wamid-2", "status": "unknown"},
    ]}}]}]}
    assert asyncio.run(whatsapp.status(RequestStub(payload))) == {"updated": 2}
    assert updates == [
        ("binding-1", "wamid-1", "delivered"),
        ("binding-1", "wamid-2", "unknown"),
    ]


def test_retry_backoff_and_dead_letter_are_bounded(monkeypatch):
    assert [_retry_delay(n) for n in (1, 2, 3, 20)] == [5, 10, 20, 300]
    released: list[dict] = []
    dead: list[dict] = []
    monkeypatch.setattr("workers.whatsapp_dispatch_worker.supabase_client.release_whatsapp_buffer", lambda *args, **kwargs: released.append({"args": args, **kwargs}))
    monkeypatch.setattr("workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer", lambda *args, **kwargs: dead.append({"args": args, **kwargs}))
    worker = WhatsAppDispatchWorker()
    worker._retry_or_dead_letter({"id": "a", "attempt_count": 2, "max_attempts": 3}, RuntimeError("temporary"))
    worker._retry_or_dead_letter({"id": "b", "attempt_count": 3, "max_attempts": 3}, RuntimeError("final"))
    assert released[0]["args"][:2] == ("a", "retry")
    assert released[0]["delay_seconds"] == 10
    assert dead[0]["args"][:2] == ("b", "dead_letter")


def test_binding_payload_never_serializes_secret_metadata():
    payload = integrations._public_binding({
        "id": "binding", "persona_id": "baita", "active": True,
        "whatsapp_phone_number_id": "business-id",
        "metadata": {"mode": "test_allowlist", "allowlist": ["5551"], "access_token": "must-not-leak", "webhook_url": "https://private"},
    })
    serialized = str(payload)
    assert "must-not-leak" not in serialized
    assert "https://private" not in serialized
    assert payload["metadata"]["mode"] == "test_allowlist"


def test_handoff_uses_the_atomic_database_operation():
    source = (ROOT / "api" / "routes" / "leads.py").read_text(encoding="utf-8")
    assert "supabase_client.handoff_whatsapp_lead(lead_ref)" in source
