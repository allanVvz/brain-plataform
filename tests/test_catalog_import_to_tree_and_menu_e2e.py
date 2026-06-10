"""E2E: importar 2 catálogos (vz-lupas + baita), 30 produtos em grupos, com
imagens baixadas, montar a árvore (brand → campaign → grupos → produtos → copy)
e replicar o cardápio (coleção → produtos com imagem/preço/copy).

Roda offline: Supabase é um store em memória; o download de imagem é injetado.
Prova o caminho real de `product_import_service.import_products` (extração +
associação produto/grupo/asset/copy) e, sobre ele, compõe a campanha/brand e
deriva o payload de cardápio que o frontend baita-cardapio consome
(/api/menu/{slug}).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import product_import_service as pis  # noqa: E402


class _FakeStore:
    def __init__(self) -> None:
        self.nodes: dict[tuple, dict] = {}
        self.edges: list[dict] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"n{self._seq}"

    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data["node_type"], data["slug"])
        existing = self.nodes.get(key)
        if existing:
            existing["metadata"] = {**(existing.get("metadata") or {}), **(data.get("metadata") or {})}
            return existing
        node = {"id": self._next_id(), **data}
        self.nodes[key] = node
        return node

    def upsert_knowledge_edge(self, source_id, target_id, relation_type, *, persona_id=None, weight=None, metadata=None):
        edge = {"id": f"e{len(self.edges) + 1}", "source_node_id": source_id, "target_node_id": target_id,
                "relation_type": relation_type, "persona_id": persona_id, "metadata": metadata or {}}
        self.edges.append(edge)
        return edge

    def list_product_nodes(self, *, persona_id=None, **_kw) -> list[dict]:
        return [n for (pid, t, _s), n in self.nodes.items() if t == "product" and pid == persona_id]

    # introspection
    def by_id(self, node_id: str) -> dict:
        for n in self.nodes.values():
            if n["id"] == node_id:
                return n
        return {}

    def nodes_of(self, node_type: str, persona_id: str) -> list[dict]:
        return [n for (pid, t, _s), n in self.nodes.items() if t == node_type and pid == persona_id]

    def edges_of(self, relation_type: str, persona_id: str) -> list[dict]:
        return [e for e in self.edges if e["relation_type"] == relation_type and e["persona_id"] == persona_id]


@pytest.fixture()
def store(monkeypatch) -> _FakeStore:
    fake = _FakeStore()
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_node", fake.upsert_knowledge_node)
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_edge", fake.upsert_knowledge_edge)
    monkeypatch.setattr(pis.supabase_client, "list_product_nodes", fake.list_product_nodes)
    monkeypatch.setattr(pis.supabase_client, "upload_to_storage",
                        lambda bucket, path, data, content_type="application/octet-stream": f"https://storage.local/{bucket}/{path}")
    return fake


# Dois catálogos reais: vz-lupas (óculos) e baita (conveniência).
CATALOGS = {
    "vz-lupas": {"persona_id": "persona-vzlupas", "groups": ["Radar", "Juliet", "Eye Jacket"]},
    "baita-conveniencia": {"persona_id": "persona-baita", "groups": ["Bebidas", "Salgados", "Doces"]},
}


def _make_30_items(catalog_slug: str, groups: list[str]) -> list[dict]:
    """30 produtos = 3 grupos x 10, cada um com imagem."""
    items: list[dict] = []
    for group in groups:
        for i in range(1, 11):
            ext = f"{catalog_slug}-{group.lower().replace(' ', '-')}-{i}"
            items.append({
                "title": f"{group} {i}",
                "description": f"Copy comercial de {group} {i}.",
                "prices": [f"{50 + i}.90"],
                "image_url": f"https://cdn/{catalog_slug}/{group.lower().replace(' ', '-')}-{i}.jpg",
                "external_id": ext,
                "product_group": group,
                "source": "shopify_json",
            })
    return items


def _fake_downloader(_url: str):
    return (b"\x89PNG-fake-image-bytes", "image/jpeg")


def _build_menu(store: _FakeStore, persona_id: str) -> dict:
    """Replica o shape do cardápio (/api/menu/{slug}) a partir do grafo:
    coleção -> produtos com imagem + preço + copy."""
    collections = store.nodes_of("product_group", persona_id)
    grouped = store.edges_of("product_group_has_product", persona_id)  # group -> product
    img_edges = store.edges_of("product_image", persona_id)     # product -> asset
    copy_edges = store.edges_of("supports_copy", persona_id)    # copy -> product

    img_by_product = {e["source_node_id"]: store.by_id(e["target_node_id"]) for e in img_edges}
    copy_by_product: dict[str, dict] = {}
    for e in copy_edges:
        copy_by_product[e["target_node_id"]] = store.by_id(e["source_node_id"])

    products_by_collection: dict[str, list[str]] = {}
    for e in grouped:
        products_by_collection.setdefault(e["source_node_id"], []).append(e["target_node_id"])

    out_collections = []
    for col in collections:
        product_ids = products_by_collection.get(col["id"], [])
        products = []
        for pid in product_ids:
            prod = store.by_id(pid)
            asset = img_by_product.get(pid) or {}
            copy_node = copy_by_product.get(pid) or {}
            products.append({
                "title": prod.get("title"),
                "price": (prod.get("metadata") or {}).get("price"),
                "image": (asset.get("metadata") or {}).get("url"),
                "copy": copy_node.get("summary"),
            })
        out_collections.append({"slug": col.get("slug"), "title": col.get("title"), "products": products})
    return {"persona_id": persona_id, "collections": out_collections}


@pytest.mark.parametrize("catalog_slug", list(CATALOGS.keys()))
def test_catalog_import_builds_tree_and_menu(store: _FakeStore, catalog_slug: str) -> None:
    cfg = CATALOGS[catalog_slug]
    persona_id = cfg["persona_id"]
    groups = cfg["groups"]

    # 1) Extrai/importa 30 produtos em 3 grupos, COM imagens baixadas.
    items = _make_30_items(catalog_slug, groups)
    assert len(items) == 30
    result = pis.import_products(
        provider="shopify", persona_id=persona_id, persona_slug=catalog_slug,
        items=items, download_images=True, image_downloader=_fake_downloader,
    )

    # 2) Associação produto/grupo/asset/copy materializada.
    assert result["created"] == 30
    assert result["images_downloaded"] == 30
    assert len(store.nodes_of("product", persona_id)) == 30
    assert len(store.nodes_of("product_group", persona_id)) == 3
    assert len(store.nodes_of("asset", persona_id)) == 30
    assert len(store.nodes_of("copy", persona_id)) == 30
    assert len(store.edges_of("product_group_has_product", persona_id)) == 30
    assert len(store.edges_of("product_image", persona_id)) == 30
    assert len(store.edges_of("supports_copy", persona_id)) == 30
    # todos pending; toda imagem realmente baixada (url de storage + origem preservada)
    assert all(p["status"] == "pending_validation" for p in store.nodes_of("product", persona_id))
    for asset in store.nodes_of("asset", persona_id):
        meta = asset["metadata"]
        assert meta["downloaded"] is True
        assert meta["url"].startswith("https://storage.local/assets-raw/")
        assert meta["image_source_url"].startswith("https://cdn/")

    # 3) Árvore: brand -> campaign -> grupos (compõe a campanha sobre o catálogo importado).
    brand = store.upsert_knowledge_node({"persona_id": persona_id, "node_type": "brand", "slug": f"brand-{catalog_slug}", "title": catalog_slug, "metadata": {}})
    campaign = store.upsert_knowledge_node({"persona_id": persona_id, "node_type": "campaign", "slug": f"campanha-{catalog_slug}", "title": f"Campanha {catalog_slug}", "metadata": {}})
    store.upsert_knowledge_edge(brand["id"], campaign["id"], "part_of_campaign", persona_id=persona_id)
    for col in store.nodes_of("product_group", persona_id):
        store.upsert_knowledge_edge(campaign["id"], col["id"], "campaign_has_collection", persona_id=persona_id)

    assert len(store.nodes_of("brand", persona_id)) == 1
    assert len(store.nodes_of("campaign", persona_id)) == 1
    assert len(store.edges_of("campaign_has_collection", persona_id)) == 3

    # cada produto pertence a exatamente 1 grupo; cada grupo tem 10 produtos.
    per_collection: dict[str, int] = {}
    for e in store.edges_of("product_group_has_product", persona_id):
        per_collection[e["source_node_id"]] = per_collection.get(e["source_node_id"], 0) + 1
    assert sorted(per_collection.values()) == [10, 10, 10]

    # 4) Replica o cardápio: 3 coleções x 10 produtos, cada um com imagem + copy + preço.
    menu = _build_menu(store, persona_id)
    assert len(menu["collections"]) == 3
    for col in menu["collections"]:
        assert len(col["products"]) == 10
        for prod in col["products"]:
            assert prod["image"] and prod["image"].startswith("https://storage.local/")
            assert prod["copy"]
            assert prod["price"]


def test_two_catalogs_are_isolated(store: _FakeStore) -> None:
    """Os dois catálogos coexistem sem vazar produtos entre personas."""
    for slug, cfg in CATALOGS.items():
        pis.import_products(
            provider="shopify", persona_id=cfg["persona_id"], persona_slug=slug,
            items=_make_30_items(slug, cfg["groups"]), download_images=True, image_downloader=_fake_downloader,
        )
    assert len(store.nodes_of("product", "persona-vzlupas")) == 30
    assert len(store.nodes_of("product", "persona-baita")) == 30
    # grupos distintos por catálogo
    vz_groups = {n["title"] for n in store.nodes_of("product_group", "persona-vzlupas")}
    baita_groups = {n["title"] for n in store.nodes_of("product_group", "persona-baita")}
    assert vz_groups == {"Radar", "Juliet", "Eye Jacket"}
    assert baita_groups == {"Bebidas", "Salgados", "Doces"}
    assert vz_groups.isdisjoint(baita_groups)
