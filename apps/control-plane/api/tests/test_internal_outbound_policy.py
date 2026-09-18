from routes import internal_outbound_policy


def test_outbound_policy_reads_active_document_without_context_projection(monkeypatch):
    monkeypatch.setattr(internal_outbound_policy.internal_auth, "authorize_webhook_token", lambda _token: None)
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_persona_by_id", lambda _id: {"slug": "tock-fatal"})
    monkeypatch.setattr(
        internal_outbound_policy.supabase_client,
        "get_active_graph_publication",
        lambda _id: {
            "version": 38,
            "checksum": "sha256:published",
            "document_json": {"nodes": [{
                "node_type": "persona",
                "data": {"conversation_policy": {"business_hours": {
                    "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
                }}},
            }]},
        },
    )

    result = internal_outbound_policy.published_outbound_policy("persona", "token")

    assert result["published_business_hours"] == {
        "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
        "graph_version": 38, "graph_checksum": "sha256:published",
    }


def test_outbound_policy_accepts_the_canonical_graph_type_shape(monkeypatch):
    monkeypatch.setattr(internal_outbound_policy.internal_auth, "authorize_webhook_token", lambda _token: None)
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_persona_by_id", lambda _id: {"slug": "tock-fatal"})
    monkeypatch.setattr(
        internal_outbound_policy.supabase_client,
        "get_active_graph_publication",
        lambda _id: {
            "version": 39, "checksum": "sha256:published-type",
            "document_json": {"nodes": [{
                "type": "Persona",
                "metadata": {"conversation_policy": {"business_hours": {
                    "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
                }}},
            }]},
        },
    )

    assert internal_outbound_policy.published_outbound_policy("persona", "token")[
        "published_business_hours"
    ]["graph_checksum"] == "sha256:published-type"
