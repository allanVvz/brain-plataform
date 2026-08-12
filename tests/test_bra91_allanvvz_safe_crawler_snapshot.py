from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from api.scripts.crawl_brand_catalog import crawl


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "test-artifacts" / "e2e"
API_BASE = os.environ.get("AI_BRAIN_BASE_URL") or os.environ.get("API_BASE") or "http://127.0.0.1:8001"
TOKEN = os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN") or "qa-baita-admin-c3f2c9f6c87842d3a59b9e1c0a8b5d77"
PERSONA_SLUG = "allanvvz"
EXPECTED_COLLECTIONS = ("plantaris", "radar", "juliet")


def _utc_token() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_json(method: str, route: str, *, params: dict[str, Any] | None = None, timeout: float = 90.0) -> dict[str, Any]:
    url = API_BASE.rstrip("/") + route
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-AI-BRAIN-ADMIN-TOKEN": TOKEN,
            "Authorization": f"Bearer {TOKEN}",
        },
        method=method,
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AssertionError(f"{method} {route} -> HTTP {exc.code}: {detail[:1000]}") from exc
    except error.URLError as exc:
        raise AssertionError(f"{method} {route} -> connection failed: {exc}") from exc


def _node_type(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    return str(data.get("node_type") or data.get("content_type") or node.get("node_type") or node.get("type") or "").lower()


def _product_url(base_url: str, handle: str) -> str:
    return f"{base_url.rstrip('/')}/products/{handle.strip('/')}"


def test_bra91_allanvvz_graph_snapshot_and_real_vzlupas_crawler_are_safe() -> None:
    token = _utc_token()
    artifact_path = ARTIFACT_DIR / f"bra91-allanvvz-safe-crawler-snapshot-{token}.json"
    graph = _http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "include_embedded": "true", "mode": "semantic_tree", "max_depth": 6},
        timeout=120,
    )
    catalog = crawl("vzlupas")

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    collections_by_slug = {str(collection.get("slug")): collection for collection in catalog.get("collections") or []}
    selected: dict[str, list[dict[str, Any]]] = {}

    for slug in EXPECTED_COLLECTIONS:
        collection = collections_by_slug.get(slug)
        assert collection, f"missing VZ Lupas collection {slug}"
        products = collection.get("products") or []
        assert len(products) >= 3, f"expected at least 3 real products for {slug}, got {len(products)}"
        selected[slug] = [
            {
                "title": product.get("title"),
                "handle": product.get("handle"),
                "price": product.get("price"),
                "image": product.get("image"),
                "source_url": _product_url(str(catalog.get("base_url")), str(product.get("handle") or "")),
            }
            for product in products[:3]
        ]
        assert all(item["title"] and item["handle"] for item in selected[slug]), f"{slug} products must have title and handle"
        assert all(str(item["source_url"]).startswith("https://www.vzlupas.com/products/") for item in selected[slug])

    artifact = {
        "ok": True,
        "issue": "BRA-91",
        "mode": "safe_no_browser_no_sofia_no_delete",
        "api_base": API_BASE,
        "persona_slug": PERSONA_SLUG,
        "graph_snapshot": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": sorted({_node_type(node) for node in nodes if _node_type(node)}),
            "raw": graph,
        },
        "crawler": {
            "brand_key": catalog.get("brand_key"),
            "base_url": catalog.get("base_url"),
            "collections_checked": list(EXPECTED_COLLECTIONS),
            "selected_products": selected,
            "raw": catalog,
        },
        "safety": {
            "opened_browser": False,
            "sent_sofia_commands": False,
            "hard_delete": False,
            "installed_playwright": False,
        },
    }
    _write_json(artifact_path, artifact)

    assert isinstance(nodes, list), "graph snapshot must include nodes list"
    assert isinstance(edges, list), "graph snapshot must include edges list"
    assert artifact_path.exists(), "safe BRA-91 artifact must be written"
