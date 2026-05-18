#!/usr/bin/env python3
"""list_gallery_assets resolves knowledge_nodes back to public.assets rows.

Regression: old gallery nodes stored an .md companion in metadata.file_path
and the function returned id="gn:<node_id>" + file_type="md", which made the
/assets page render `.md` placeholders and crashed GET/POST /assets/{id}
with `invalid input syntax for type uuid`.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class FakeQuery:
    def __init__(self, table_name: str, store: "FakeClient"):
        self.table_name = table_name
        self.store = store
        self.filters: dict = {}
        self.in_filter: tuple[str, list] | None = None
        self.neq_filter: tuple[str, str] | None = None
        self._limit = None

    def select(self, *_args, **_kwargs): return self
    def eq(self, col, val): self.filters[col] = val; return self
    def in_(self, col, vals): self.in_filter = (col, list(vals)); return self
    def neq(self, col, val): self.neq_filter = (col, val); return self
    def order(self, *_a, **_kw): return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self.store.tables.get(self.table_name, [])
        out = []
        for row in rows:
            ok = all(row.get(k) == v for k, v in self.filters.items())
            if ok and self.in_filter:
                col, vals = self.in_filter
                ok = row.get(col) in vals
            if ok and self.neq_filter:
                col, val = self.neq_filter
                ok = row.get(col) != val
            if ok:
                out.append(deepcopy(row))
        if self._limit:
            out = out[: self._limit]
        return type("R", (), {"data": out})()


class FakeClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "knowledge_nodes": [],
            "knowledge_edges": [],
            "assets": [],
        }

    def table(self, name): return FakeQuery(name, self)


def main() -> int:
    from services import supabase_client

    fake = FakeClient()

    gallery_node = {
        "id": "gallery-uuid",
        "node_type": "gallery",
        "status": "active",
        "persona_id": "persona-1",
    }
    # Node WITH backing public.assets row — the modern case (new uploads).
    backed_node = {
        "id": "node-backed",
        "node_type": "asset",
        "status": "active",
        "persona_id": "persona-1",
        "source_table": "assets",
        "source_id": "asset-real-uuid",
        "title": "Imagem boa",
        "metadata": {},
    }
    # Orphan gallery node — legacy Sofia/CRIAR flow. No public.assets row.
    # Used to surface in the UI as `.md` and crash /assets/{id}.
    orphan_node = {
        "id": "node-orphan",
        "node_type": "asset",
        "status": "active",
        "persona_id": "persona-1",
        "source_table": None,
        "source_id": None,
        "title": "Md companion",
        "metadata": {"file_path": "assets/persona-1/something.md"},
    }
    backed_asset = {
        "id": "asset-real-uuid",
        "persona_id": "persona-1",
        "type": "image",
        "name": "wp-image.png",
        "url": "https://example/wp-image.png",
        "original_filename": "wp-image.png",
        "mime_type": "image/png",
        "storage_bucket": "assets-raw",
        "storage_path": "persona-1/wp-image.png",
        "status": "ready",
        "metadata": {"asset_function": "social_post", "kind": "image_social"},
        "created_at": "2026-05-01T00:00:00Z",
    }

    fake.tables["knowledge_nodes"] = [gallery_node, backed_node, orphan_node]
    fake.tables["knowledge_edges"] = [
        {
            "id": "edge-backed",
            "source_node_id": "node-backed",
            "target_node_id": "gallery-uuid",
            "relation_type": "gallery_asset",
            "metadata": {},
        },
        {
            "id": "edge-orphan",
            "source_node_id": "node-orphan",
            "target_node_id": "gallery-uuid",
            "relation_type": "gallery_asset",
            "metadata": {},
        },
    ]
    fake.tables["assets"] = [backed_asset]

    original_get_client = supabase_client.get_client
    original_kg_missing = supabase_client._KG_TABLES_MISSING
    supabase_client.get_client = lambda: fake
    supabase_client._KG_TABLES_MISSING = False
    try:
        rows = supabase_client.list_gallery_assets(persona_id="persona-1")
    finally:
        supabase_client.get_client = original_get_client
        supabase_client._KG_TABLES_MISSING = original_kg_missing

    _assert(len(rows) == 1, "orphan gallery node skipped; only backed asset returned")
    row = rows[0]
    _assert(row["id"] == "asset-real-uuid", "id is public.assets UUID (no gn: prefix)")
    _assert(not str(row["id"]).startswith("gn:"), "id never starts with 'gn:'")
    _assert(row["file_type"] == "png", "file_type extracted from real filename")
    _assert(row["url"] == "https://example/wp-image.png", "asset url returned")
    _assert(row["asset_type"] == "image", "asset_type from public.assets.type")
    _assert(row["knowledge_node_id"] == "node-backed", "knowledge_node_id exposed for traceability")
    _assert(row["gallery_edge_id"] == "edge-backed", "gallery_edge_id linked")
    _assert(row["persona_id"] == "persona-1", "persona_id propagated")

    print("PASS integration_gallery_assets_resolution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
