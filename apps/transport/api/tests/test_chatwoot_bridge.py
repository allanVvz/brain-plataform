import hashlib
import hmac
import json
import time
import asyncio

import pytest
from fastapi import HTTPException

from routes import chatwoot
from services import chatwoot_api
from workers.chatwoot_bridge_worker import ChatwootBridgeWorker


def _signature(body: bytes, secret: str, timestamp: str) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _payload(**updates):
    payload = {
        "event": "message_created",
        "id": "9001",
        "content": "Olá, preciso de ajuda",
        "message_type": "outgoing",
        "private": False,
        "content_attributes": {},
        "sender": {"id": "17", "type": "user"},
        "account": {"id": "3"},
        "inbox": {"id": "8"},
        "conversation": {"id": "44", "display_id": "44"},
    }
    payload.update(updates)
    return payload


class _Request:
    def __init__(self, body: bytes):
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _deliver(body: bytes, secret: str, timestamp: str):
    return asyncio.run(chatwoot.receive_chatwoot_event(
        _Request(body), timestamp, _signature(body, secret, timestamp),
    ))


def test_chatwoot_webhook_authenticates_and_enqueues_one_human_reply(monkeypatch):
    secret = "bridge-webhook-test-secret"
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret=secret, agent_id=17,
    )
    monkeypatch.setattr(chatwoot_api, "configuration", lambda: config)
    monkeypatch.setattr(chatwoot.chatwoot_bridge, "get_conversation_by_chatwoot_id", lambda *args: {
        "channel_binding_id": "binding-1", "lead_ref": 51,
    })
    calls = []

    def enqueue_command(**kwargs):
        calls.append(kwargs)
        return {"status": "pending"}

    monkeypatch.setattr(chatwoot.chatwoot_bridge, "enqueue_command", enqueue_command)
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    response = _deliver(body, secret, timestamp)

    assert response == {"ok": True, "queued": True}
    assert calls == [{
        "source_id": "message:9001", "operation": "human_reply",
        "binding_id": "binding-1", "lead_ref": 51,
        "chatwoot_message_id": 9001, "conversation_id": 44,
    }]


def test_chatwoot_webhook_rejects_forgery_and_ignores_bridge_echo(monkeypatch):
    secret = "bridge-webhook-test-secret"
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret=secret, agent_id=17,
    )
    monkeypatch.setattr(chatwoot_api, "configuration", lambda: config)
    monkeypatch.setattr(chatwoot.chatwoot_bridge, "get_conversation_by_chatwoot_id", lambda *args: {
        "channel_binding_id": "binding-1", "lead_ref": 51,
    })
    calls = []
    monkeypatch.setattr(chatwoot.chatwoot_bridge, "enqueue_command", lambda **kwargs: calls.append(kwargs))
    timestamp = str(int(time.time()))
    forged_body = json.dumps(_payload(), separators=(",", ":")).encode()
    with pytest.raises(HTTPException) as forged:
        asyncio.run(chatwoot.receive_chatwoot_event(
            _Request(forged_body), timestamp, "sha256=" + "0" * 64,
        ))
    assert forged.value.status_code == 401

    echo_body = json.dumps(_payload(content_attributes={"brain_bridge_v1": True}), separators=(",", ":")).encode()
    echoed = _deliver(echo_body, secret, timestamp)
    assert echoed == {"ok": True, "ignored": True}
    assert calls == []


def test_private_notes_require_explicit_pause_or_resume_command(monkeypatch):
    secret = "bridge-webhook-test-secret"
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret=secret, agent_id=17,
    )
    monkeypatch.setattr(chatwoot_api, "configuration", lambda: config)
    monkeypatch.setattr(chatwoot.chatwoot_bridge, "get_conversation_by_chatwoot_id", lambda *args: {
        "channel_binding_id": "binding-1", "lead_ref": 51,
    })
    calls = []
    monkeypatch.setattr(chatwoot.chatwoot_bridge, "enqueue_command", lambda **kwargs: calls.append(kwargs) or {"status": "pending"})
    timestamp = str(int(time.time()))

    for message_id, command, operation in (
        (9002, "/assumir-ia", "pause_ai"),
        (9003, "/retomar-ia", "resume_ai"),
    ):
        body = json.dumps(_payload(id=str(message_id), content=command, private=True), separators=(",", ":")).encode()
        response = _deliver(body, secret, timestamp)
        assert response["ok"] is True
        assert calls[-1]["operation"] == operation

    assert len(calls) == 2


