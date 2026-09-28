from __future__ import annotations

import pytest

from services import release_queue_service as service


class Query:
    def __init__(self, table: str):
        self.table = table
        self.filters: list[tuple[str, str, object]] = []

    def select(self, *_args): return self
    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self
    def gt(self, key, value):
        self.filters.append(("gt", key, value))
        return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args): return self
    def maybe_single(self): return self


def test_reactivation_uses_current_lead_binding_and_all_binding_replies(monkeypatch):
    queries: list[Query] = []
    newer_inbound = False

    class Client:
        def table(self, name):
            query = Query(name)
            queries.append(query)
            return query

    def one(query):
        if query.table == "leads":
            return {"id": 208, "persona_id": "persona-1",
                    "channel_binding_id": "current-binding", "handoff_level": "none"}
        if query.table == "workflow_bindings":
            return {"id": "current-binding", "persona_id": "persona-1",
                    "active": True, "connection_status": "connected", "metadata": {}}
        if query.table == "lead_buffer":
            return {"id": "new-inbound"} if newer_inbound else None
        raise AssertionError(query.table)

    monkeypatch.setattr(service.supabase_client, "get_client", lambda: Client())
    monkeypatch.setattr(service, "_one", one)
    source = {"lead_ref": 208, "persona_id": "persona-1",
              "created_at": "2026-09-01T00:00:00Z", "channel_binding_id": "retired-binding"}

    service._assert_reactivation_source_current(source)
    binding_query = next(row for row in queries if row.table == "workflow_bindings")
    assert ("eq", "id", "current-binding") in binding_query.filters
    inbound_query = next(row for row in queries if row.table == "lead_buffer")
    assert ("gt", "created_at", source["created_at"]) in inbound_query.filters
    assert not any(key == "channel_binding_id" for _, key, _ in inbound_query.filters)

    newer_inbound = True
    with pytest.raises(RuntimeError, match="resposta nova"):
        service._assert_reactivation_source_current(source)
