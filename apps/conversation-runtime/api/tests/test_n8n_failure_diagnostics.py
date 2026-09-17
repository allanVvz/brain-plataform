from brain_contracts import TechnicalConversationFailureV1
from routes import conversations


def test_fail_safe_persists_structured_n8n_node_diagnostic(monkeypatch):
    events = []
    handoffs = []
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "token")
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "get_lead_by_ref",
        lambda _lead_ref: {"id": 41, "persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "handoff_whatsapp_lead",
        handoffs.append,
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "insert_event",
        lambda data, **kwargs: events.append((data, kwargs)) or {"id": "event-1"},
    )
    monkeypatch.setattr(
        conversations.conversation_runtime.supabase_client,
        "list_system_events",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        conversations.transport_client,
        "quarantine_inbound_technical_failure",
        lambda *args: {"ok": True, "status": "dead_letter", "deduplicated": False},
    )

    result = conversations.technical_failure(
        TechnicalConversationFailureV1(
            lead_ref=41,
            buffer_id="44444444-4444-4444-8444-444444444444",
            correlation_id="meta:test",
            stage="DeepSeek agentic reply",
            reason="workflow_step_failed:DeepSeek agentic reply:invalid syntax",
            diagnostic={
                "failed_node": "DeepSeek agentic reply",
                "message": "invalid syntax",
                "http_code": 400,
                "workflow_template": "graph_agentic_v1",
            },
        ),
        x_webhook_token="token",
    )

    assert result["status"] == "technical_failure_unconfirmed"
    assert result["handoff"] is False
    assert handoffs == []
    assert [event[0]["event_type"] for event in events] == [
        "conversation.failure_observed",
        "conversation.technical_failure",
    ]
    assert events[1][0]["payload"]["diagnostic"]["failed_node"] == "DeepSeek agentic reply"
    assert events[1][0]["payload"]["diagnostic"]["http_code"] == 400