def test_human_reply_hands_off_before_using_transport_outbox(monkeypatch):
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret="not-used", agent_id=17,
    )
    mapping = {"conversation_id": 44, "contact_identifier": "contact-session"}
    calls = []

    class FakeApi:
        def get_message(self, **kwargs):
            calls.append(("read_message", kwargs["message_id"]))
            return {
                "id": 9004, "content": "Vou verificar para você", "private": False,
                "attachments": [], "sender": {"id": 17, "type": "user"},
            }

    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.chatwoot_bridge.get_conversation",
        lambda *args: mapping,
    )
    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.runtime_client.pause_ai",
        lambda lead_ref: calls.append(("pause_ai", lead_ref)) or {"ai_paused": True},
    )
    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.supabase_client.get_lead_by_ref",
        lambda lead_ref: {"id": lead_ref, "persona_id": "persona-1", "channel_binding_id": "binding-1"},
    )
    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.operator_messaging.enqueue",
        lambda **kwargs: calls.append(("enqueue", kwargs)) or {"buffer_id": "00000000-0000-0000-0000-000000000001"},
    )
    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.chatwoot_bridge.finish_operation",
        lambda *args, **kwargs: calls.append(("finish", args, kwargs)) or True,
    )
    worker = ChatwootBridgeWorker()
    worker._process_operation(FakeApi(), config, {
        "id": "op-1", "operation": "human_reply", "lead_ref": 51,
        "chatwoot_message_id": 9004, "chatwoot_conversation_id": 44,
        "attempt_count": 1,
    })

    assert calls[0] == ("read_message", 9004)
    assert calls[1] == ("pause_ai", 51)
    assert calls[2][0] == "enqueue"
    assert calls[2][1]["lead_ref"] == 51
    assert calls[2][1]["text"] == "Vou verificar para você"
    assert calls[2][1]["metadata"]["chatwoot_message_id"] == 9004
    assert calls[3][0] == "finish"
    assert calls[3][2]["transport_buffer_id"] == "00000000-0000-0000-0000-000000000001"


def test_projection_creates_missing_api_inbox_contact_session(monkeypatch):
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret="not-used", agent_id=17,
    )
    calls = []

    class FakeApi:
        def create_or_get_contact(self, **kwargs):
            calls.append(("contact", kwargs))
            return {"id": 61, "contact_inboxes": []}

        def create_contact_inbox(self, **kwargs):
            calls.append(("contact_inbox", kwargs))
            return {"source_id": kwargs["source_id"]}

        def get_contact(self, **kwargs):
            calls.append(("get_contact", kwargs))
            return {"contact_inboxes": [{"inbox_id": 8, "source_id": "session-61"}]}

        def list_conversations(self, **kwargs):
            calls.append(("list_conversations", kwargs))
            return []

        def create_conversation(self, **kwargs):
            calls.append(("create_conversation", kwargs))
            return {"id": 901}

        def assign_conversation(self, conversation_id):
            calls.append(("assign", conversation_id))
            return {}

    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.chatwoot_bridge.get_conversation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "workers.chatwoot_bridge_worker.chatwoot_bridge.save_conversation",
        lambda payload: payload | {"conversation_id": 901},
    )
    mapping = ChatwootBridgeWorker()._ensure_conversation(
        FakeApi(), config, 51,
        {"external_contact_id": "+5511999999999", "nome": "Contato"},
    )

    assert mapping["conversation_id"] == 901
    assert calls[1][0] == "contact_inbox"
    assert calls[1][1]["contact_id"] == 61
    assert calls[1][1]["source_id"] == "brain:binding-1:51"
    assert calls[2] == ("get_contact", {"contact_id": 61})
    assert calls[3][1]["contact_identifier"] == "session-61"


@pytest.mark.parametrize(
    ("incoming", "message_type"),
    [(True, "incoming"), (False, "outgoing")],
)
def test_brain_projection_uses_account_api_and_preserves_direction(incoming, message_type):
    config = chatwoot_api.ChatwootConfig(
        base_url="https://chat.example", api_token="not-used", account_id=3,
        inbox_id=8, inbox_identifier="inbox-test", binding_id="binding-1",
        webhook_secret="not-used", agent_id=17,
    )
    api = chatwoot_api.ChatwootApi(config)
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": 9005}

    class Client:
        @staticmethod
        def request(method, url, *, json=None, params=None):
            calls.append((method, url, json, params))
            return Response()

    api._client.close()
    api._client = Client()
    result = api.create_message(
        conversation_id=44, source_id="brain-message:812",
        content="Canonical text", incoming=incoming,
        external_created_at="2026-10-06T12:34:56Z",
        content_attributes={"brain_message_id": 812},
    )
    assert result["id"] == 9005
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://chat.example/api/v1/accounts/3/conversations/44/messages"
    assert calls[0][2]["message_type"] == message_type
    assert calls[0][2]["source_id"] == "brain-message:812"
    assert calls[0][2]["external_created_at"] == "2026-10-06T12:34:56Z"
    assert calls[0][2]["content_attributes"]["brain_bridge_v1"] is True
