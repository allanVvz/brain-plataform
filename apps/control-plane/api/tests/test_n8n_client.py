import httpx
import pytest

from services import conversation_workflow_service, n8n_client


def test_workflow_payload_strips_internal_node_metadata_without_mutation():
    workflow = {
        "name": "Conversation",
        "nodes": [
            {
                "id": "model",
                "meta": {
                    "credential_binding": "conversation_model",
                    "model_call_stage": "reply",
                },
                "credentials": {"httpHeaderAuth": {"id": "credential-id"}},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
        "meta": {"template": "graph_agentic_v3"},
    }

    payload = n8n_client.workflow_payload(workflow)

    assert "meta" not in payload
    assert "meta" not in payload["nodes"][0]
    assert workflow["nodes"][0]["meta"]["model_call_stage"] == "reply"
    assert payload["nodes"][0]["credentials"] == workflow["nodes"][0]["credentials"]


def test_raise_for_status_includes_only_n8n_validation_message():
    request = httpx.Request("PUT", "https://n8n.invalid/api/v1/workflows/1")
    response = httpx.Response(
        400,
        request=request,
        json={
            "message": "request/body/nodes/0 must NOT have additional properties",
            "payload": {"secret": "must-not-leak"},
        },
    )

    with pytest.raises(httpx.HTTPStatusError) as raised:
        n8n_client._raise_for_status(response)

    rendered = str(raised.value)
    assert "must NOT have additional properties" in rendered
    assert "must-not-leak" not in rendered


def test_workflow_checksum_matches_the_deployable_n8n_payload():
    canonical = {
        "name": "Conversation",
        "nodes": [{"id": "model", "meta": {"model_call_stage": "reply"}}],
        "connections": {},
        "settings": {},
    }
    live = n8n_client.workflow_payload(canonical)

    assert conversation_workflow_service._workflow_checksum(canonical) == (
        conversation_workflow_service._workflow_checksum(live)
    )


def test_workflow_checksum_ignores_n8n_credential_label_but_not_identity():
    canonical = {
        "name": "Conversation",
        "nodes": [
            {
                "id": "model",
                "credentials": {
                    "httpHeaderAuth": {
                        "id": "credential-id",
                        "name": "Published label",
                    }
                },
            }
        ],
        "connections": {},
        "settings": {},
    }
    normalized_by_n8n = {
        **canonical,
        "nodes": [
            {
                **canonical["nodes"][0],
                "credentials": {
                    "httpHeaderAuth": {
                        "id": "credential-id",
                        "name": "Stored n8n label",
                    }
                },
            }
        ],
    }
    wrong_credential = {
        **normalized_by_n8n,
        "nodes": [
            {
                **normalized_by_n8n["nodes"][0],
                "credentials": {
                    "httpHeaderAuth": {
                        "id": "different-credential-id",
                        "name": "Stored n8n label",
                    }
                },
            }
        ],
    }

    expected = conversation_workflow_service._workflow_checksum(canonical)
    assert conversation_workflow_service._workflow_checksum(normalized_by_n8n) == expected
    assert conversation_workflow_service._workflow_checksum(wrong_credential) != expected
