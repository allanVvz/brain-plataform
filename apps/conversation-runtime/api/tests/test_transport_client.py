from __future__ import annotations

from services import transport_client


class _Response:
    status_code = 200

    def json(self):
        return {"buffer_id": "buffer-1"}


class _Client:
    def __init__(self, calls, **kwargs):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


def test_runtime_uses_authenticated_transport_boundary(monkeypatch):
    calls = []
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "https://transport.internal")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    monkeypatch.setattr(
        transport_client.httpx,
        "Client",
        lambda **kwargs: _Client(calls, **kwargs),
    )

    result = transport_client.prepare_outbound(lead={"id": 42}, text="ok")

    assert result == {"buffer_id": "buffer-1"}
    assert calls[0][0].endswith("/internal/v1/transport/messages/prepare-outbound")
    assert calls[0][1]["headers"] == {"X-Webhook-Token": "internal-token"}


def test_runtime_uses_canonical_contract_for_validator_inbound(monkeypatch):
    calls = []
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "https://transport.internal")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    monkeypatch.setattr(
        transport_client.httpx,
        "Client",
        lambda **kwargs: _Client(calls, **kwargs),
    )

    result = transport_client.enqueue_validator_inbound(
        inbound_id="validator:33333333-3333-4333-8333-333333333333:2",
        correlation_id="validator:33333333-3333-4333-8333-333333333333:2",
        persona_id="11111111-1111-4111-8111-111111111111",
        persona_slug="fixture-persona",
        lead_ref="42",
        channel_binding_id="22222222-2222-4222-8222-222222222222",
        provider="internal_validator",
        received_at="2026-08-29T20:00:00+00:00",
        message_type="text",
        content={"text": "mensagem sintetica"},
    )

    assert result == {"buffer_id": "buffer-1"}
    assert calls[0][0].endswith("/internal/v1/transport/messages/validator-inbound")
    assert calls[0][1]["json"]["contract_version"] == "3"
    assert calls[0][1]["json"]["canonical_inbound_id"] == calls[0][1]["json"]["inbound_id"]
    assert calls[0][1]["json"]["provider"] == "internal_validator"


def test_runtime_completes_validator_inbound_through_transport(monkeypatch):
    calls = []
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "https://transport.internal")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    monkeypatch.setattr(
        transport_client.httpx,
        "Client",
        lambda **kwargs: _Client(calls, **kwargs),
    )

    transport_client.complete_validator_inbound(
        "33333333-3333-4333-8333-333333333333", 2
    )

    assert calls[0][0].endswith(
        "/internal/v1/transport/messages/validator-inbound/"
        "33333333-3333-4333-8333-333333333333/2/complete"
    )


def test_runtime_quarantines_failed_inbound_through_transport(monkeypatch):
    calls = []
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "https://transport.internal")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "internal-token")
    monkeypatch.setattr(
        transport_client.httpx,
        "Client",
        lambda **kwargs: _Client(calls, **kwargs),
    )

    transport_client.quarantine_inbound_technical_failure(
        "44444444-4444-4444-8444-444444444444", 42, "graph unavailable"
    )

    assert calls[0][0].endswith(
        "/internal/v1/transport/messages/inbound/"
        "44444444-4444-4444-8444-444444444444/technical-failure"
    )
    assert calls[0][1]["json"] == {"lead_ref": 42, "error": "graph unavailable"}
