from routes import internal_outbound_policy
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import auth_middleware


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


def test_no_published_send_window_is_explicit_and_pinned(monkeypatch):
    monkeypatch.setattr(internal_outbound_policy.internal_auth, "authorize_webhook_token", lambda _token: None)
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_persona_by_id", lambda _id: {"slug": "appointment"})
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_active_graph_publication", lambda _id: {
        "version": 13, "checksum": "sha256:appointment",
        "document_json": {"nodes": [{"node_type": "persona", "data": {"appointment_policy": {}}}]},
    })

    assert internal_outbound_policy.published_outbound_policy("persona", "token") == {
        "published_business_hours": None,
        "graph_version": 13,
        "graph_checksum": "sha256:appointment",
    }


def test_outbound_policy_route_uses_service_token_without_operator_session(monkeypatch):
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-test-token")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_persona_by_id", lambda _id: {"slug": "sales"})
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_active_graph_publication", lambda _id: {
        "version": 38, "checksum": "sha256:sales",
        "document_json": {"nodes": [{"node_type": "persona", "data": {
            "conversation_policy": {"business_hours": {
                "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
            }},
        }}]},
    })
    app = FastAPI()
    app.middleware("http")(auth_middleware)
    app.include_router(internal_outbound_policy.router)
    path = "/internal/v1/control-plane/personas/71b364c4-9875-47c6-b66e-34ecde677922/outbound-policy"
    client = TestClient(app)

    assert client.get(path).status_code == 401
    response = client.get(path, headers={"X-Webhook-Token": "internal-test-token"})
    assert response.status_code == 200
    assert response.json()["published_business_hours"]["graph_checksum"] == "sha256:sales"
