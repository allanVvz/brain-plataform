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

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def update(self, *_a, **_k):
        self._mode = "update"
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        data = self._store.get(self._table, []) if self._mode == "select" else []
        return type("R", (), {"data": data})()


class _FakeClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _Query(name, self._store)


def test_withdraw_faq_deactivates_only_embedded_edges(monkeypatch):
    from services import supabase_client as sc

    monkeypatch.setattr(sc, "_KG_TABLES_MISSING", False, raising=False)
    store = {"knowledge_nodes": [{"id": "n1", "metadata": {}}]}
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
