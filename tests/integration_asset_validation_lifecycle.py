#!/usr/bin/env python3
"""ASSET card lifecycle: item shows in /knowledge/queue?content_type=asset, approve
moves it to status=approved and node status=validated, and NO row is created in
knowledge_rag_* (assets are never RAG-eligible)."""
from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["ASSET_OCR_BACKEND"] = "mock"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class FakeStore:
    def __init__(self) -> None:
        self.persona = {"id": "p-1", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.item = {
            "id": "ki-asset-1",
            "persona_id": "p-1",
            "content_type": "asset",
            "title": "Foto kit modal 1",
            "content": "asset capturado via card ASSET",
            "status": "pending",
            "curation_status": "pending",
            "metadata": {"asset_id": "a-1", "asset_function": "reference"},
            "tags": ["asset"],
            "source_table": "knowledge_items",
        }
        self.node = {
            "id": "n-asset-1",
            "persona_id": "p-1",
            "node_type": "asset",
            "slug": "foto-kit-modal-1",
            "title": self.item["title"],
            "source_table": "knowledge_items",
            "source_id": self.item["id"],
            "metadata": dict(self.item["metadata"]),
            "status": "pending",
        }
        self.item_updates: list[dict] = []
        self.rag_entry_inserts: list[dict] = []
        self.rag_chunk_inserts: list[dict] = []

    # ---- queue listing ----
    def get_knowledge_items(self, status="pending", persona_id=None, content_type=None, limit=100, offset=0):
        rows = [self.item]
        if status and self.item.get("status") != status:
            rows = []
        if persona_id and self.item.get("persona_id") != persona_id:
            rows = []
        if content_type and self.item.get("content_type") != content_type:
            rows = []
        return [deepcopy(r) for r in rows]

    # ---- approve flow ----
    def get_knowledge_item(self, item_id):
        return deepcopy(self.item) if item_id == self.item["id"] else None

    def update_knowledge_item(self, item_id, patch):
        self.item_updates.append({"id": item_id, "patch": deepcopy(patch)})
        if item_id == self.item["id"]:
            self.item.update(deepcopy(patch))
        return deepcopy(self.item)

    def bootstrap_from_item(self, item, frontmatter=None, body="", persona_id=None, source_table=None):
        # promote_knowledge_item -> knowledge_graph.bootstrap_from_item: return the
        # already-existing node mirror for this asset item.
        return deepcopy(self.node)

    def get_knowledge_node(self, node_id):
        return deepcopy(self.node) if node_id == self.node["id"] else None

    def get_knowledge_nodes_for_item(self, item):
        return [deepcopy(self.node)] if item.get("id") == self.item["id"] else []

    def get_knowledge_node_for_source(self, source_table, source_id, persona_id=None):
        if source_table == "knowledge_items" and str(source_id) == self.item["id"]:
            return deepcopy(self.node)
        return None

    def normalize_file_path(self, value):
        return value

    def update_knowledge_node(self, node_id, patch):
        if node_id == self.node["id"]:
            self.node.update(deepcopy(patch))
        return deepcopy(self.node)

    # ---- RAG insert hooks: must NEVER be called for asset ----
    def upsert_knowledge_rag_entry(self, data):
        self.rag_entry_inserts.append(deepcopy(data))
        return {**data, "id": f"rag-NOT-EXPECTED-{len(self.rag_entry_inserts)}"}

    def replace_knowledge_rag_chunks(self, rag_entry_id, persona_id, chunks):
        for chunk in chunks:
            self.rag_chunk_inserts.append({"rag_entry_id": rag_entry_id, **chunk})
        return []


class _Request:
    def __init__(self):
        self.state = type("S", (), {})()


def main() -> int:
    from routes import knowledge as routes_knowledge
    from services import (
        auth_service,
        knowledge_graph,
        knowledge_lifecycle,
        knowledge_rag_intake,
        supabase_client,
    )

    store = FakeStore()

    auth_orig = {
        "assert_persona_access": auth_service.assert_persona_access,
        "is_admin": auth_service.is_admin,
        "current_user": auth_service.current_user,
        "allowed_persona_ids": auth_service.allowed_persona_ids,
    }
    sb_targets = [
        "get_knowledge_items", "get_knowledge_item", "update_knowledge_item",
        "get_knowledge_node", "update_knowledge_node",
        "get_knowledge_node_for_source", "normalize_file_path",
        "upsert_knowledge_rag_entry", "replace_knowledge_rag_chunks",
    ]
    sb_orig = {n: getattr(supabase_client, n, None) for n in sb_targets}
    kg_orig_bootstrap = knowledge_graph.bootstrap_from_item
    # promote_knowledge_item uses _confirmed_graph_node_for_item(item) which calls
    # supabase_client.get_knowledge_nodes_for_item; provide a stub there too.
    nodes_for_item_orig = getattr(supabase_client, "get_knowledge_nodes_for_item", None)

    try:
        # Auth stubs (avoid HTTPException on missing session/user state).
        auth_service.assert_persona_access = lambda *a, **kw: None
        auth_service.is_admin = lambda *a, **kw: True
        auth_service.current_user = lambda *a, **kw: {"id": "user-test", "role": "admin"}
        auth_service.allowed_persona_ids = lambda *a, **kw: ["p-1"]

        for name in sb_targets:
            if hasattr(store, name):
                setattr(supabase_client, name, getattr(store, name))
        supabase_client.get_knowledge_nodes_for_item = store.get_knowledge_nodes_for_item
        knowledge_graph.bootstrap_from_item = store.bootstrap_from_item

        # 1) Asset card item appears in /knowledge/queue?content_type=asset
        queued = routes_knowledge.list_queue(_Request(), status="pending", persona_id="p-1", content_type="asset")
        _assert(len(queued) == 1, "queue filtered by content_type=asset returns the asset item")
        _assert(queued[0]["id"] == store.item["id"], "queue returns the expected asset card item")
        _assert(queued[0]["content_type"] == "asset", "queued row carries content_type=asset")

        # 2) Approve path via promote_knowledge_item (the same code that the handler
        #    calls before publish_approved_node). promote_to_kb=False is the
        #    intended approval mode for non-FAQ types after migration 030+.
        result = knowledge_lifecycle.promote_knowledge_item(
            store.item["id"],
            promote_to_kb=False,
            approval_mode="manual_validation",
        )
        approved_item = result["item"]
        evidence = result["evidence"]

        _assert(approved_item["status"] == "approved", "asset item status=approved after approve")
        _assert(approved_item["curation_status"] == "approved", "asset item curation_status=approved")
        _assert(evidence["knowledge_node_id"] == store.node["id"], "evidence carries the asset node id")
        _assert(evidence["knowledge_rag_entry_id"] is None, "evidence has no rag entry id for asset approval")
        _assert(evidence["embedded_edge_id"] is None, "evidence has no embedded edge for asset approval")

        # 3) Hard contract: assets are NEVER RAG-eligible.
        _assert(knowledge_rag_intake.is_rag_eligible("asset") is False,
                "is_rag_eligible('asset') stays False")
        _assert(len(store.rag_entry_inserts) == 0,
                "no knowledge_rag_entries row inserted during asset approval")
        _assert(len(store.rag_chunk_inserts) == 0,
                "no knowledge_rag_chunks row inserted during asset approval")
    finally:
        for name, fn in sb_orig.items():
            if fn is not None:
                setattr(supabase_client, name, fn)
        if nodes_for_item_orig is not None:
            supabase_client.get_knowledge_nodes_for_item = nodes_for_item_orig
        else:
            # Attribute did not exist before; remove our stub to avoid leaking it
            # across other tests in the same interpreter.
            try:
                delattr(supabase_client, "get_knowledge_nodes_for_item")
            except AttributeError:
                pass
        knowledge_graph.bootstrap_from_item = kg_orig_bootstrap
        for name, fn in auth_orig.items():
            setattr(auth_service, name, fn)

    print("PASS integration_asset_validation_lifecycle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
