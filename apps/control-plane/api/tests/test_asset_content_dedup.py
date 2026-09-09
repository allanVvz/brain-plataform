from __future__ import annotations

import asyncio
import base64
import hashlib
from types import SimpleNamespace

from repositories import control_plane
from routes import assets
from routes import kb_intake
from services import asset_pipeline
from services.asset_identity import image_dimensions


class _Upload:
    filename = "Produto final.JPEG"
    content_type = "image/jpeg"

    def __init__(self, content: bytes):
        self._content = content

    async def read(self) -> bytes:
        return self._content


def test_content_address_ignores_filename_and_is_persona_scoped():
    content = b"same immutable image"
    digest = hashlib.sha256(content).hexdigest()

    first = assets._content_addressed_path("persona-1", digest, "look A.JPG", "image/jpeg")
    second = assets._content_addressed_path("persona-1", digest, "look B.JPG", "image/jpeg")

    assert first == second == f"persona-1/sha256/{digest}.jpg"
    assert assets._content_addressed_path("persona-2", digest, "look.jpg", "image/jpeg") != first


def test_image_dimensions_reads_raster_metadata():
    one_pixel_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    assert image_dimensions(one_pixel_png, "image/png") == (1, 1)
    assert image_dimensions(one_pixel_png, "application/octet-stream") is None


def test_reservation_reuses_winner_after_unique_race(monkeypatch):
    winner = {"id": "asset-winner", "persona_id": "persona-1", "content_sha256": "a" * 64}
    reads = iter([None, winner])
    monkeypatch.setattr(control_plane, "get_asset_by_content_sha256", lambda *_args: next(reads))

    def duplicate(_payload):
        raise RuntimeError("23505 duplicate key value violates unique constraint")

    monkeypatch.setattr(control_plane, "insert_asset", duplicate)

    row, created = control_plane.reserve_asset_by_content_sha256(
        {"persona_id": "persona-1", "content_sha256": "A" * 64, "name": "same.jpg"}
    )

    assert created is False
    assert row == winner


def test_duplicate_upload_reuses_row_without_storage_or_pipeline(monkeypatch):
    content = b"already uploaded"
    digest = hashlib.sha256(content).hexdigest()
    existing = {
        "id": "asset-1",
        "persona_id": "persona-1",
        "content_sha256": digest,
        "status": "ready",
        "approval_status": "pending",
        "name": "Existing",
        "storage_bucket": "assets-raw",
        "storage_path": f"persona-1/sha256/{digest}.jpg",
        "metadata": {},
    }
    monkeypatch.setattr(assets.supabase_client, "reserve_asset_by_content_sha256", lambda _payload: (existing, False))
    monkeypatch.setattr(assets.supabase_client, "asset_display_url", lambda _row: "https://cdn/asset-1")
    monkeypatch.setattr(
        assets,
        "_ensure_asset_graph_contract",
        lambda **_kwargs: {"asset": existing, "asset_node": {"id": "node-1"}},
    )
    monkeypatch.setattr(
        assets.supabase_client,
        "upload_to_storage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not upload duplicate")),
    )
    monkeypatch.setattr(
        assets,
        "run_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not re-read duplicate")),
    )

    result = asyncio.run(
        assets._upload_asset_impl(
            _Upload(content),
            "persona-1",
            "brand",
            {"id": "product-1", "slug": "look", "node_type": "product", "title": "Look"},
            "product_image",
        )
    )

    assert result["deduplicated"] is True
    assert result["upload_in_progress"] is False
    assert result["asset_id"] == "asset-1"
    assert result["content_sha256"] == digest


