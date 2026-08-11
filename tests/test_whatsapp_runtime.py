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


def test_decision_response_failure_reconciles_an_already_committed_turn(monkeypatch):
    events: list[tuple] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.reconcile_committed_graph_inbound",
        lambda *_args, **_kwargs: {
            "ok": True,
            "reconciled": True,
            "outbound_id": "outbound-1",
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *_args, **_kwargs: pytest.fail("committed inbound was paused"),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.record_whatsapp_safety_violation",
        lambda **_kwargs: pytest.fail("committed inbound raised a safety violation"),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    WhatsAppDispatchWorker()._retry_or_dead_letter(
        {
            "id": "inbound-1",
            "direction": "inbound",
            "persona_id": "persona-1",
            "lead_ref": 29,
            "correlation_id": "correlation-1",
            "attempt_count": 1,
            "max_attempts": 5,
            "_attempt_started": "decision",
        },
        RuntimeError("n8n response was truncated after commit"),
    )

    assert events[0][0][0] == "whatsapp.inbound_commit_reconciled"
    assert events[0][1]["payload"]["outbound_id"] == "outbound-1"


def test_ambiguous_decision_attempt_never_retries(monkeypatch):
    """After dispatch, timeout is ambiguous and cannot authorize replay."""
    waiting: list[tuple] = []
    violations: list[dict] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.release_whatsapp_buffer",
        lambda *_args, **_kwargs: pytest.fail("ambiguous decision was retried"),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.record_whatsapp_safety_violation",
        lambda **kwargs: violations.append(kwargs) or {},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: waiting.append((args, kwargs)),
    )

    WhatsAppDispatchWorker()._retry_or_dead_letter(
        {
            "id": "inbound-1",
            "direction": "inbound",
            "channel_binding_id": "binding-1",
            "lead_ref": 29,
            "attempt_count": 1,
            "max_attempts": 5,
            "_attempt_started": "decision",
        },
        RuntimeError("n8n conversation returned HTTP 409"),
    )

    assert violations[0]["level"] == "partial"
    assert waiting[0][0][:2] == ("inbound-1", "waiting_human")


def test_dispatch_cycle_parallelizes_leads_but_keeps_each_lead_fifo(monkeypatch):
    rows = [
        {"id": "a2", "lead_ref": 10, "batch_key": "p:10", "direction": "inbound", "created_at": "2"},
        {"id": "b1", "lead_ref": 11, "batch_key": "p:11", "direction": "inbound", "created_at": "1"},
        {"id": "a1", "lead_ref": 10, "batch_key": "p:10", "direction": "inbound", "created_at": "1"},
    ]
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.claim_whatsapp_buffer",
        lambda _worker_id: rows,
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        WhatsAppDispatchWorker, "_dispatch_inbound",
        lambda _self, row: dispatched.append(row["id"]),
    )
    executor_calls: list[dict] = []

    class FakeExecutor:
        def __init__(self, **kwargs):
            executor_calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, fn, groups):
            materialized = list(groups)
            executor_calls[0]["group_ids"] = [[row["id"] for row in group] for group in materialized]
            return [fn(group) for group in materialized]

    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.ThreadPoolExecutor", FakeExecutor,
    )
    worker = WhatsAppDispatchWorker()
    worker.concurrency = 4

    worker._run_cycle()

    assert executor_calls[0]["max_workers"] == 2
    assert ["a1", "a2"] in executor_calls[0]["group_ids"]
    assert ["b1"] in executor_calls[0]["group_ids"]
    assert dispatched.index("a1") < dispatched.index("a2")


def test_decision_attempt_escalates_with_partial_level_after_exhausting_retries(monkeypatch):
    """Once retries are exhausted, escalate without pausing sibling rows.

    level="partial" (migration 103) only quarantines this row to
    waiting_human; it leaves every other buffered inbound row for the same
    lead claimable, unlike the implicit level="full" this used to send.
    """
    waiting: list[tuple] = []
    violations: list[dict] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.record_whatsapp_safety_violation",
        lambda **kwargs: violations.append(kwargs) or {},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: waiting.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.release_whatsapp_buffer",
        lambda *_args, **_kwargs: pytest.fail("exhausted decision attempt was retried again"),
    )

    WhatsAppDispatchWorker()._retry_or_dead_letter(
        {
            "id": "inbound-1",
            "direction": "inbound",
            "channel_binding_id": "binding-1",
            "lead_ref": 29,
            "attempt_count": 5,
            "max_attempts": 5,
            "_attempt_started": "decision",
        },
        RuntimeError("n8n conversation returned HTTP 409"),
    )

    assert violations[0]["level"] == "partial"
    assert violations[0]["violation_key"] == "attempt-failed:decision:inbound-1"
    assert waiting[0][0][:2] == ("inbound-1", "waiting_human")


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
