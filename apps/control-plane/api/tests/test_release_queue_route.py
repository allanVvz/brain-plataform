from types import SimpleNamespace

from routes import release_queue


class _Request:
    state = SimpleNamespace(user={"role": "admin", "account_type": "internal"})


def test_queue_route_applies_selected_persona_before_database_paging(monkeypatch):
    calls = {}

    monkeypatch.setattr(release_queue.auth_service, "current_user", lambda _request: _Request.state.user)
    monkeypatch.setattr(release_queue.auth_service, "is_admin", lambda _user: True)

    def assert_scope(_request, capability, *, persona_id=None, persona_slug=None):
        calls["auth"] = (capability, persona_id, persona_slug)
        return {}

    monkeypatch.setattr(release_queue.auth_service, "assert_persona_capability", assert_scope)

    def list_queue(**kwargs):
        calls["queue"] = kwargs
        return {"items": [], "next_offset": None}

    monkeypatch.setattr(release_queue.release_queue_service, "list_unified_queue", list_queue)

    result = release_queue.list_queue(
        _Request(), origin=None, status=None, persona_id="persona-allan",
        offset=0, limit=50,
    )

    assert result == {"items": [], "next_offset": None}
    assert calls["auth"] == ("view", "persona-allan", None)
    assert calls["queue"] == {
        "persona_ids": ["persona-allan"],
        "origin": None,
        "status": None,
        "offset": 0,
        "limit": 50,
    }


def test_explicit_operator_preview_is_persona_scoped_and_uses_selected_inbound(monkeypatch):
    calls = {}
    class _Query:
        def select(self, *_args): return self
        def in_(self, *_args): return self
    class _Client:
        def table(self, *_args): return _Query()
    monkeypatch.setattr(release_queue.auth_service, "current_user", lambda _request: _Request.state.user)
    monkeypatch.setattr(
        release_queue.auth_service, "assert_persona_capability",
        lambda _request, capability, *, persona_id=None, persona_slug=None: calls.setdefault("scope", (capability, persona_id)),
    )
    monkeypatch.setattr(release_queue.release_queue_service, "_rows", lambda _query: [{
        "id": "inbound-1", "persona_id": "persona-1",
    }])
    monkeypatch.setattr(release_queue.release_queue_service.supabase_client, "get_client", lambda: _Client())
    monkeypatch.setattr(
        release_queue.release_queue_service, "generate_operator_queue_previews",
        lambda **kwargs: calls.setdefault("generate", kwargs) or {"items": []},
    )

    result = release_queue._queue_action(
        "operator_preview", release_queue.QueueActionBody(buffer_ids=["inbound-1"]), _Request(),
    )

    assert calls["scope"] == ("edit", "persona-1")
    assert calls["generate"] == {"buffer_ids": ["inbound-1"], "actor_user_id": None}
    assert result == calls["generate"]
