#!/usr/bin/env python3
"""Purge every Brain media object and its database/graph projections.

Dry-run is the default. Applying requires the exact confirmation token:

    python scripts/purge_all_media.py --apply DELETE_ALL_MEDIA

Run only in the approved production API environment. The script deliberately
keeps the buckets themselves so future uploads continue to work.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

from services import supabase_client


CONFIRMATION = "DELETE_ALL_MEDIA"
MEDIA_BUCKETS = ("assets-derived", "assets-raw", "whatsapp-media")
PROTECTED_NODE_TYPES = {"persona", "embedded", "embed", "gallery"}
PAGE_SIZE = 100


def _rows(query: Any) -> list[dict[str, Any]]:
    result = query.execute()
    data = getattr(result, "data", None)
    return data if isinstance(data, list) else []


def _all_assets() -> list[dict[str, Any]]:
    client = supabase_client.get_client()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _rows(
            client.table("assets").select("*")
            .order("created_at").range(offset, offset + 999)
        )
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def _list_bucket_objects(bucket: str, prefix: str = "") -> list[dict[str, Any]]:
    """Recursively enumerate real objects without printing their paths."""
    storage = supabase_client.get_client().storage.from_(bucket)
    objects: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = storage.list(
            prefix,
            {
                "limit": PAGE_SIZE,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            },
        ) or []
        for item in page:
            value = item if isinstance(item, dict) else vars(item)
            name = str(value.get("name") or "").strip()
            if not name:
                continue
            path = f"{prefix}/{name}" if prefix else name
            # Supabase returns virtual folder entries without an object id and
            # without file metadata. They must be traversed, not removed.
            if value.get("id") is None and value.get("metadata") is None:
                objects.extend(_list_bucket_objects(bucket, path))
            else:
                metadata = value.get("metadata") or {}
                objects.append({
                    "path": path,
                    "size": int(metadata.get("size") or 0),
                })
        if len(page) < PAGE_SIZE:
            return objects
        offset += PAGE_SIZE


def _storage_inventory() -> dict[str, list[dict[str, Any]]]:
    return {bucket: _list_bucket_objects(bucket) for bucket in MEDIA_BUCKETS}


def _assert_safety_gates() -> None:
    client = supabase_client.get_client()
    unsafe_bindings = [
        row for row in _rows(
            client.table("workflow_bindings")
            .select("id,active,connection_status,metadata").eq("active", True)
        )
        if row.get("connection_status") != "safety_paused"
        or str((row.get("metadata") or {}).get("safety_paused")).lower() != "true"
    ]
    if unsafe_bindings:
        raise RuntimeError(
            f"aborted: {len(unsafe_bindings)} active binding(s) are not safety_paused"
        )

    critical_buffers = _rows(
        client.table("lead_buffer").select("id,status")
        .in_("status", ["processing", "awaiting_proof"])
    )
    if critical_buffers:
        raise RuntimeError(
            f"aborted: {len(critical_buffers)} buffer(s) are processing/awaiting_proof"
        )

    validator_sessions = _rows(
        client.table("wa_validator_sessions").select("id,data")
    )
    running = [
        row for row in validator_sessions
        if str((row.get("data") or {}).get("status") or "")
        in {"queued", "starting", "running"}
    ]
    if running:
        raise RuntimeError(
            f"aborted: {len(running)} WA Validator session(s) are active"
        )


def _graph_refs(assets: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    node_ids: set[str] = set()
    edge_ids: set[str] = set()
    item_ids: set[str] = set()
    for asset in assets:
        metadata = asset.get("metadata") or {}
        node_id = asset.get("knowledge_node_id") or metadata.get("knowledge_node_id")
        edge_id = asset.get("gallery_edge_id") or metadata.get("gallery_edge_id")
        item_id = metadata.get("knowledge_item_id")
        if node_id:
            node_ids.add(str(node_id))
        if edge_id:
            edge_ids.add(str(edge_id))
        if item_id:
            item_ids.add(str(item_id))
    return node_ids, edge_ids, item_ids


def _assert_no_protected_nodes(node_ids: set[str]) -> None:
    protected: list[str] = []
    for node_id in sorted(node_ids):
        node = supabase_client.get_knowledge_node(node_id) or {}
        if str(node.get("node_type") or "").strip().lower() in PROTECTED_NODE_TYPES:
            protected.append(node_id)
    if protected:
        raise RuntimeError(
            f"aborted: {len(protected)} asset reference(s) point to protected graph nodes"
        )


def _remove_storage_objects(inventory: dict[str, list[dict[str, Any]]]) -> None:
    client = supabase_client.get_client()
    for bucket, objects in inventory.items():
        paths = [str(row["path"]) for row in objects]
        for index in range(0, len(paths), PAGE_SIZE):
            client.storage.from_(bucket).remove(paths[index:index + PAGE_SIZE])

    remaining = _storage_inventory()
    remaining_count = sum(len(rows) for rows in remaining.values())
    if remaining_count:
        raise RuntimeError(
            f"storage verification failed: {remaining_count} media object(s) remain"
        )


def _delete_database_projections(
    assets: list[dict[str, Any]],
    node_ids: set[str],
    edge_ids: set[str],
    item_ids: set[str],
) -> None:
    client = supabase_client.get_client()

    # Same graph semantics as DELETE /assets/{asset_id}: remove explicit
    # gallery edges and every edge incident to an asset-owned node first.
    all_edge_ids = set(edge_ids)
    if node_ids:
        for edge in supabase_client.list_edges_for_nodes(sorted(node_ids), limit=5000):
            if edge.get("id"):
                all_edge_ids.add(str(edge["id"]))
    for edge_id in sorted(all_edge_ids):
        supabase_client.delete_knowledge_edge(edge_id)
    for node_id in sorted(node_ids):
        supabase_client.delete_knowledge_node(node_id)
    for item_id in sorted(item_ids):
        supabase_client.delete_knowledge_item(item_id)

    asset_ids = [str(row["id"]) for row in assets if row.get("id")]
    for asset_id in asset_ids:
        supabase_client._execute_with_retry(
            client.table("asset_readings").delete().eq("asset_id", asset_id)
        )
        supabase_client._execute_with_retry(
            client.table("assets").delete().eq("id", asset_id)
        )

    remaining_assets = _rows(client.table("assets").select("id").limit(1))
    remaining_storage = _storage_inventory()
    if remaining_assets:
        raise RuntimeError("database verification failed: asset rows remain")
    if any(remaining_storage.values()):
        raise RuntimeError("final verification failed: media objects remain")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        default="",
        help=f"Exact destructive confirmation token: {CONFIRMATION}",
    )
    args = parser.parse_args()
    apply = args.apply == CONFIRMATION

    assets = _all_assets()
    unexpected_buckets = sorted({
        str(row.get("storage_bucket") or "")
        for row in assets
        if row.get("storage_path")
        and str(row.get("storage_bucket") or "") not in MEDIA_BUCKETS
    })
    if unexpected_buckets:
        raise RuntimeError(
            f"aborted: {len(unexpected_buckets)} unexpected storage bucket(s) found"
        )

    inventory = _storage_inventory()
    node_ids, edge_ids, item_ids = _graph_refs(assets)
    _assert_no_protected_nodes(node_ids)
    summary = {
        "mode": "apply" if apply else "dry_run",
        "confirmation_required": CONFIRMATION,
        "assets": len(assets),
        "storage_objects": sum(len(rows) for rows in inventory.values()),
        "storage_bytes": sum(
            int(row.get("size") or 0)
            for rows in inventory.values() for row in rows
        ),
        "buckets": {bucket: len(inventory[bucket]) for bucket in MEDIA_BUCKETS},
        "graph_nodes": len(node_ids),
        "graph_edges": len(edge_ids),
        "knowledge_items": len(item_ids),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)

    if not apply:
        return 0

    _assert_safety_gates()
    _remove_storage_objects(inventory)
    _delete_database_projections(assets, node_ids, edge_ids, item_ids)
    print(json.dumps({
        "status": "completed",
        "deleted_assets": len(assets),
        "deleted_storage_objects": summary["storage_objects"],
        "buckets_preserved": list(MEDIA_BUCKETS),
    }, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
