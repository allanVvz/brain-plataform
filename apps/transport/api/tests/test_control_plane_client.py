import pytest

from services import control_plane_client


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Client:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, **_kwargs):
        assert "/internal/v1/control-plane/personas/" in url
        return self.response


def test_active_publication_without_send_hours_is_valid(monkeypatch):
    monkeypatch.setenv("BRAIN_CONTROL_PLANE_URL", "http://control-plane")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "token")
    payload = {"published_business_hours": None, "graph_checksum": "sha256:appointment"}
    monkeypatch.setattr(control_plane_client.httpx, "Client", lambda **_kwargs: _Client(_Response(payload)))

    assert control_plane_client.published_outbound_policy("persona") == payload


def test_missing_publication_proof_cannot_disable_send_hours(monkeypatch):
    monkeypatch.setenv("BRAIN_CONTROL_PLANE_URL", "http://control-plane")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "token")
    monkeypatch.setattr(control_plane_client.httpx, "Client", lambda **_kwargs: _Client(_Response({
        "published_business_hours": None,
    })))

    with pytest.raises(RuntimeError, match="unpinned outbound policy"):
        control_plane_client.published_outbound_policy("persona")
