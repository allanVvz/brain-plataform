from services import release_queue_service


class _Result:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, args):
        self.calls.append((name, args))
        return _Result({"items": [{"id": "queued"}], "next_offset": 50})


def test_actionable_queue_delegates_global_projection_and_pagination_to_database(monkeypatch):
    client = _Client()
    monkeypatch.setattr(release_queue_service.supabase_client, "get_client", lambda: client)

    result = release_queue_service.list_unified_queue(
        persona_ids=["00000000-0000-0000-0000-000000000001"],
        origin="conversation", status="pending", offset=0, limit=50,
    )

    assert result == {"items": [{"id": "queued"}], "next_offset": 50}
    assert client.calls == [(
        "list_actionable_message_queue_v1",
        {
            "p_persona_ids": ["00000000-0000-0000-0000-000000000001"],
            "p_origin": "conversation", "p_status": "pending",
            "p_offset": 0, "p_limit": 50,
        },
    )]


def test_actionable_queue_returns_empty_without_bypassing_an_empty_persona_scope(monkeypatch):
    monkeypatch.setattr(
        release_queue_service.supabase_client, "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be called")),
    )

    assert release_queue_service.list_unified_queue(persona_ids=[]) == {
        "items": [], "next_offset": None,
    }
