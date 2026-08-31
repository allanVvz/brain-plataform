from routes import conversations


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
        ) or {"ok": True},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"persona_id": "persona-1", "ai_paused": True},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "insert_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        conversations.conversation_runtime,
        "emit_turn_event",
        lambda **kwargs: None,
    )
    body = conversations.TechnicalFailureRequest(
        lead_ref=42,
        buffer_id="44444444-4444-4444-8444-444444444444",
        reason="graph unavailable",
        correlation_id="correlation-1",
    )

    result = conversations.technical_failure(body, "internal-token")

    assert calls == [
        "internal-token",
        ("44444444-4444-4444-8444-444444444444", 42, "graph unavailable"),
    ]
    assert result["technical_failure"] is True
    assert result["ai_paused"] is True
