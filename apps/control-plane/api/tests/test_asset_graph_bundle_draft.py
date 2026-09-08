from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from routes import assets


def test_asset_upload_operations_stay_inside_draft_and_keep_product_media_exact():
    draft = {"bundle": {"nodes": [
        {"id": "gallery", "node_type": "gallery", "slug": "gallery", "status": "active"},
        {"id": "group", "node_type": "product_group", "slug": "vestidos", "status": "validated"},
        {"id": "product", "node_type": "product", "slug": "dress", "status": "validated"},
        {"id": "retail", "node_type": "brand", "slug": "retail", "status": "validated"},
        {"id": "wholesale", "node_type": "brand", "slug": "wholesale", "status": "validated"},
    ], "edges": [
        {"id": "group-product", "source": "group", "target": "product", "relation_type": "contains"},
    ]}}
    operations = assets._asset_draft_operations(
        draft=draft, parent_node=draft["bundle"]["nodes"][2],
        asset_row={"id": "registry-1"}, title="Dress photo", summary="",
        asset_type="image", asset_function="vitrine",
        sha256="sha256:" + "a" * 64, storage_bucket="assets-raw",
        storage_path="persona/dress.jpg", mime="image/jpeg",
        shared_branch_hints='["retail", "wholesale"]',
    )
    node = operations[0]["node"]
    assert node["data"]["blob"]["registry_id"] == "registry-1"
    assert node["data"]["blob"]["sha256"] == "sha256:" + "a" * 64
    edges = [item["edge"] for item in operations if item["op"] == "add_edge"]
    assert any(edge["source"] == "product" and edge["relation_type"] == "uses_asset" for edge in edges)
    assert not any(edge["source"] == "group" for edge in edges)
    assert any(edge["source"] == "asset:registry-1" and edge["target"] == "gallery" and edge["relation_type"] == "gallery_asset" for edge in edges)
    assert all(edge["metadata"].get("primary_tree") is False for edge in edges if edge["source"] in {"retail", "wholesale"})


def test_explicit_group_upload_uses_cover_slot():
    draft = {"bundle": {"nodes": [
        {"id": "gallery", "node_type": "gallery", "slug": "gallery", "status": "active"},
        {"id": "group", "node_type": "product_group", "slug": "vestidos", "status": "validated"},
    ], "edges": []}}
    operations = assets._asset_draft_operations(
        draft=draft, parent_node=draft["bundle"]["nodes"][1],
        asset_row={"id": "registry-cover"}, title="Cover", summary="",
        asset_type="image", asset_function="vitrine",
        sha256="sha256:" + "b" * 64, storage_bucket="assets-raw",
        storage_path="persona/cover.jpg", mime="image/jpeg", shared_branch_hints=None,
    )
    group_edge = next(item["edge"] for item in operations if item["op"] == "add_edge" and item["edge"]["source"] == "group")
    assert group_edge["metadata"]["page_binding"]["slot_key"] == "product_group_cover"


def test_upload_compensation_removes_registry_before_exact_objects(monkeypatch):
    calls = []
    monkeypatch.setattr(assets.supabase_client, "delete_asset_registry_row", lambda asset_id: calls.append(("row", asset_id)))
    monkeypatch.setattr(assets.supabase_client, "remove_from_storage", lambda bucket, path: calls.append((bucket, path)))
    monkeypatch.setattr(assets, "_log_asset_flow", lambda *_args, **_kwargs: None)

    assets._compensate_asset_upload(
        asset_id="asset-1",
        objects=[("assets-raw", "p/raw.jpg"), ("assets-derived", "p/preview.jpg")],
        persona_id="persona-1",
    )

    assert calls == [
        ("assets-derived", "p/preview.jpg"),
        ("assets-raw", "p/raw.jpg"),
        ("row", "asset-1"),
    ]


def test_upload_has_no_knowledge_bucket_fallback():
    source = Path(assets.__file__).read_text(encoding="utf-8")
    upload_body = source[source.index("async def _upload_asset_impl"):source.index("# ── GET /assets")]
    assert 'storage_bucket = "knowledge"' not in upload_body
