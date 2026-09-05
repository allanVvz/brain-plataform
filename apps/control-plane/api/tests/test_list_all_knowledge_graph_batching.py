"""A graph too large to query in one URL must not look edgeless.

`list_all_knowledge_graph` filtered edges with `in_(source_node_id, node_ids)`,
which renders every id into the query string. Past a few hundred nodes the
gateway rejects the URL, and a bare `except` turned that into an empty edge
list -- indistinguishable from a genuinely edgeless graph.

That silence is dangerous, not merely lossy: graph_bundle_publisher's preflight
compares the bundle against the *existing* edges, so an empty result makes it
wave through a bundle that orphans every live edge, and its post-write
verification recompiles an edgeless graph and rejects the checksum.

The monolith was fixed first; this copy is the one that actually runs. On
2026-09-05 it blocked the Tock Fatal v16 publication with
`materialized_runtime_checksum_mismatch`, because the read back after staging
returned 0 edges for a 1015-node graph.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import supabase_client


class _Table:
    def __init__(self, recorder, fail_over):
        self._rec = recorder
        self._fail_over = fail_over
        self._batch = None

    def select(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, _column, values):
        self._batch = list(values)
        return self

    def execute(self):
        if self._batch is None:  # node query
            return type("R", (), {"data": self._rec["nodes"]})()
        self._rec["batches"].append(len(self._batch))
        if self._fail_over is not None and len(self._batch) > self._fail_over:
            raise RuntimeError("414 Request-URI Too Large")
        return type("R", (), {
            "data": [
                {"id": f"e-{nid}", "source_node_id": nid, "target_node_id": "x",
                 "relation_type": "contains", "metadata": {"active": True}}
                for nid in self._batch
            ]
        })()


def _install(monkeypatch, node_count, fail_over):
    rec = {"nodes": [{"id": f"n-{i}"} for i in range(node_count)], "batches": []}
    monkeypatch.setattr(
        supabase_client, "get_client",
        lambda: type("C", (), {"table": lambda _s, _n: _Table(rec, fail_over)})(),
    )
    monkeypatch.setattr(supabase_client, "_KG_TABLES_MISSING", False)
    return rec


def test_large_graph_still_returns_its_edges(monkeypatch):
    """1015 nodes is the size of the Tock Fatal graph that broke publication."""
    rec = _install(monkeypatch, 1015, fail_over=200)
    _nodes, edges = supabase_client.list_all_knowledge_graph(
        persona_id="p", limit_nodes=10000
    )
    assert len(edges) == 1015, "edges were lost for a large graph"
    assert max(rec["batches"]) <= supabase_client._EDGE_LOOKUP_BATCH


def test_an_unreadable_graph_raises_instead_of_looking_empty(monkeypatch):
    """The dangerous case: failure must never be reported as 'no edges'."""
    _install(monkeypatch, 1015, fail_over=0)
    with pytest.raises(RuntimeError):
        supabase_client.list_all_knowledge_graph(persona_id="p", limit_nodes=10000)