def test_new_upload_reserves_first_and_never_overwrites_storage(monkeypatch):
    content = b"new image bytes"
    digest = hashlib.sha256(content).hexdigest()
    calls: list[tuple] = []

    def reserve(payload):
        calls.append(("reserve", payload.copy()))
        return ({**payload, "id": "asset-new"}, True)

    def upload(bucket, path, body, content_type, **options):
        calls.append(("storage", bucket, path, body, content_type, options))
        return "https://cdn/new"

    bundle = SimpleNamespace(
        classification=SimpleNamespace(kind="image_product"),
        rename=SimpleNamespace(title="Produto", asset_function="product_image", tags=["produto"], slug="produto"),
        reading_status="completed",
        extracted_text="",
        visual_summary="Produto fotografado",
        video_mock=False,
        rows_to_persist=[],
        ocr=None,
        to_summary=lambda: {"reading_status": "completed"},
    )
    monkeypatch.setattr(assets.supabase_client, "reserve_asset_by_content_sha256", reserve)
    monkeypatch.setattr(assets.supabase_client, "upload_to_storage", upload)
    monkeypatch.setattr(assets, "run_pipeline", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(assets, "compose_markdown", lambda *_args, **_kwargs: "# Asset")
    monkeypatch.setattr(assets.supabase_client, "get_or_create_manual_source", lambda: {"id": "source-1"})
    monkeypatch.setattr(assets.supabase_client, "insert_knowledge_item", lambda _payload: {"id": "item-1"})

    def update(asset_id, patch):
        calls.append(("update", asset_id, patch.copy()))
        return {"id": asset_id, "persona_id": "persona-1", "content_sha256": digest, **patch}

    monkeypatch.setattr(assets.supabase_client, "update_asset", update)
    monkeypatch.setattr(
        assets,
        "_ensure_asset_graph_contract",
        lambda **kwargs: {
            "asset": kwargs["asset_row"],
            "asset_node": {"id": "node-1", "slug": "asset"},
            "parent_edge": {"id": "edge-parent"},
            "landing_edge": {"id": "edge-slot"},
            "gallery_edge": {"id": "edge-gallery"},
        },
    )
    monkeypatch.setattr(assets, "_append_image_ref_to_parent_card", lambda *_args: False)

    result = asyncio.run(
        assets._upload_asset_impl(
            _Upload(content),
            "persona-1",
            "brand",
            {"id": "product-1", "slug": "look", "node_type": "product", "title": "Look"},
            "product_image",
        )
    )

    assert [call[0] for call in calls[:2]] == ["reserve", "storage"]
    reservation = calls[0][1]
    assert reservation["content_sha256"] == digest
    assert reservation["approval_status"] == "pending"
    storage = calls[1]
    assert storage[2] == f"persona-1/sha256/{digest}.jpeg"
    assert storage[5] == {"upsert": False, "reuse_existing": True}
    assert result["deduplicated"] is False
    assert result["content_sha256"] == digest


def test_approve_writes_canonical_top_level_status(monkeypatch):
    asset = {
        "id": "asset-1",
        "persona_id": "persona-1",
        "status": "ready",
        "approval_status": "pending",
        "metadata": {"knowledge_item_id": "item-1", "knowledge_node_id": "node-1"},
    }
    updates: list[dict] = []
    monkeypatch.setattr(assets.supabase_client, "get_asset", lambda _id: asset)
    monkeypatch.setattr(assets.auth_service, "assert_persona_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(assets.auth_service, "current_user", lambda _request: {"id": "operator-1"})
    monkeypatch.setattr(
        assets,
        "_validate_asset_approval",
        lambda _asset: {"ok": True, "connections": [{"parent_node": {"id": "product-1"}}]},
    )
    monkeypatch.setattr(assets.supabase_client, "get_knowledge_node", lambda _id: {"id": "product-1"})

    def update(_id, patch):
        updates.append(patch)
        return {**asset, **patch}

    monkeypatch.setattr(assets.supabase_client, "update_asset", update)
    monkeypatch.setattr(assets.supabase_client, "update_knowledge_item", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(assets.supabase_client, "update_knowledge_node", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(assets, "_publish_asset_path_to_canonical_graph", lambda **_kwargs: {"version": 1})
    monkeypatch.setattr(assets, "_log_asset_flow", lambda *_args, **_kwargs: None)

    result = assets.approve_asset_route("asset-1", object())

    assert updates[0]["approval_status"] == "approved"
    assert "validation_status" not in updates[0]["metadata"]
    assert result["asset"]["approval_status"] == "approved"


def test_sofia_upload_reuses_same_canonical_asset(monkeypatch):
    content = b"shared with Sofia"
    digest = hashlib.sha256(content).hexdigest()
    existing = {
        "id": "asset-shared",
        "persona_id": "persona-1",
        "content_sha256": digest,
        "status": "ready",
        "approval_status": "pending",
        "storage_bucket": "assets-raw",
        "storage_path": f"persona-1/sha256/{digest}.jpeg",
        "metadata": {},
    }
    bundle = SimpleNamespace(
        classification=SimpleNamespace(kind="image_product"),
        rename=SimpleNamespace(title="Produto", asset_function=None, tags=[], slug="produto"),
        reading_status="completed",
        extracted_text="",
        visual_summary="Produto",
        video_mock=False,
        rows_to_persist=[],
        ocr=None,
        ai_fallback=None,
        to_summary=lambda: {"reading_status": "completed"},
    )
    session = {"user_id": "user-1", "persona_id": "persona-1", "persona_slug": "brand"}
    monkeypatch.setattr(kb_intake, "_assert_session_access", lambda *_args: session)
    monkeypatch.setattr(
        kb_intake.integration_service,
        "get_enabled_user_secret",
        lambda *_args: None,
        raising=False,
    )
    monkeypatch.setattr(kb_intake, "get_session", lambda _id: session)
    monkeypatch.setattr(kb_intake, "prune_unpersisted_asset_readings", lambda _session: 0)
    monkeypatch.setattr(kb_intake.supabase_client, "reserve_asset_by_content_sha256", lambda _payload: (existing, False))
    monkeypatch.setattr(kb_intake.supabase_client, "asset_display_url", lambda _row: "https://cdn/shared")
    monkeypatch.setattr(
        kb_intake.supabase_client,
        "insert_kb_intake",
        lambda _payload: {},
        raising=False,
    )
    monkeypatch.setattr(
        kb_intake.supabase_client,
        "upload_to_storage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not upload duplicate")),
    )
    monkeypatch.setattr(asset_pipeline, "run_pipeline", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(kb_intake, "attach_reading", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kb_intake, "chat", lambda *_args, **_kwargs: {})

    result = asyncio.run(
        kb_intake.upload_file(
            object(),
            session_id="session-1",
            message="",
            file=_Upload(content),
        )
    )

    assert result["asset_id"] == "asset-shared"
    assert result["content_sha256"] == digest
    assert result["deduplicated"] is True
