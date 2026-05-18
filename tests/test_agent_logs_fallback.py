import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402


class _FakeInsert:
    def __init__(self, payload):
        self.payload = payload


class _FakeTable:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    def insert(self, payload):
        self.calls.append(payload)
        return _FakeInsert(payload)


class _FakeClient:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    def table(self, name: str):
        assert name == "agent_logs"
        return _FakeTable(self.calls)


def test_insert_agent_log_falls_back_to_legacy_when_modern_insert_fails(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(supabase_client, "_detect_agent_logs_schema_mode", lambda: "modern")
    monkeypatch.setattr(supabase_client, "get_client", lambda: _FakeClient(calls))

    def fake_execute(query):
        if "agent_type" in query.payload:
            raise RuntimeError("null value in column \"status\" violates not-null constraint")
        return object()

    monkeypatch.setattr(supabase_client, "_execute_with_retry", fake_execute)

    supabase_client.insert_agent_log({
        "agent_type": "HealthCheckWorker",
        "action": "[INFO] health ok",
        "decision": "healthy",
        "metadata": {"level": "INFO", "component": "HealthCheckWorker"},
    })

    assert len(calls) == 2
    assert calls[0]["agent_type"] == "HealthCheckWorker"
    assert calls[1]["agent_name"] == "HealthCheckWorker"
    assert calls[1]["status"] == "success"


def test_insert_agent_log_raises_when_both_shapes_fail(monkeypatch):
    monkeypatch.setattr(supabase_client, "_detect_agent_logs_schema_mode", lambda: "modern")
    monkeypatch.setattr(supabase_client, "get_client", lambda: _FakeClient([]))
    monkeypatch.setattr(
        supabase_client,
        "_execute_with_retry",
        lambda query: (_ for _ in ()).throw(RuntimeError("still broken")),
    )

    with pytest.raises(RuntimeError, match="still broken"):
        supabase_client.insert_agent_log({"agent_type": "FlowValidatorWorker"})
