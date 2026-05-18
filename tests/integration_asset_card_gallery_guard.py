#!/usr/bin/env python3
"""POST /assets/{id}/connect refuses gallery targets for non-asset paths."""
from __future__ import annotations

import os
import sys
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


class _Request:
    def __init__(self): self.state = type("S", (), {})()


def main() -> int:
    from fastapi import HTTPException
    from routes import assets as routes_assets
    from services import auth_service, supabase_client

    asset = {
        "id": "a-1", "persona_id": "p-1",
        "knowledge_node_id": "n-asset-1",
        "type": "image",
    }
    parent_gallery = {
        "id": "n-gallery", "persona_id": "p-1", "node_type": "gallery", "slug": "gallery-default",
    }

    edges: list = []

    auth_orig = auth_service.assert_persona_access
    a_orig = supabase_client.get_asset
    n_orig = supabase_client.get_knowledge_node
    s_orig = supabase_client.get_knowledge_node_by_slug
    e_orig = supabase_client.upsert_knowledge_edge
    try:
        auth_service.assert_persona_access = lambda *a, **kw: None
        supabase_client.get_asset = lambda aid: asset if aid == "a-1" else None
        supabase_client.get_knowledge_node = lambda nid: parent_gallery if nid == "n-gallery" else None
        supabase_client.get_knowledge_node_by_slug = lambda slug, persona_id=None, node_type=None: parent_gallery if slug == "gallery-default" else None
        supabase_client.upsert_knowledge_edge = lambda *a, **kw: edges.append((a, kw)) or {"id": "should-not-happen"}

        body = routes_assets.ConnectBody(parent_node_id="gallery-default", relation_type="manual")
        try:
            routes_assets.connect_asset("a-1", body, _Request())
        except HTTPException as exc:
            _assert(exc.status_code == 422, "gallery target on connect returns 422")
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            _assert(detail.get("error") == "gallery_invalid_target", "guard returns explicit error code")
        else:
            raise AssertionError("connect should refuse gallery as parent target")

        _assert(len(edges) == 0, "no edge written when guard fires")
    finally:
        auth_service.assert_persona_access = auth_orig
        supabase_client.get_asset = a_orig
        supabase_client.get_knowledge_node = n_orig
        supabase_client.get_knowledge_node_by_slug = s_orig
        supabase_client.upsert_knowledge_edge = e_orig

    print("PASS integration_asset_card_gallery_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
