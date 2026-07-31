"""P1 contract for product_import_service + Meta integration validation.

Runs fully offline: Supabase is replaced by an in-memory fake store and the
Meta Graph API / crawler are injected via the `fetch=` parameter. Covers:
dedupe, CSV normalize, Meta import (mocked), product+group+asset+copy node
creation with edges, token-non-leak, and validate_meta.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import product_import_service as pis  # noqa: E402
from services import integration_service  # noqa: E402


class _FakeStore:
    """In-memory stand-in for supabase_client knowledge_nodes/edges."""

    def __init__(self) -> None:
        self.nodes: dict[tuple, dict] = {}
        self.edges: list[dict] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"node-{self._seq}"

    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data["node_type"], data["slug"])
        existing = self.nodes.get(key)
        if existing:
            existing["metadata"] = {**(existing.get("metadata") or {}), **(data.get("metadata") or {})}
            existing["tags"] = sorted(set((existing.get("tags") or []) + (data.get("tags") or [])))
            existing["title"] = data.get("title") or existing.get("title")
            existing["summary"] = data.get("summary") or existing.get("summary")
            return existing
        node = {"id": self._next_id(), **data}
        self.nodes[key] = node
        return node

    def upsert_knowledge_edge(self, source_id, target_id, relation_type, *, persona_id=None, weight=None, metadata=None):
        edge = {
            "id": f"edge-{len(self.edges) + 1}",
            "source_node_id": source_id,
            "target_node_id": target_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }
        self.edges.append(edge)
        return edge

    def list_product_nodes(self, *, persona_id=None, **_kw) -> list[dict]:
        return [n for (pid, ntype, _slug), n in self.nodes.items() if ntype == "product" and pid == persona_id]

    # introspection helpers for assertions
    def nodes_of(self, node_type: str) -> list[dict]:
        return [n for (_pid, ntype, _slug), n in self.nodes.items() if ntype == node_type]

    def edges_of(self, relation_type: str) -> list[dict]:
        return [e for e in self.edges if e["relation_type"] == relation_type]


@pytest.fixture()
def store(monkeypatch) -> _FakeStore:
    fake = _FakeStore()
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_node", fake.upsert_knowledge_node)
    monkeypatch.setattr(pis.supabase_client, "upsert_knowledge_edge", fake.upsert_knowledge_edge)
    monkeypatch.setattr(pis.supabase_client, "list_product_nodes", fake.list_product_nodes)
    return fake


_META_ITEMS = [
    {"retailer_id": "SKU-1", "name": "Radar Ev Path Copper", "description": "Oculos esportivo.", "price": "219.00 BRL", "image_url": "https://cdn/x1.jpg", "product_type": "Radar"},
    {"retailer_id": "SKU-2", "name": "Juliet Plasma Gold", "description": "Modelo classico.", "price": "212.30 BRL", "image_url": "https://cdn/x2.jpg", "product_type": "Juliet"},
]


def _meta_fetch(_config):
    return list(_META_ITEMS)


# --------------------------------------------------------------------------- #
# Normalization                                                                 #
# --------------------------------------------------------------------------- #
def test_normalize_price_and_fields() -> None:
    norm = pis.normalize_imported_product(_META_ITEMS[0], provider="meta", catalog_id="CAT-9")
    assert norm["name"] == "Radar Ev Path Copper"
    assert norm["price"] == "219.00"
    assert norm["external_id"] == "SKU-1"
    assert norm["product_group"] == "Radar"
    assert norm["dedupe_key"] == "meta:SKU-1:CAT-9"
    assert norm["image_url"] == "https://cdn/x1.jpg"


# --------------------------------------------------------------------------- #
# Meta import (mocked) + asset/copy/group materialization                       #
# --------------------------------------------------------------------------- #
def test_meta_import_creates_product_group_asset_copy(store: _FakeStore) -> None:
    result = pis.import_products(
        provider="meta", persona_id="p1", persona_slug="vz-lupas",
        config={"catalog_id": "CAT-9"}, fetch=_meta_fetch,
    )
    assert result["created"] == 2 and result["updated"] == 0 and result["skipped"] == 0

    products = store.nodes_of("product")
    assert len(products) == 2
    assert all(p["status"] == "pending_validation" for p in products)
    # group (canonical product_group), asset, copy were created per product
    assert len(store.nodes_of("product_group")) == 2  # Radar, Juliet
    assert len(store.nodes_of("asset")) == 2
    assert len(store.nodes_of("copy")) == 2
    # canonical edges (menu reads product_group_has_product)
    assert len(store.edges_of("product_group_has_product")) == 2
    assert len(store.edges_of("product_image")) == 2
    assert len(store.edges_of("supports_copy")) == 2
    # each product binds to its group via metadata for the cardápio menu
    for p in products:
        assert p["metadata"]["category_slug"] == p["metadata"]["product_group_slug"]
    # asset marked as product image with source ref
    asset = store.nodes_of("asset")[0]
    assert asset["metadata"]["is_product_image"] is True
    assert asset["metadata"]["image_source_url"].startswith("https://cdn/")


def test_no_connection_to_embedded(store: _FakeStore) -> None:
    pis.import_products(provider="meta", persona_id="p1", config={"catalog_id": "CAT-9"}, fetch=_meta_fetch)
    embed_targets = [e for e in store.edges if "embed" in str(e.get("relation_type", "")).lower()]
    assert embed_targets == []
    assert store.nodes_of("embed") == []


# --------------------------------------------------------------------------- #
# Dedupe                                                                        #
# --------------------------------------------------------------------------- #
def test_reimport_dedupes_by_source_external_catalog(store: _FakeStore) -> None:
    pis.import_products(provider="meta", persona_id="p1", config={"catalog_id": "CAT-9"}, fetch=_meta_fetch)
    second = pis.import_products(provider="meta", persona_id="p1", config={"catalog_id": "CAT-9"}, fetch=_meta_fetch)
    assert second["created"] == 0
    assert second["updated"] == 2
    assert len(store.nodes_of("product")) == 2  # no duplicates


def test_different_catalog_is_not_deduped(store: _FakeStore) -> None:
    pis.import_products(provider="meta", persona_id="p1", config={"catalog_id": "CAT-9"}, fetch=_meta_fetch)
    pis.import_products(provider="meta", persona_id="p1", config={"catalog_id": "CAT-OTHER"}, fetch=_meta_fetch)
    # same SKUs but different catalog_id -> distinct dedupe keys -> distinct products
    assert len(store.nodes_of("product")) == 4


# --------------------------------------------------------------------------- #
# CSV import                                                                    #
# --------------------------------------------------------------------------- #
def test_csv_import_normalizes_and_creates(store: _FakeStore) -> None:
    csv_bytes = (
        "name,description,price,external_id,product_group,image_url\n"
        "Splice Carbon,Copy comercial 1,199.00,CSV-1,Splice,https://cdn/s1.jpg\n"
        "Splice Ruby,Copy comercial 2,199.00,CSV-2,Splice,\n"
    ).encode("utf-8")
    result = pis.import_products(provider="csv", persona_id="p1", file_bytes=csv_bytes)
    assert result["created"] == 2
    assert len(store.nodes_of("product")) == 2
    # only the first row had an image -> 1 asset
    assert len(store.nodes_of("asset")) == 1
    # both share the same product_group -> single product_group node
    assert len(store.nodes_of("product_group")) == 1


def test_csv_requires_file_bytes(store: _FakeStore) -> None:
    with pytest.raises(ValueError):
        pis.import_products(provider="csv", persona_id="p1")


# --------------------------------------------------------------------------- #
# Token non-leak                                                                #
# --------------------------------------------------------------------------- #
def test_import_result_never_leaks_token(store: _FakeStore) -> None:
    result = pis.import_products(
        provider="meta", persona_id="p1",
        config={"catalog_id": "CAT-9", "access_token": "SECRET-TOKEN-XYZ"}, fetch=_meta_fetch,
    )
    assert "SECRET-TOKEN-XYZ" not in repr(result)


# --------------------------------------------------------------------------- #
# Meta validation                                                               #
# --------------------------------------------------------------------------- #
def test_validate_meta_healthy_with_injected_fetch() -> None:
    calls = {}

    def fake(token, catalog_id):
        calls["token"], calls["catalog"] = token, catalog_id
        return {"data": [{"id": "1"}]}

    status, error, latency = integration_service.validate_meta("good-token", "CAT-9", fetch=fake)
    assert status == "healthy" and error is None
    assert calls == {"token": "good-token", "catalog": "CAT-9"}


def test_validate_meta_rejects_placeholder_and_missing_catalog() -> None:
    with pytest.raises(integration_service.IntegrationValidationError):
        integration_service.validate_meta("changeme", "CAT-9", fetch=lambda *_: None)
    with pytest.raises(integration_service.IntegrationValidationError):
        integration_service.validate_meta("good-token", "", fetch=lambda *_: None)


def test_shopify_url_normalization_adds_scheme() -> None:
    assert pis._normalize_url("vzlupas.com") == "https://vzlupas.com"
    assert pis._normalize_url("http://x.com") == "http://x.com"
    assert pis._normalize_url("https://x.com/c/all") == "https://x.com/c/all"
    assert pis._normalize_url("  loja.com  ") == "https://loja.com"
    assert pis._normalize_url("") == ""


_SHOPIFY_ITEMS = [
    {"title": "Radar A", "description": "d", "prices": ["219.00"], "image_url": "https://cdn/r1.jpg", "external_id": "radar-a", "product_group": "Radar", "source": "shopify_json"},
    {"title": "Radar B", "description": "d", "prices": ["219.00"], "image_url": "https://cdn/r2.jpg", "external_id": "radar-b", "product_group": "Radar", "source": "shopify_json"},
    {"title": "Juliet A", "description": "d", "prices": ["212.00"], "image_url": None, "external_id": "juliet-a", "product_group": "Juliet", "source": "shopify_json"},
    {"title": "Avulso", "description": "d", "prices": [], "external_id": "avulso", "source": "shopify_json"},
]


def test_preview_groups_products_by_collection() -> None:
    preview = pis.preview_products(provider="shopify", config={"url": "vzlupas.com"}, fetch=lambda _c: list(_SHOPIFY_ITEMS))
    labels = [c["label"] for c in preview["collections"]]
    assert labels == ["Radar", "Juliet", "Sem grupo"]
    assert preview["total"] == 4
    radar = preview["collections"][0]
    assert radar["count"] == 2
    assert radar["products"][0]["thumbnail"] == "https://cdn/r1.jpg"
    assert radar["products"][0]["has_image"] is True
    # raw item is carried back so confirm imports without re-crawling
    assert radar["products"][0]["item"]["external_id"] == "radar-a"
    assert preview["source_url"] == "https://vzlupas.com"


def test_import_items_subset_only_imports_selected(store: _FakeStore) -> None:
    selected = [_SHOPIFY_ITEMS[0], _SHOPIFY_ITEMS[1]]  # only the 2 Radar items
    result = pis.import_products(provider="shopify", persona_id="p1", items=selected)
    assert result["created"] == 2
    assert len(store.nodes_of("product")) == 2


def test_import_downloads_images_when_flag_set(store: _FakeStore, monkeypatch) -> None:
    uploaded: dict = {}

    def fake_upload(bucket, path, data, content_type="application/octet-stream"):
        uploaded["call"] = (bucket, path, content_type, len(data))
        return f"https://storage.local/{bucket}/{path}"

    monkeypatch.setattr(pis.supabase_client, "upload_to_storage", fake_upload)

    result = pis.import_products(
        provider="shopify", persona_id="p1", items=[_SHOPIFY_ITEMS[0]],
        download_images=True, image_downloader=lambda _url: (b"\x89PNG-bytes", "image/png"),
    )
    assert result["images_downloaded"] == 1
    asset = store.nodes_of("asset")[0]["metadata"]
    assert asset["downloaded"] is True
    assert asset["storage_bucket"] == "assets-raw"
    assert asset["url"].startswith("https://storage.local/assets-raw/")
    # origin reference preserved
    assert asset["image_source_url"] == "https://cdn/r1.jpg"
    assert uploaded["call"][2] == "image/png"


def test_import_image_download_failure_falls_back_to_reference(store: _FakeStore) -> None:
    def boom(_url):
        raise RuntimeError("network down")

    result = pis.import_products(
        provider="shopify", persona_id="p1", items=[_SHOPIFY_ITEMS[0]],
        download_images=True, image_downloader=boom,
    )
    assert result["created"] == 1
    assert result["images_downloaded"] == 0
    asset = store.nodes_of("asset")[0]["metadata"]
    assert asset["downloaded"] is False
    assert "download_error" in asset
    # still keeps the external URL as reference/thumbnail
    assert asset["image_source_url"] == "https://cdn/r1.jpg"
    assert asset["url"] == "https://cdn/r1.jpg"


def test_import_without_download_keeps_url_reference(store: _FakeStore) -> None:
    pis.import_products(provider="shopify", persona_id="p1", items=[_SHOPIFY_ITEMS[0]])
    asset = store.nodes_of("asset")[0]["metadata"]
    assert "downloaded" not in asset
    assert asset["url"] == "https://cdn/r1.jpg"
    assert asset["image_source_url"] == "https://cdn/r1.jpg"


def test_normalize_credentials_meta_splits_secret_and_config() -> None:
    secret, config = integration_service.normalize_credentials(
        "meta", {"access_token": "tok", "business_id": "biz", "catalog_id": "cat"}
    )
    assert secret == "tok"
    assert config == {"business_id": "biz", "catalog_id": "cat"}


def test_llm_integrations_are_persona_managed_and_validate_format() -> None:
    openai = integration_service.get_catalog_item("openai")
    anthropic = integration_service.get_catalog_item("anthropic")
    assert openai["scope"] == "persona"
    assert openai["user_managed"] is True
    assert anthropic["scope"] == "persona"
    assert anthropic["user_managed"] is True

    secret, config = integration_service.normalize_credentials("openai", {"api_key": "sk-test-123"})
    assert secret == "sk-test-123"
    assert config == {}

    with pytest.raises(integration_service.IntegrationValidationError):
        integration_service.normalize_credentials("openai", {"api_key": "changeme"})
    with pytest.raises(integration_service.IntegrationValidationError):
        integration_service.normalize_credentials("anthropic", {"api_key": "sk-test-123"})


def test_user_llm_secret_is_not_returned_from_state(monkeypatch) -> None:
    rows: dict[tuple[str, str], dict] = {}

    def fake_upsert(payload: dict) -> dict:
        rows[(payload["user_id"], payload["service"])] = dict(payload)
        return rows[(payload["user_id"], payload["service"])]

    def fake_get(user_id: str, service: str) -> dict | None:
        row = rows.get((user_id, service))
        return dict(row) if row else None

    monkeypatch.setattr(integration_service.supabase_client, "upsert_user_integration_connection", fake_upsert)
    monkeypatch.setattr(integration_service.supabase_client, "get_user_integration_connection", fake_get)

    state = integration_service.save_user_integration(
        "user-1",
        "openai",
        enabled=True,
        credentials={"api_key": "sk-test-secret"},
    )

    stored = rows[("user-1", "openai")]
    assert stored["secret_ciphertext"] != "sk-test-secret"
    assert state["configured"] is True
    assert state["enabled"] is True
    assert state["status"] == "connected"
    assert "secret_ciphertext" not in state
    assert "sk-test-secret" not in str(state)
