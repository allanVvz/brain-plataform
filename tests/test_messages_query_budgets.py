from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from routes import messages
from services import supabase_client


def test_conversation_decoration_bulk_loads_leads(monkeypatch):
    calls: list[list[int]] = []

    def bulk(refs):
        calls.append(list(refs))
        return {
            value: {
                "id": value,
                "lead_id": f"lead-{value}",
                "stage": "novo",
                "metadata": {},
            }
            for value in refs
        }

    monkeypatch.setattr(messages.supabase_client, "get_leads_by_refs", bulk)
    monkeypatch.setattr(
        messages.supabase_client,
        "get_lead_by_ref",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("conversation decorator performed an N+1 lookup")
        ),
    )

    result = messages._decorate_conversations([
        {"lead_ref": 1, "last_message": "one"},
        {"lead_ref": 2, "last_message": "two"},
    ])

    assert calls == [[1, 2]]
    assert len(result) == 2


class _Query:
    def __init__(self, calls):
        self.calls = calls
        self.column = ""
        self.values = []

    def select(self, *_args):
        return self

    def in_(self, column, values):
        self.column = column
        self.values = list(values)
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        self.calls.append((self.column, list(self.values)))
        identity = f"{self.column}:{self.values[0]}" if self.values else self.column
        return SimpleNamespace(data=[{
            "id": identity,
            "source_node_id": self.values[0] if self.values else "source",
            "target_node_id": "target",
            "relation_type": "contains",
            "metadata": {"active": True},
        }])


class _Client:
    def __init__(self, calls):
        self.calls = calls

    def table(self, _name):
        return _Query(self.calls)


def test_graph_edge_lookup_bounds_postgrest_in_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(supabase_client, "_KG_TABLES_MISSING", False)
    monkeypatch.setattr(supabase_client, "get_client", lambda: _Client(calls))
    node_ids = [f"node-{index}" for index in range(176)]

    result = supabase_client.list_edges_for_nodes(node_ids)

    assert result
    assert len(calls) == 6
    assert all(len(values) <= 75 for _column, values in calls)
