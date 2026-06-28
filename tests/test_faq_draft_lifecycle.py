"""Task B — editing an approved/embedded FAQ sends it back to draft (rascunho)
and withdraws it from Embedded until it is re-approved + re-published.

Pure-logic + monkeypatched tests; no live Supabase.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# ── route gate: _should_revert_faq_to_draft ──────────────────────────────────

def test_should_revert_faq_when_content_changes_on_approved():
    from routes import knowledge

    existing = {"content_type": "faq", "status": "approved", "content": "old", "title": "T"}
    assert knowledge._should_revert_faq_to_draft(existing, {"content": "new"}) is True
    assert knowledge._should_revert_faq_to_draft(existing, {"title": "T2"}) is True


def test_should_revert_faq_when_embedded():
    from routes import knowledge

    existing = {"content_type": "faq", "status": "embedded", "content": "old"}
    assert knowledge._should_revert_faq_to_draft(existing, {"content": "new"}) is True


def test_should_not_revert_when_status_unchanged_content():
    from routes import knowledge

    existing = {"content_type": "faq", "status": "approved", "content": "same"}
    assert knowledge._should_revert_faq_to_draft(existing, {"content": "same"}) is False


def test_should_not_revert_non_faq_or_draft_or_explicit_status():
    from routes import knowledge

    # not a faq
    assert knowledge._should_revert_faq_to_draft(
        {"content_type": "product", "status": "approved", "content": "old"}, {"content": "new"}
    ) is False
    # already a draft (pending) — nothing to revert
    assert knowledge._should_revert_faq_to_draft(
        {"content_type": "faq", "status": "pending", "content": "old"}, {"content": "new"}
    ) is False
    # explicit status patch is respected, not overridden
    assert knowledge._should_revert_faq_to_draft(
        {"content_type": "faq", "status": "approved", "content": "old"},
        {"content": "new", "status": "approved"},
    ) is False
    # no existing item
    assert knowledge._should_revert_faq_to_draft(None, {"content": "new"}) is False


# ── withdraw_faq_from_embedded ───────────────────────────────────────────────

class _Query:
    def __init__(self, table_name, store):
        self._table = table_name
        self._store = store
        self._mode = "select"
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def update(self, *args, **_k):
        self._mode = "update"
        self._payload = args[0] if args else {}
        return self

    def eq(self, *args, **_k):
        if len(args) >= 2:
            self._filters.append((args[0], args[1]))
        return self

    def execute(self):
        rows = self._store.get(self._table, [])
        for key, value in self._filters:
            rows = [row for row in rows if row.get(key) == value]
        if self._mode == "update":
            self._store.setdefault("_updates", []).append({
                "table": self._table,
                "filters": list(self._filters),
                "payload": self._payload,
            })
            for row in rows:
                row.update(self._payload or {})
            data = rows
        else:
            data = rows
        return type("R", (), {"data": data})()


class _FakeClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _Query(name, self._store)


def test_withdraw_faq_deactivates_only_embedded_edges(monkeypatch):
    from services import supabase_client as sc

    monkeypatch.setattr(sc, "_KG_TABLES_MISSING", False, raising=False)
    store = {
        "knowledge_nodes": [
            {"id": "n1", "source_table": "knowledge_items", "source_id": "item-1", "node_type": "faq", "metadata": {}}
        ]
    }
    monkeypatch.setattr(sc, "get_client", lambda: _FakeClient(store))

    monkeypatch.setattr(
        sc,
        "list_edges_for_nodes",
        lambda ids, **k: [
            {"id": "e1", "source_node_id": "n1", "target_node_id": "emb"},
            {"id": "e2", "source_node_id": "n1", "target_node_id": "prod"},
            {"id": "e3", "source_node_id": "other", "target_node_id": "n1"},  # incoming, ignored
        ],
    )
    monkeypatch.setattr(
        sc,
        "get_knowledge_node",
        lambda nid: {"emb": {"node_type": "embedded"}, "prod": {"node_type": "product"}}.get(nid),
    )
    deactivated: list[str] = []
    monkeypatch.setattr(sc, "delete_knowledge_edge", lambda eid: deactivated.append(eid) or True)

    summary = sc.withdraw_faq_from_embedded("item-1")

    assert summary["node_ids"] == ["n1"]
    assert summary["deactivated_embedded_edges"] == ["e1"]
    assert deactivated == ["e1"]


def test_withdraw_faq_deletes_rag_and_marks_snapshot_stale(monkeypatch):
    from services import supabase_client as sc

    monkeypatch.setattr(sc, "_KG_TABLES_MISSING", False, raising=False)
    store = {
        "knowledge_nodes": [
            {
                "id": "n1",
                "source_table": "knowledge_items",
                "source_id": "item-1",
                "node_type": "faq",
                "metadata": {
                    "knowledge_rag_entry_id": "rag-node",
                    "knowledge_rag_entry_ids": ["rag-node-extra"],
                    "knowledge_rag_chunk_ids": ["chunk-old"],
                    "n8n_ready": True,
                },
            }
        ],
        "knowledge_items": [
            {
                "id": "item-1",
                "metadata": {
                    "knowledge_rag_entry_id": "rag-item",
                    "knowledge_rag_chunk_ids": ["chunk-item"],
                    "n8n_ready": True,
                },
            }
        ],
        "knowledge_rag_entries": [{"id": "rag-query", "source_node_id": "n1", "content_type": "faq"}],
    }
    monkeypatch.setattr(sc, "get_client", lambda: _FakeClient(store))
    monkeypatch.setattr(sc, "list_edges_for_nodes", lambda ids, **k: [])
    monkeypatch.setattr(
        sc,
        "list_approved_snapshots_for_nodes",
        lambda ids: {
            "n1": {
                "id": "snap-1",
                "source_node_id": "n1",
                "rag_entry_id": "rag-snapshot",
                "metadata": {"rag_entry_ids": ["rag-snapshot-extra"], "rag_chunk_ids": ["chunk-snap"]},
            }
        },
    )
    deleted: list[str] = []
    monkeypatch.setattr(sc, "delete_knowledge_rag_entry", lambda entry_id: deleted.append(entry_id) or True)
    stale_updates: list[dict] = []
    monkeypatch.setattr(sc, "update_approved_knowledge_snapshot", lambda sid, data: stale_updates.append({"id": sid, "data": data}) or data)
    monkeypatch.setattr(sc, "get_knowledge_item", lambda item_id: store["knowledge_items"][0])

    summary = sc.withdraw_faq_from_embedded("item-1")

    assert summary["deleted_rag_entry_ids"] == deleted
    assert deleted == ["rag-node", "rag-node-extra", "rag-snapshot", "rag-snapshot-extra", "rag-query"]
    assert stale_updates[0]["id"] == "snap-1"
    assert stale_updates[0]["data"]["status"] == "stale"
    node_update = next(update for update in store["_updates"] if update["table"] == "knowledge_nodes")
    item_update = next(update for update in store["_updates"] if update["table"] == "knowledge_items")
    assert node_update["payload"]["status"] == "pending_validation"
    assert node_update["payload"]["metadata"]["n8n_ready"] is False
    assert "knowledge_rag_entry_id" not in node_update["payload"]["metadata"]
    assert item_update["payload"]["metadata"]["snapshot_status"] == "withdrawn"
    assert "knowledge_rag_chunk_ids" not in item_update["payload"]["metadata"]
