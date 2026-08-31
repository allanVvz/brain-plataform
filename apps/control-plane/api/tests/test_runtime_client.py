from __future__ import annotations

from services import runtime_client


class _Response:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"ok": True}


class _Client:
    def __init__(self, captured: dict, **kwargs):
        captured["client"] = kwargs
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, **kwargs):
        self.captured.update({"url": url, **kwargs})
        return _Response()


def test_journey_state_is_sent_to_versioned_runtime_endpoint(monkeypatch):
    monkeypatch.setenv("BRAIN_RUNTIME_URL", "https://runtime.internal/")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "secret-token")
    captured = {}
    monkeypatch.setattr(
        runtime_client.httpx,
        "Client",
        lambda **kwargs: _Client(captured, **kwargs),
    )

    result = runtime_client.set_journey_state(
        42,
        {"target": "vendido"},
        actor_user_id="user-7",
        offering="sales",
    )

    assert result == {"ok": True}
    assert captured["url"] == "https://runtime.internal/internal/v1/agents/leads/42/journey-state"
    assert captured["headers"] == {
        "X-Webhook-Token": "secret-token",
        "X-Brain-Actor-Id": "user-7",
    }
    assert captured["params"] == {"offering": "sales"}


def test_resume_is_sent_once_to_runtime_with_actor(monkeypatch):
    monkeypatch.setenv("BRAIN_RUNTIME_URL", "https://runtime.internal")
    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "secret-token")
    captured = {}
    monkeypatch.setattr(
        runtime_client.httpx,
        "Client",
        lambda **kwargs: _Client(captured, **kwargs),
    )

    runtime_client.lead_action(42, "resume", actor_user_id="user-7")

    assert captured["url"] == "https://runtime.internal/internal/v1/runtime/leads/42/resume"
    assert captured["json"] == {}
    assert captured["headers"]["X-Brain-Actor-Id"] == "user-7"
