from types import SimpleNamespace

from services import agentic_turn, conversation_runtime


def _publication():
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "version": 38,
        "checksum": "sha256:published",
        "document_json": {
            "nodes": [
                {
                    "id": "persona:fixture", "node_type": "persona",
                    "data": {"conversation_policy": {"business_hours": {
                        "enabled": True, "timezone": "America/Sao_Paulo",
                        "start": "08:00", "end": "20:00",
                        "rule_node_id": "rule:hours",
                        "morning_reactivation_copy_node_id": "copy:reactivate",
                    }}},
                },
                {"id": "rule:hours", "node_type": "rule", "data": {}},
                {"id": "copy:reactivate", "node_type": "copy", "status": "validated",
                 "data": {"content": "Copy publicada."}},
            ]
        },
    }


def test_operator_reactivation_uses_only_active_published_copy_and_rule(monkeypatch):
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"})
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_lead_by_ref", lambda _lead: {"id": 42, "persona_id": "persona-1", "handoff_level": "none"})
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_active_graph_publication", lambda _persona: _publication())
    captured = {}
    monkeypatch.setattr(
        conversation_runtime.transport_client, "enqueue_reactivation_preview",
        lambda **payload: captured.update(payload) or {"buffer_id": "preview-1", "status": "preview_ready"},
    )

    result = conversation_runtime.create_reactivation_preview(
        persona_slug="fixture", lead_ref=42, source_buffer_id="source-1", actor_user_id="operator-1",
    )

    assert result["status"] == "preview_ready"
    assert captured["text"] == "Copy publicada."
    assert captured["evidence_node_ids"] == ["copy:reactivate", "rule:hours"]
    assert captured["idempotency_key"] == "proactive-reactivation:source-1"
    assert captured["metadata"]["published_business_hours"]["graph_checksum"] == "sha256:published"


def test_operator_reactivation_fails_closed_without_a_published_copy_node(monkeypatch):
    publication = _publication()
    publication["document_json"]["nodes"][0]["data"]["conversation_policy"]["business_hours"] = {
        "enabled": True, "rule_node_id": "rule:hours",
    }
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"})
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_lead_by_ref", lambda _lead: {"id": 42, "persona_id": "persona-1"})
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_active_graph_publication", lambda _persona: publication)

    try:
        conversation_runtime.create_reactivation_preview(
            persona_slug="fixture", lead_ref=42, source_buffer_id="source-1",
        )
    except RuntimeError as exc:
        assert "published reactivation copy is unavailable" in str(exc)
    else:
        raise AssertionError("missing published copy must fail closed")


def test_contextual_reactivation_pair_uses_read_only_agentic_reply(monkeypatch):
    publication = _publication()
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_persona", lambda _slug: {"id": "persona-1"})
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_lead_by_ref", lambda _lead: {
        "id": 42, "persona_id": "persona-1", "handoff_level": "none",
    })
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_active_graph_publication", lambda _persona: publication)
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_messages", lambda *_args, **_kwargs: [
        {"direction": "inbound", "content": "Mensagem recente"},
    ])
    captured_agentic = {}
    def fake_agentic(**kwargs):
        captured_agentic.update(kwargs)
        return {
        "context": SimpleNamespace(publication_id=publication["id"], graph_checksum=publication["checksum"]),
        "response": SimpleNamespace(
            reply_text="Resposta contextual gerada.",
            evidence_node_ids=["copy:reactivate"],
            proof={"valid": True, "delivery_authorized": True},
            handoff_required=False,
            proposal=SimpleNamespace(model_dump=lambda **_dump_kwargs: {"reply": "Resposta contextual gerada."}),
        ),
        "decision": SimpleNamespace(handoff_reason=None),
        }
    monkeypatch.setattr(agentic_turn, "execute", fake_agentic)
    captured = {}
    monkeypatch.setattr(
        conversation_runtime.transport_client, "enqueue_reactivation_pair",
        lambda **payload: captured.update(payload) or {"lines": [
            {"buffer_id": "preview-1", "line_kind": "apology"},
            {"buffer_id": "preview-2", "line_kind": "context"},
        ]},
    )

    result = conversation_runtime.create_reactivation_pair(
        persona_slug="fixture", lead_ref=42, source_buffer_id="source-1", regenerate=True,
    )

    assert result["latest_inbound_context"] == "Mensagem recente"
    assert [line["text"] for line in captured["lines"]] == ["Copy publicada.", "Resposta contextual gerada."]
    assert captured["regenerate"] is True
    assert captured_agentic["commit_result"] is False
    assert captured_agentic["preview_only"] is True
