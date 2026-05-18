#!/usr/bin/env python3
"""Baita cardapio seed creates 2 campaigns and links product/support assets."""
from __future__ import annotations

import sys
import tempfile
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


class FakeStore:
    def __init__(self) -> None:
        self.persona = {"id": "p-baita", "slug": "baita-conveniencia", "name": "Baita Conveniencia"}
        self.nodes: list[dict] = [
            {"id": "n-gallery", "persona_id": "p-baita", "node_type": "gallery", "slug": "gallery-default", "title": "Gallery"},
            {"id": "n-collection", "persona_id": "p-baita", "node_type": "product_collection", "slug": "cardapio-baita-v14", "title": "Cardapio Baita v14"},
        ]
        for slug, title in [
            ("licor-jagermeister-700ml", "Licor Jagermeister 700ml"),
            ("patagonia-weisse-473ml", "Patagonia Weisse 473ml"),
            ("vinho-suspeito-750ml", "Vinho Suspeito 750ml"),
            ("lagunitas-daytime-355ml", "Lagunitas Daytime Session IPA 355ml"),
        ]:
            self.nodes.append({"id": f"n-{slug}", "persona_id": "p-baita", "node_type": "product", "slug": slug, "title": title, "metadata": {}})
        self.assets: list[dict] = []
        self.edges: list[dict] = []
        self.asset_updates: list[dict] = []

    def get_persona(self, slug):
        return deepcopy(self.persona) if slug == self.persona["slug"] else None

    def ensure_gallery_node(self, persona_id):
        return deepcopy(next(n for n in self.nodes if n["id"] == "n-gallery" and n["persona_id"] == persona_id))

    def get_knowledge_node_by_slug(self, slug, persona_id=None, node_type=None):
        for node in self.nodes:
            if node["slug"] == slug and (not persona_id or node["persona_id"] == persona_id) and (not node_type or node["node_type"] == node_type):
                return deepcopy(node)
        return None

    def upsert_knowledge_node(self, data):
        for node in self.nodes:
            if node["persona_id"] == data.get("persona_id") and node["node_type"] == data["node_type"] and node["slug"] == data["slug"]:
                node.update(deepcopy(data))
                node.setdefault("id", f"n-{len(self.nodes)+1}")
                return deepcopy(node)
        row = {**deepcopy(data), "id": f"n-{len(self.nodes)+1}"}
        self.nodes.append(row)
        return deepcopy(row)

    def upload_to_storage(self, bucket, path, data, content_type="application/octet-stream"):
        return f"https://supa.local/{bucket}/{path}"

    def insert_asset(self, data):
        row = {**deepcopy(data), "id": f"a-{len(self.assets)+1}"}
        self.assets.append(row)
        return deepcopy(row)

    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        for edge in self.edges:
            if edge["source_node_id"] == source_node_id and edge["target_node_id"] == target_node_id and edge["relation_type"] == relation_type:
                edge.update({"persona_id": persona_id, "weight": weight, "metadata": metadata or {}})
                return deepcopy(edge)
        row = {
            "id": f"e-{len(self.edges)+1}",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }
        self.edges.append(row)
        return deepcopy(row)

    def update_asset_graph_refs(self, asset_id, *, knowledge_node_id=None, gallery_edge_id=None, parent_node_id=None, parent_edge_id=None):
        patch = {
            "asset_id": asset_id,
            "knowledge_node_id": knowledge_node_id,
            "gallery_edge_id": gallery_edge_id,
            "parent_node_id": parent_node_id,
            "parent_edge_id": parent_edge_id,
        }
        self.asset_updates.append(deepcopy(patch))
        return deepcopy(patch)


def main() -> int:
    from scripts import seed_baita_cardapio_assets as seed
    from services import supabase_client

    store = FakeStore()
    patched = [
        "get_persona",
        "ensure_gallery_node",
        "get_knowledge_node_by_slug",
        "upsert_knowledge_node",
        "upload_to_storage",
        "insert_asset",
        "upsert_knowledge_edge",
        "update_asset_graph_refs",
    ]
    originals = {name: getattr(supabase_client, name) for name in patched}
    try:
        for name in patched:
            setattr(supabase_client, name, getattr(store, name))
        with tempfile.TemporaryDirectory() as tmp:
            image_dir = Path(tmp)
            for filename in [
                "jagermeister-catalogo.png",
                "patagonia-weisse-473ml.jpg",
                "vinho-suspeito-brinde.png",
                "Lagunitas DayTime Session IPA.png",
                "jack-baita.png",
                "drink-baita.jpg",
                "Baita-Conveniencia-Brand.png",
                "Baita-Logo-'B'.png",
                "Baita-Asset-2estrelhas.png",
                "avalie-e-ganhe-um-drink.png",
            ]:
                (image_dir / filename).write_bytes(b"\x89PNG\r\n\x1a\nseed")
            result = seed.seed_assets(image_dir, "baita-conveniencia", None)
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)

    _assert(result["ok"] is True, "seed returns ok=True")
    _assert(set(result["campaigns"]) == {"cardapio-baita-v14", "avalie-e-ganhe"}, "creates cardapio and avalie campaigns")
    _assert(result["count"] == 10, "uploads 4 product assets + 6 support assets")

    campaigns = {n["slug"] for n in store.nodes if n["node_type"] == "campaign"}
    _assert({"cardapio-baita-v14", "avalie-e-ganhe"}.issubset(campaigns), "campaign nodes exist")
    _assert(len([a for a in store.assets if (a["metadata"] or {}).get("product_slug")]) == 4, "exactly 4 assets carry product_slug")
    _assert(len([a for a in store.assets if not (a["metadata"] or {}).get("product_slug")]) == 6, "support assets do not carry product_slug")

    product_image_edges = [e for e in store.edges if e["relation_type"] == "product_image"]
    _assert(len(product_image_edges) == 4, "exactly 4 product_image edges")
    _assert(len([e for e in store.edges if e["relation_type"] == "gallery_asset"]) == 10, "every asset links to Gallery")
    _assert(len([e for e in store.edges if e["relation_type"] == "supports_campaign"]) == 10, "every asset supports a campaign")
    _assert(all(update["parent_node_id"] for update in store.asset_updates[:4]), "product asset graph refs point to products")
    _assert(all(update["parent_node_id"] is None for update in store.asset_updates[4:]), "support asset graph refs do not point to products")

    _assert(len([n for n in store.nodes if n["node_type"] == "briefing" and n["slug"].startswith("briefing-licor")]) == 1, "product brief node exists")
    _assert(len([n for n in store.nodes if n["node_type"] == "copy" and n["slug"].startswith("copy-lagunitas")]) == 1, "product copy node exists")

    print("PASS integration_baita_cardapio_seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
