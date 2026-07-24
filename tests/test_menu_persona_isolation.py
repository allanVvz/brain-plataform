"""Regressão: /cardapio/{slug} deve mostrar os produtos DA PERSONA do slug.

Bug relatado: /cardapio/vz-lupas exibia produtos da persona `baita`. Causa: o
import gravava `product_collection`+`part_of_collection`, mas o menu lê
`product_group` + bind por `metadata.category_slug`/edge
`product_group_has_product`; sem categorias, a vz-lupas vinha vazia e o front
caía em fallback. Aqui rodamos o `build_menu_payload` REAL offline (Supabase =
store em memória) populado pelo import, para os dois catálogos, e provamos:
- cada menu só contém os produtos da sua persona (zero vazamento);
- os produtos aparecem agrupados por product_group;
- as imagens importadas (asset nodes) aparecem no payload.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import product_import_service as pis  # noqa: E402
from routes import menu as menu_route  # noqa: E402


class _Store:
    def __init__(self) -> None:
        self.nodes: dict[tuple, dict] = {}
        self.edges: list[dict] = []
        self._seq = 0

    def _nid(self) -> str:
        self._seq += 1
        return f"n{self._seq}"

    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data["node_type"], data["slug"])
        if key in self.nodes:
            self.nodes[key]["metadata"] = {**(self.nodes[key].get("metadata") or {}), **(data.get("metadata") or {})}
            return self.nodes[key]
        node = {"id": self._nid(), **data}
        self.nodes[key] = node
        return node

    def upsert_knowledge_edge(self, src, tgt, rel, *, persona_id=None, weight=None, metadata=None):
        edge = {"id": f"e{len(self.edges)+1}", "source_node_id": src, "target_node_id": tgt,
                "relation_type": rel, "persona_id": persona_id, "metadata": metadata or {}}
        self.edges.append(edge)
        return edge

    # menu reads --------------------------------------------------------------
    def list_product_nodes(self, *, persona_id=None, collection_slug=None, category_slug=None, status=None, limit=1000):
        rows = [n for (pid, t, _s), n in self.nodes.items() if t == "product" and pid == persona_id]
        if collection_slug:
            rows = [r for r in rows if (r.get("metadata") or {}).get("collection_slug") == collection_slug]
        return rows

    def list_product_collection_nodes(self, *, persona_id=None, node_type="product_group", limit=500):
        return [n for (pid, t, _s), n in self.nodes.items() if t == node_type and pid == persona_id]

    def get_knowledge_node_by_slug(self, slug, *, persona_id=None, node_type=None):
        return self.nodes.get((persona_id, node_type, slug))

    def list_edges_for_nodes(self, node_ids, *, relation_types=None, limit=5000):
        ids = set(node_ids)
        out = []
        for e in self.edges:
            if e["source_node_id"] in ids or e["target_node_id"] in ids:
                if relation_types is None or e["relation_type"] in relation_types:
                    out.append(e)
        return out

    def list_knowledge_nodes_by_ids(self, ids):
        idset = set(ids)
        return [n for n in self.nodes.values() if n["id"] in idset]

    def nodes_of(self, node_type, persona_id):
        return [n for (pid, t, _s), n in self.nodes.items() if t == node_type and pid == persona_id]

    def ensure_gallery_node(self, persona_id):
        return self.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "gallery",
            "slug": "gallery-default",
            "title": "Gallery",
            "metadata": {},
            "status": "active",
        })

    def list_gallery_assets(self, *, persona_id=None, limit=500):
        galleries = {node["id"] for node in self.nodes_of("gallery", persona_id)}
        asset_ids = {
            edge["source_node_id"]
            for edge in self.edges
            if edge["relation_type"] == "gallery_asset"
            and edge["target_node_id"] in galleries
            and edge.get("metadata", {}).get("active") is not False
        }
        return [
            {
                "knowledge_node_id": node["id"],
                "url": (node.get("metadata") or {}).get("url"),
                "status": "approved",
                "metadata": node.get("metadata") or {},
                "title": node.get("title"),
            }
            for node in self.nodes.values()
            if node["id"] in asset_ids
        ]


class _FakeChain:
    """No-op chainable for supabase_client.get_client().table(...).<...>.execute()."""
    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return type("R", (), {"data": []})()


CATALOGS = {
    "vz-lupas": {"persona_id": "p-vz", "groups": ["Radar", "Juliet"]},
    "baita-conveniencia": {"persona_id": "p-baita", "groups": ["Bebidas", "Doces"]},
}
SLUG_TO_PID = {s: c["persona_id"] for s, c in CATALOGS.items()}


def _items(slug, groups, n=2):
    out = []
    for g in groups:
        for i in range(1, n + 1):
            out.append({
                "title": f"{g} {i}", "description": f"Copy {g} {i}.", "prices": [f"{10+i}.90"],
                "image_url": f"https://cdn/{slug}/{g.lower()}-{i}.jpg",
                "external_id": f"{slug}-{g.lower()}-{i}", "product_group": g, "source": "shopify_json",
            })
    return out


@pytest.fixture()
def store(monkeypatch) -> _Store:
    s = _Store()
    # import side
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_node", s.upsert_knowledge_node)
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_edge", s.upsert_knowledge_edge)
    monkeypatch.setattr(pis.supabase_client, "ensure_gallery_node", s.ensure_gallery_node)
    monkeypatch.setattr(pis.supabase_client, "list_product_nodes", s.list_product_nodes)
    monkeypatch.setattr(pis.supabase_client, "upload_to_storage",
                        lambda b, p, d, content_type="application/octet-stream": f"https://storage.local/{b}/{p}")
    # menu side (same module object)
    sc = menu_route.supabase_client
    monkeypatch.setattr(sc, "get_persona", lambda slug: ({"id": SLUG_TO_PID[slug], "slug": slug, "name": slug} if slug in SLUG_TO_PID else None))
    monkeypatch.setattr(sc, "get_personas", lambda: [{"id": pid, "slug": s2, "name": s2} for s2, pid in SLUG_TO_PID.items()])
    monkeypatch.setattr(sc, "get_knowledge_node_by_slug", lambda slug, persona_id=None, node_type=None: s.get_knowledge_node_by_slug(slug, persona_id=persona_id, node_type=node_type))
    monkeypatch.setattr(sc, "list_product_collection_nodes", s.list_product_collection_nodes)
    monkeypatch.setattr(sc, "list_product_nodes", s.list_product_nodes)
    monkeypatch.setattr(sc, "list_edges_for_nodes", s.list_edges_for_nodes)
    monkeypatch.setattr(sc, "list_knowledge_nodes_by_ids", s.list_knowledge_nodes_by_ids)
    monkeypatch.setattr(sc, "list_gallery_assets", s.list_gallery_assets)
    monkeypatch.setattr(sc, "get_client", lambda: _FakeChain())
    return s


def _seed_both(store: _Store) -> None:
    for slug, cfg in CATALOGS.items():
        pis.import_products(provider="shopify", persona_id=cfg["persona_id"], persona_slug=slug,
                            items=_items(slug, cfg["groups"]), download_images=True,
                            image_downloader=lambda _u: (b"img", "image/jpeg"))


def _menu_product_names(payload: dict) -> set[str]:
    names = set()
    for col in payload["persona"]["collections"]:
        for cat in col["categories"]:
            for p in cat["products"]:
                names.add(p["name"])
    return names


def test_vzlupas_menu_shows_only_vzlupas_products(store: _Store) -> None:
    _seed_both(store)
    payload = menu_route.build_menu_payload("vz-lupas")

    assert payload["persona"]["slug"] == "vz-lupas"
    collection = payload["persona"]["collections"][0]
    categories = [c for c in collection["categories"] if c["products"]]
    # 2 grupos (Radar, Juliet), cada um com 2 produtos
    assert {c["title"] for c in categories} == {"Radar", "Juliet"}
    for cat in categories:
        assert len(cat["products"]) == 2
        for prod in cat["products"]:
            assert prod["assets"] and prod["assets"][0]["url"].startswith("https://storage.local/")

    names = _menu_product_names(payload)
    assert all(n.startswith(("Radar", "Juliet")) for n in names)
    # ZERO vazamento da baita
    assert not any(n.startswith(("Bebidas", "Doces")) for n in names)


def test_baita_menu_shows_only_baita_products(store: _Store) -> None:
    _seed_both(store)
    payload = menu_route.build_menu_payload("baita-conveniencia")
    names = _menu_product_names(payload)
    assert names and all(n.startswith(("Bebidas", "Doces")) for n in names)
    assert not any(n.startswith(("Radar", "Juliet")) for n in names)


def test_menu_payload_exposes_public_site_contract(store: _Store, monkeypatch) -> None:
    persona = {
        "id": "p-vz",
        "slug": "vz-lupas",
        "name": "VZ Lupas",
        "catalog_url": "https://catalog.example/vz-lupas",
        "config": {
            "public_site": {
                "site_slug": "vitrine-vz",
                "site_name": "Vitrine VZ",
                "format_key": "landing_page",
                "default_collection_slug": "campanha-vz-v1",
                "whatsapp_phone": "+55 (11) 99999-8888",
                "whatsapp_message_template": "Ola, vim pela landing e quero comprar.",
            }
        },
    }
    monkeypatch.setattr(menu_route.supabase_client, "get_persona", lambda slug: persona if slug == "vz-lupas" else None)

    payload = menu_route.build_menu_payload("vz-lupas")

    assert payload["site"]["slug"] == "vitrine-vz"
    assert payload["site"]["name"] == "Vitrine VZ"
    assert payload["site"]["format_key"] == "landing_page"
    assert payload["site"]["route_path"] == "/landing/vitrine-vz"
    assert payload["site"]["catalog_url"] == "https://catalog.example/vz-lupas"
    assert payload["site"]["default_collection_slug"] == "campanha-vz-v1"
    assert payload["site"]["whatsapp"]["phone"] == "5511999998888"
    assert payload["site"]["whatsapp"]["href"].startswith("https://wa.me/5511999998888?text=")
    assert payload["persona"]["collections"][0]["slug"] == "campanha-vz-v1"
