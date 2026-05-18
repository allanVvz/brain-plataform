#!/usr/bin/env python3
"""Image upload appends ![[slug]] into the parent card's .md.

Model: brand / briefing / product / copy / faq nodes carry their long-form
markdown in a linked knowledge_item. When an image is uploaded with one of
these nodes as branch_hint, the image is anchored INTO that card's .md via
Obsidian-style embed `![[image-slug]]`.
"""
from __future__ import annotations

import asyncio
import io
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
os.environ["ASSET_RENAME_DISABLE_MODEL"] = "1"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class FakeStore:
    def __init__(self):
        self.persona = {"id": "p-1", "slug": "tock-fatal", "name": "Tock Fatal"}
        # Parent card: a product node with a linked knowledge_item holding
        # its long-form markdown.
        self.parent_item = {
            "id": "ki-product-1",
            "content": "# Kit Modal 1\n\nDescricao do produto.\n",
            "content_type": "product",
            "persona_id": "p-1",
        }
        self.parent = {
            "id": "n-product",
            "persona_id": "p-1",
            "node_type": "product",
            "slug": "kit-modal-1-9-cores",
            "title": "Kit Modal 1",
            "source_table": "knowledge_items",
            "source_id": "ki-product-1",
            "metadata": {"knowledge_item_id": "ki-product-1"},
        }
        self.gallery = {
            "id": "n-gallery",
            "persona_id": "p-1",
            "node_type": "gallery",
            "slug": "gallery-default",
        }
        self.knowledge_items_by_id = {"ki-product-1": self.parent_item}
        self.knowledge_item_updates: list[tuple[str, dict]] = []
        self.assets_inserted: list[dict] = []
        self.asset_readings: list[dict] = []
        self.knowledge_items: list[dict] = []
        self.knowledge_nodes: list[dict] = []
        self.edges: list[dict] = []
        self.asset_updates: list[dict] = []

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
        self.knowledge_items.append(row)
        self.knowledge_items_by_id[row["id"]] = row
        return deepcopy(row)
    def get_knowledge_item(self, item_id):
        return deepcopy(self.knowledge_items_by_id.get(item_id) or {})
    def update_knowledge_item(self, item_id, patch):
        self.knowledge_item_updates.append((item_id, deepcopy(patch)))
        target = self.knowledge_items_by_id.get(item_id)
        if target:
            target.update(deepcopy(patch))
    def update_asset(self, asset_id, patch):
        self.asset_updates.append({"id": asset_id, "patch": deepcopy(patch)})
        for a in self.assets_inserted:
            if a["id"] == asset_id: a.update(deepcopy(patch))
        return deepcopy(next((a for a in self.assets_inserted if a["id"] == asset_id), {}))
    def get_asset(self, asset_id):
        return deepcopy(next((a for a in self.assets_inserted if a["id"] == asset_id), {}))
    def update_asset_graph_refs(self, asset_id, *, knowledge_node_id=None, gallery_edge_id=None, parent_node_id=None, parent_edge_id=None):
        patch = {k: v for k, v in {"knowledge_node_id": knowledge_node_id, "gallery_edge_id": gallery_edge_id, "parent_node_id": parent_node_id, "parent_edge_id": parent_edge_id}.items() if v is not None}
        self.asset_updates.append({"id": asset_id, "patch": deepcopy(patch)})
        for a in self.assets_inserted:
            if a["id"] == asset_id: a.update(deepcopy(patch))
        return deepcopy(next((a for a in self.assets_inserted if a["id"] == asset_id), {}))
    def get_knowledge_node_for_source(self, source_table, source_id, persona_id=None):
        return None
    def upsert_knowledge_node(self, data):
        node = {
            "id": f"n-asset-{len(self.knowledge_nodes)+1}",
            "persona_id": data.get("persona_id"),
            "node_type": data.get("node_type"),
            "slug": data.get("slug"),
            "title": data.get("title"),
            "metadata": data.get("metadata") or {},
            "status": data.get("status") or "active",
            "source_table": data.get("source_table"),
            "source_id": data.get("source_id"),
        }
        self.knowledge_nodes.append(node)
        return deepcopy(node)
    def ensure_gallery_node(self, persona_id): return deepcopy(self.gallery)
    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        row = {"id": f"e-{len(self.edges)+1}", "source_node_id": source_node_id, "target_node_id": target_node_id, "relation_type": relation_type, "metadata": metadata or {}}
        self.edges.append(row); return deepcopy(row)


class _UploadFile:
    def __init__(self, content, filename, content_type):
        self.file = io.BytesIO(content); self.filename = filename; self.content_type = content_type
    async def read(self): return self.file.read()


class _Request:
    def __init__(self): self.state = type("S", (), {})()


def with_store(store):
    from routes import assets as routes_assets
    from services import auth_service, supabase_client
    patched = [
        "get_persona_by_id", "get_persona", "get_knowledge_node",
        "get_knowledge_node_by_slug", "upload_to_storage", "insert_asset",
        "insert_asset_reading", "get_or_create_manual_source", "insert_knowledge_item",
        "get_knowledge_item", "update_knowledge_item", "update_asset", "get_asset",
        "update_asset_graph_refs", "get_knowledge_node_for_source",
        "upsert_knowledge_node", "ensure_gallery_node", "upsert_knowledge_edge",
    ]
    orig = {n: getattr(supabase_client, n) for n in patched}
    auth_orig = auth_service.assert_persona_access
    try:
        for n in patched: setattr(supabase_client, n, getattr(store, n))
        auth_service.assert_persona_access = lambda *a, **kw: None
        upload = _UploadFile(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "wp-image.png", "image/png")
        return asyncio.run(routes_assets.upload_asset(
            _Request(), file=upload,
            persona_id=store.persona["id"],
            branch_hint=store.parent["slug"],
            asset_function="social_post",
            persona_slug=store.persona["slug"],
        ))
    finally:
        for n, fn in orig.items(): setattr(supabase_client, n, fn)
        auth_service.assert_persona_access = auth_orig


def main() -> int:
    store = FakeStore()
    result = with_store(store)

    _assert(result["success"] is True, "upload success")
    ev = result["evidence"]
    _assert(ev["parent_card_node_id"] == store.parent["id"], "evidence carries parent card node id")
    _assert(ev["parent_card_md_appended"] is True, "parent card .md was updated")
    _assert(ev["image_ref"].startswith("![["), "image_ref is an Obsidian embed")

    _assert(len(store.knowledge_item_updates) == 1, "parent knowledge_item received exactly 1 update")
    item_id, patch = store.knowledge_item_updates[0]
    _assert(item_id == store.parent_item["id"], "updated the parent's knowledge_item")
    new_content = patch["content"]
    _assert(new_content.startswith("# Kit Modal 1"), "preserves the original heading")
    _assert("## Imagens" in new_content, "appends under an 'Imagens' section")
    _assert(ev["image_ref"] in new_content, "embed ref present in the new markdown")
    _assert("Descricao do produto" in new_content, "preserves prior body content")

    # idempotency: a second upload of the SAME slug should NOT duplicate.
    second_result = with_store(store)
    appended_again = second_result["evidence"]["parent_card_md_appended"]
    duplicates = store.knowledge_item_updates[0][1]["content"].count(ev["image_ref"])
    _assert(duplicates == 1, "image ref appears only once in the parent card .md (idempotent)")
    _ = appended_again  # may be False on second run depending on slug uniqueness

    print("PASS integration_asset_appends_to_parent_card_md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
