from brain_contracts import TechnicalConversationFailureV1
from routes import conversations


def test_success_event_resets_consecutive_failure_streak(monkeypatch):
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "list_system_events",
        lambda **_kwargs: [
            {"event_type": "conversation.failure_observed", "payload": {"inbound_buffer_id": "new"}},
            {"event_type": "conversation.decision_committed", "payload": {"inbound_buffer_id": "ok"}},
            {"event_type": "conversation.failure_observed", "payload": {"inbound_buffer_id": "old"}},
        ],
    )
    assert conversations.conversation_runtime.consecutive_conversation_failures(42) == 1


def test_duplicate_failure_event_counts_once(monkeypatch):
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "list_system_events",
        lambda **_kwargs: [
            {"event_type": "conversation.failure_observed", "payload": {"inbound_buffer_id": "same"}},
            {"event_type": "conversation.failure_observed", "payload": {"inbound_buffer_id": "same"}},
        ],
    )
    assert conversations.conversation_runtime.consecutive_conversation_failures(42) == 1


def test_technical_failure_uses_transport_owned_buffer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conversations.internal_auth, "authorize_webhook_token", calls.append
    )
    monkeypatch.setattr(
        conversations.transport_client,
        "quarantine_inbound_technical_failure",
        lambda buffer_id, lead_ref, error: calls.append(
            (buffer_id, lead_ref, error)
        ) or {"ok": True, "status": "dead_letter", "deduplicated": False},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"persona_id": "persona-1", "ai_paused": True},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "insert_event",
        lambda *args, **kwargs: {"id": "event-1"},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "list_system_events",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "handoff_whatsapp_lead",
        lambda lead_ref: calls.append(("handoff", lead_ref)),
    )
    monkeypatch.setattr(
        conversations.conversation_runtime,
        "emit_turn_event",
        lambda **kwargs: None,
    )
    body = TechnicalConversationFailureV1(
        lead_ref=42,
        buffer_id="44444444-4444-4444-8444-444444444444",
        reason="graph unavailable",
        correlation_id="correlation-1",
        stage="graph_context",
    )

    result = conversations.technical_failure(body, "internal-token")

    assert calls == [
        "internal-token",
        ("44444444-4444-4444-8444-444444444444", 42, "graph unavailable"),
    ]
    assert result["technical_failure"] is True
    assert result["status"] == "technical_failure_unconfirmed"
    assert result["ai_paused"] is False
    assert result["handoff"] is False


def test_second_consecutive_failure_handoffs_and_duplicate_reuses_events(monkeypatch):
    inserted = []
    prior = {
        "id": "prior-failure", "event_type": "conversation.failure_observed",
        "payload": {"inbound_buffer_id": "prior-inbound"},
    }
    current = {
        "id": "current-failure", "event_type": "conversation.failure_observed",
        "payload": {"inbound_buffer_id": "44444444-4444-4444-8444-444444444444"},
    }
    monkeypatch.setattr(
        conversations.transport_client,
        "quarantine_inbound_technical_failure",
        lambda *args: {"status": "dead_letter", "deduplicated": True},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "handoff_whatsapp_lead",
        lambda _lead_ref: None,
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "list_system_events",
        lambda **kwargs: (
            [current, prior]
            if kwargs.get("entity_type") == "lead"
            else [{"id": "existing-event"}]
        ),
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "insert_event",
        lambda *args, **kwargs: inserted.append(args),
    )
    monkeypatch.setattr(
        conversations.conversation_runtime,
        "emit_turn_event",
        lambda **kwargs: None,
    )
    result = conversations._terminalize_technical_failure(
        TechnicalConversationFailureV1(
            lead_ref=42,
            buffer_id="44444444-4444-4444-8444-444444444444",
            reason="invalid_json",
            correlation_id="correlation-1",
            stage="reply_model",
        )
    )
    assert result["status"] == "technical_handoff"
    assert result["handoff"] is True
    assert result["ai_paused"] is True
    assert result["terminalization_status"] == "dead_letter"
    assert inserted == []
