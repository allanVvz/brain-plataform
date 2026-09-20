from fastapi import HTTPException
import pytest

from services import release_queue_service


class _Result:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _Query:
    """Minimal chainable stand-in for a Supabase query builder.

    Every filter/order/limit call is a no-op that returns self; the fixed
    `rows` payload is what `_rows()`/`_one()` ultimately sees. This mirrors
    the fake client already used in test_actionable_queue_service.py.
    """

    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, _name):
        def chain(*_args, **_kwargs):
            return self
        return chain

    def execute(self):
        return _Result(self._rows)


class _Client:
    def __init__(self, system_events_rows):
        self.system_events_rows = system_events_rows
        self.rpc_calls = []

    def table(self, name):
        assert name == "system_events"
        return _Query(self.system_events_rows)

    def rpc(self, name, args):
        self.rpc_calls.append((name, args))
        return _Result({"items": [{"buffer_id": args.get("p_buffer_ids", ["?"])[0], "result": "agendado"}]})


def test_with_idempotency_runs_once_without_a_key():
    calls = {"count": 0}

    def run():
        calls["count"] += 1
        return {"items": [{"result": "agendado"}]}

    result = release_queue_service.with_idempotency(
        action="send_preview", buffer_ids=["b1"], idempotency_key=None,
        persona_id="p1", run=run,
    )

    assert calls["count"] == 1
    assert result == {"items": [{"result": "agendado"}]}


def test_with_idempotency_replays_the_cached_response_for_a_repeated_key(monkeypatch):
    cached_response = {"items": [{"result": "agendado"}]}
    client = _Client(system_events_rows=[{"payload": {
        "key_signature": "send_preview:b1", "response": cached_response,
    }}])
    monkeypatch.setattr(release_queue_service.supabase_client, "get_client", lambda: client)
    inserted = []
    monkeypatch.setattr(
        release_queue_service.supabase_client, "insert_event",
        lambda data, **kwargs: inserted.append(data),
    )

    calls = {"count": 0}

    def run():
        calls["count"] += 1
        return {"items": [{"result": "should_not_run_twice"}]}

    result = release_queue_service.with_idempotency(
        action="send_preview", buffer_ids=["b1"], idempotency_key="operator-click-1",
        persona_id="p1", run=run,
    )

    assert result is cached_response
    assert calls["count"] == 0, "a cached hit must never re-run the action"
    assert inserted == [], "a cache hit must not write a second idempotency record"


def test_with_idempotency_rejects_key_reuse_for_a_different_action_or_target(monkeypatch):
    client = _Client(system_events_rows=[{"payload": {
        "key_signature": "send_preview:b1", "response": {"items": []},
    }}])
    monkeypatch.setattr(release_queue_service.supabase_client, "get_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        release_queue_service.with_idempotency(
            action="pause", buffer_ids=["b1"], idempotency_key="operator-click-1",
            persona_id="p1", run=lambda: {"items": []},
        )
    assert exc_info.value.status_code == 409


def test_with_idempotency_records_a_fresh_call_for_a_new_key(monkeypatch):
    client = _Client(system_events_rows=[])
    monkeypatch.setattr(release_queue_service.supabase_client, "get_client", lambda: client)
    inserted = []
    monkeypatch.setattr(
        release_queue_service.supabase_client, "insert_event",
        lambda data, **kwargs: inserted.append(data),
    )

    result = release_queue_service.with_idempotency(
        action="send_preview", buffer_ids=["b1"], idempotency_key="operator-click-2",
        persona_id="p1", run=lambda: {"items": [{"result": "agendado"}]},
    )

    assert result == {"items": [{"result": "agendado"}]}
    assert len(inserted) == 1
    assert inserted[0]["entity_type"] == "messaging_queue_idempotency"
    assert inserted[0]["entity_id"] == "operator-click-2"
    assert inserted[0]["payload"]["key_signature"] == "send_preview:b1"
    assert inserted[0]["payload"]["response"] == {"items": [{"result": "agendado"}]}
