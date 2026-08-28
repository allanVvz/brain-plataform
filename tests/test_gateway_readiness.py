import asyncio
import json

from api import gateway_main


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class _Client:
    responses = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        return self.responses[url]


def _configure(monkeypatch):
    monkeypatch.setenv("BRAIN_CONTROL_PLANE_URL", "http://router/control-plane")
    monkeypatch.setenv("BRAIN_RUNTIME_URL", "http://router/conversation-runtime")
    monkeypatch.setenv("BRAIN_TRANSPORT_URL", "http://router/transport")
    monkeypatch.setattr(gateway_main.httpx, "AsyncClient", _Client)


def test_gateway_ready_only_when_every_upstream_is_ready(monkeypatch):
    _configure(monkeypatch)
    _Client.responses = {
        f"http://router/{name}/health/ready": _Response(200, {
            "status": "ready", "source_sha": "a" * 40,
            "build_digest": "sha256:" + "b" * 64,
            "contracts_version": "1.0.0", "schema_version": 131,
        })
        for name in ("control-plane", "conversation-runtime", "transport")
    }
    response = asyncio.run(gateway_main.readiness())
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["ready"] is True
    assert all(item["ready"] for item in payload["dependencies"].values())


def test_gateway_readiness_fails_closed(monkeypatch):
    _configure(monkeypatch)
    _Client.responses = {
        "http://router/control-plane/health/ready": _Response(200, {"status": "ready"}),
        "http://router/conversation-runtime/health/ready": _Response(503, {"status": "not_ready"}),
        "http://router/transport/health/ready": _Response(200, {"status": "ready"}),
    }
    response = asyncio.run(gateway_main.readiness())
    payload = json.loads(response.body)
    assert response.status_code == 503
    assert payload["ready"] is False
    assert payload["dependencies"]["conversation-runtime"]["ready"] is False
