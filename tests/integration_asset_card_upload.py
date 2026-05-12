#!/usr/bin/env python3
"""ASSET card upload creates assets + knowledge_item + node + edges; no RAG."""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["ASSET_OCR_BACKEND"] = "mock"
os.environ["ASSET_RENAME_DISABLE_MODEL"] = "1"

from services import knowledge_rag_intake  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class FakeStore:
    """Mocks the supabase_client surface used by /assets/upload."""
    def __init__(self):
        self.persona = {"id": "p-1", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.parent = {
            "id": "n-product",
            "persona_id": "p-1",
            "node_type": "product",
            "slug": "kit-modal-1-9-cores",
            "title": "Kit Modal 1",
        }
        self.gallery = {
            "id": "n-gallery",
            "persona_id": "p-1",
            "node_type": "gallery",
            "slug": "gallery-default",
            "title": "Gallery",
        }
        self.assets_inserted: list[dict] = []
        self.asset_readings: list[dict] = []
        self.knowledge_items: list[dict] = []
        self.knowledge_nodes: list[dict] = []
        self.edges: list[dict] = []
        self.asset_updates: list[dict] = []
        self.uploaded: list[tuple[str, str]] = []

    # ---- supabase_client.* ----
    def get_persona_by_id(self, pid): return deepcopy(self.persona) if pid == self.persona["id"] else None
    def get_persona(self, slug): return deepcopy(self.persona) if slug == self.persona["slug"] else None
    def get_knowledge_node(self, node_id):
        for n in (self.parent, self.gallery, *self.knowledge_nodes):
            if n["id"] == node_id: return deepcopy(n)
        return None
    def get_knowledge_node_by_slug(self, slug, persona_id=None, node_type=None):
        for n in (self.parent, self.gallery, *self.knowledge_nodes):
            if n["slug"] == slug and (not persona_id or n["persona_id"] == persona_id):
                return deepcopy(n)
        return None
    def upload_to_storage(self, bucket, path, data, content_type="application/octet-stream"):
        self.uploaded.append((bucket, path))
        return f"https://supa.local/{bucket}/{path}"
    def insert_asset(self, data):
        row = {**deepcopy(data), "id": f"a-{len(self.assets_inserted)+1}"}
        self.assets_inserted.append(row); return deepcopy(row)
    def insert_asset_reading(self, data):
        row = {**deepcopy(data), "id": f"ar-{len(self.asset_readings)+1}"}
        self.asset_readings.append(row); return deepcopy(row)
    def get_or_create_manual_source(self): return {"id": "src-manual", "kind": "manual"}
    def insert_knowledge_item(self, data):
        row = {**deepcopy(data), "id": f"ki-{len(self.knowledge_items)+1}"}
        self.knowledge_items.append(row); return deepcopy(row)
    def update_asset(self, asset_id, patch):
        self.asset_updates.append({"id": asset_id, "patch": deepcopy(patch)})
        for a in self.assets_inserted:
            if a["id"] == asset_id: a.update(deepcopy(patch))
        return deepcopy(next((a for a in self.assets_inserted if a["id"] == asset_id), {}))
    def ensure_gallery_node(self, persona_id): return deepcopy(self.gallery)
    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        row = {
            "id": f"e-{len(self.edges)+1}",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }
        self.edges.append(row); return deepcopy(row)
    # bootstrap_from_item is patched to return a mirror node directly
    def bootstrap_from_item(self, item, frontmatter=None, body="", persona_id=None, source_table=None):
        node = {
            "id": f"n-asset-{item.get('id','x')}",
            "persona_id": persona_id,
            "node_type": "asset",
            "slug": (frontmatter or {}).get("slug") or item.get("title", "asset"),
            "title": item["title"],
            "summary": (item.get("content") or "")[:200],
            "metadata": item.get("metadata") or {},
            "status": "pending",
        }
        self.knowledge_nodes.append(node); return deepcopy(node)


class _UploadFile:
    """Minimal stand-in for fastapi.UploadFile."""
    def __init__(self, content: bytes, filename: str, content_type: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type
    async def read(self) -> bytes: return self.file.read()


class _Request:
    def __init__(self): self.state = type("S", (), {})()


def with_store(store: FakeStore, **kwargs):
    from routes import assets as routes_assets
    from services import auth_service, knowledge_graph, supabase_client
    patched_sb = [
        "get_persona_by_id", "get_persona", "get_knowledge_node",
        "get_knowledge_node_by_slug", "upload_to_storage", "insert_asset",
        "insert_asset_reading", "get_or_create_manual_source", "insert_knowledge_item",
        "update_asset", "ensure_gallery_node", "upsert_knowledge_edge",
    ]
    sb_orig = {n: getattr(supabase_client, n) for n in patched_sb}
    kg_orig = knowledge_graph.bootstrap_from_item
    auth_orig = auth_service.assert_persona_access
    try:
        for n in patched_sb:
            setattr(supabase_client, n, getattr(store, n))
        knowledge_graph.bootstrap_from_item = store.bootstrap_from_item
        auth_service.assert_persona_access = lambda *a, **kw: None
        upload = _UploadFile(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "wp-image.png", "image/png")
        return asyncio.run(routes_assets.upload_asset(
            _Request(),
            file=upload,
            persona_id=store.persona["id"],
            branch_hint=store.parent["slug"],
            asset_function=kwargs.get("asset_function"),
            persona_slug=store.persona["slug"],
        ))
    finally:
        for n, fn in sb_orig.items(): setattr(supabase_client, n, fn)
        knowledge_graph.bootstrap_from_item = kg_orig
        auth_service.assert_persona_access = auth_orig


def main() -> int:
    store = FakeStore()
    result = with_store(store)

    _assert(result["success"] is True, "/assets/upload returns success=true")
    _assert(len(store.assets_inserted) == 1, "public.assets row inserted")
    inserted = store.assets_inserted[0]
    _assert(inserted["upload_context"] == "asset_card", "upload_context tagged asset_card")
    _assert(inserted["storage_bucket"] in ("assets-raw", "knowledge"), "stored in assets-raw or fallback knowledge bucket")
    _assert(inserted["persona_id"] == "p-1", "asset row carries persona_id")

    _assert(len(store.knowledge_items) == 1, "knowledge_item created")
    ki = store.knowledge_items[0]
    _assert(ki["content_type"] == "asset", "content_type=asset")
    _assert(ki["status"] == "pending", "knowledge_item status=pending")
    _assert(ki["metadata"]["asset_id"] == inserted["id"], "knowledge_item metadata.asset_id matches")

    _assert(len(store.knowledge_nodes) == 1, "knowledge_node created via bootstrap")
    node = store.knowledge_nodes[0]
    _assert(node["node_type"] == "asset", "node_type=asset")

    rels = sorted(e["relation_type"] for e in store.edges)
    _assert("uses_asset" in rels, "parent->asset edge created with relation uses_asset")
    _assert("gallery_asset" in rels, "asset->gallery edge created with relation gallery_asset")

    parent_edge = next(e for e in store.edges if e["relation_type"] == "uses_asset")
    _assert(parent_edge["source_node_id"] == store.parent["id"], "parent edge source = parent node")
    _assert(parent_edge["target_node_id"] == node["id"], "parent edge target = asset node")

    gallery_edge = next(e for e in store.edges if e["relation_type"] == "gallery_asset")
    _assert(gallery_edge["source_node_id"] == node["id"], "gallery edge source = asset node")
    _assert(gallery_edge["target_node_id"] == store.gallery["id"], "gallery edge target = gallery node")
    _assert(gallery_edge["metadata"].get("graph_layer") == "auxiliary", "gallery edge marked auxiliary")
    _assert(gallery_edge["metadata"].get("primary_tree") is False, "gallery edge primary_tree=false")

    # RAG gate: content_type='asset' must never be RAG-eligible.
    _assert(knowledge_rag_intake.is_rag_eligible("asset") is False, "asset content_type is NOT rag eligible")

    # asset row updated with knowledge_node_id + gallery_edge_id.
    update = next((u for u in store.asset_updates if "knowledge_node_id" in u["patch"]), None)
    _assert(update is not None, "asset row updated with knowledge_node_id")
    _assert(update["patch"]["knowledge_node_id"] == node["id"], "knowledge_node_id linked back")

    print("PASS integration_asset_card_upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
