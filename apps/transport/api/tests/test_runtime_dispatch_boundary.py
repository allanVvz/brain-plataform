from __future__ import annotations

from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker


def test_deterministic_inbound_delegates_without_burning_attempt(monkeypatch):
    row = {
        "id": "buffer-1",
        "persona_id": "persona-1",
        "lead_ref": 7,
        "payload": {"text": "Quero agendar"},
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "phone-1",
        "external_message_id": "wamid-1",
        "correlation_id": "correlation-1",
    }
    worker = WhatsAppDispatchWorker()
    calls: list[dict] = []

    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _persona_id: {"id": "persona-1", "slug": "persona"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _lead_ref: {"id": 7, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1",
            "active": True,
            "persona_id": "persona-1",
            "metadata": {"decision_owner": "deterministic"},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.mark_whatsapp_attempt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not own deterministic decision attempts")
        ),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.runtime_client.execute_inbound",
        lambda payload: calls.append(payload) or {"ok": True, "handoff": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )

    worker._dispatch_inbound(row)

    assert calls == [{
        "persona_slug": "persona",
        "lead_ref": 7,
        "message": "Quero agendar",
        "message_id": "wamid-1",
        "correlation_id": "correlation-1",
        "phone_number_id": "phone-1",
        "channel_binding_id": "binding-1",
        "inbound_buffer_id": "buffer-1",
    }]


def test_unavailable_runtime_releases_deterministic_inbound_for_retry(monkeypatch):
    worker = WhatsAppDispatchWorker()
    row = {
        "id": "buffer-2",
        "direction": "inbound",
        "attempt_count": 1,
        "max_attempts": 5,
    }
    releases: list[tuple] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.release_whatsapp_buffer",
        lambda *args, **kwargs: releases.append((args, kwargs)),
    )

    worker._retry_or_dead_letter(row, RuntimeError("runtime unavailable"))

    assert releases
    assert releases[0][0][1] == "retry"


def test_agentic_inbound_uses_runtime_and_never_n8n(monkeypatch):
    row = {
        "id": "buffer-agentic",
        "persona_id": "persona-1",
        "lead_ref": 9,
        "payload": {"text": "Uso proprio"},
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "phone-1",
        "external_message_id": "wamid-2",
        "correlation_id": "correlation-2",
    }
    worker = WhatsAppDispatchWorker()
    calls: list[dict] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _persona_id: {"id": "persona-1", "slug": "persona"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _lead_ref: {"id": 9, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1", "active": True, "persona_id": "persona-1",
            "provider": "meta_cloud",
            "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.runtime_client.execute_agentic_inbound",
        lambda payload: calls.append(payload) or {"ok": True, "handoff": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.n8n_client.send_to_webhook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("n8n must not execute agentic turns")
        ),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )

    worker._dispatch_inbound(row)

    assert len(calls) == 1
    assert calls[0]["inbound_buffer_id"] == "buffer-agentic"
    assert calls[0]["provider"] == "meta_cloud"
    assert calls[0]["publication_id"] is None


def test_internal_validator_uses_real_worker_while_binding_is_paused(monkeypatch):
    row = {
        "id": "buffer-validator",
        "persona_id": "persona-1",
        "lead_ref": 9,
        "payload": {
            "text": "Uso proprio",
            "sender": "wa-validator",
            "validation_transport": True,
            "publication_id": "publication-1",
        },
        "channel_binding_id": "binding-1",
        "external_message_id": "validator:session:0",
        "correlation_id": "validator:session:0",
    }
    worker = WhatsAppDispatchWorker()
    calls: list[dict] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _persona_id: {"id": "persona-1", "slug": "persona"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _lead_ref: {"id": 9, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1",
            "active": True,
            "persona_id": "persona-1",
            "provider": "meta_cloud",
            "connection_status": "safety_paused",
            "metadata": {"decision_owner": "n8n_agents", "safety_paused": True},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.runtime_client.execute_agentic_inbound",
        lambda payload: calls.append(payload) or {"ok": True, "handoff": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )

    worker._dispatch_inbound(row)

    assert len(calls) == 1
    assert calls[0]["provider"] == "internal_validator"
    assert calls[0]["publication_id"] == "publication-1"


def test_agentic_runtime_transport_failure_terminalizes_once_without_retry(monkeypatch):
    row = {
        "id": "buffer-failed",
        "persona_id": "persona-1",
        "lead_ref": 9,
        "payload": {"text": "Oi"},
        "channel_binding_id": "binding-1",
        "external_message_id": "wamid-failed",
        "correlation_id": "correlation-failed",
    }
    worker = WhatsAppDispatchWorker()
    terminalized: list[tuple] = []
    handoffs: list[int] = []
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _persona_id: {"id": "persona-1", "slug": "persona"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _lead_ref: {"id": 9, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1", "active": True, "persona_id": "persona-1",
            "provider": "meta_cloud", "metadata": {"decision_owner": "n8n_agents"},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.runtime_client.execute_agentic_inbound",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.terminalize_inbound_technical_failure",
        lambda *args, **kwargs: terminalized.append((args, kwargs)) or {"status": "dead_letter"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.handoff_whatsapp_lead",
        lambda lead_ref: handoffs.append(lead_ref),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )

    worker._dispatch_inbound(row)

    assert len(terminalized) == 1
    assert handoffs == [9]
