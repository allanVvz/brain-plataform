from services import transport_client


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {"ok": True, "deduplicated": False}


class _Client:
    def __init__(self, captured, **kwargs):
        captured["client"] = kwargs
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, **kwargs):
        self.captured.update({"url": url, **kwargs})
        return _Response()


def test_portal_message_targets_versioned_transport_endpoint(monkeypatch):
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "https://transport.internal/")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "secret-token")
    captured = {}
    monkeypatch.setattr(
        transport_client.httpx,
        "Client",
        lambda **kwargs: _Client(captured, **kwargs),
    )
    payload = {"persona_id": "p1", "lead_ref": 42, "client_message_id": "m1", "text": "Oi"}

    result = transport_client.send_portal_message(payload, actor_user_id="user-7")

    assert result["ok"] is True
    assert captured["url"] == "https://transport.internal/internal/v1/transport/messages/send"
    assert captured["json"] == payload
    assert captured["headers"]["X-Brain-Actor-Id"] == "user-7"
