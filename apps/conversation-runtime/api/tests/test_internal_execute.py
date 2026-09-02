from __future__ import annotations

from routes import conversations


def test_execute_delegates_canonical_inbound_and_returns_small_envelope(monkeypatch):
    monkeypatch.setattr(
        conversations.internal_auth,
        "authorize_webhook_token",
        lambda token: None,
    )
    captured = {}

    def fake_execute(**payload):
        captured.update(payload)
        return {
            "ok": True,
            "handoff": False,
            "message_id": "message-1",
            "classifier": "qualification",
            "knowledge_context": {"must_not_cross": True},
        }

    monkeypatch.setattr(
        conversations.conversation_runtime,
        "execute_deterministic_pipeline",
        fake_execute,
    )
    body = conversations.ExecuteRequest(
        persona_slug="persona",
        lead_ref=7,
        message="Quero agendar",
        message_id="wamid-1",
        correlation_id="correlation-1",
        phone_number_id="phone-1",
        channel_binding_id="binding-1",
        inbound_buffer_id="buffer-1",
    )

    result = conversations.execute(body, x_webhook_token="token")

    assert captured["inbound_buffer_id"] == "buffer-1"
    assert result["message_id"] == "message-1"
    assert result["classifier"] == "qualification"
    assert "knowledge_context" not in result
