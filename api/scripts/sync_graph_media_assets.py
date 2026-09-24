"""Validate or upload graph-declared local media assets; dry-run by default.

Apply is deliberately fail-closed: an existing object with different bytes is
never overwritten, and an existing asset row is reused by bucket/path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path


API_DIR = next(
    (
        candidate
        for candidate in (Path(__file__).resolve().parents[1], Path.cwd())
        if (candidate / "services").is_dir()
    ),
    Path(__file__).resolve().parents[1],
)
ROOT = API_DIR.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import graph_bundle, supabase_client  # noqa: E402


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bundle must be a JSON object")
    return value


def _candidate_rows(bundle_path: Path, *, asset_root: Path | None = None) -> tuple[dict, list[dict]]:
    normalized = graph_bundle.normalize_bundle(_load(bundle_path))
    evidence_root = (asset_root or ROOT).resolve()
    nodes = {str(node["id"]): node for node in normalized["nodes"]}
    edges = normalized["edges"]
    rows: list[dict] = []
    for node in normalized["nodes"]:
        if node["node_type"] != "asset":
            continue
        data = node.get("data") or {}
        media = data.get("media") or {}
        local_value = str(data.get("local_evidence_path") or "")
        if not local_value:
            continue
        local_path = (evidence_root / local_value).resolve()
        local_path.relative_to(evidence_root)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
        if digest != str(media.get("sha256") or "").lower():
            raise ValueError(f"checksum mismatch: {node['id']}")
        parents = sorted({
            edge["source"] for edge in edges
            if edge["target"] == node["id"]
            and edge["relation_type"] in {"contains", "uses_asset", "category_has_asset"}
        })
        galleries = [
            edge["target"] for edge in edges
            if edge["source"] == node["id"] and edge["relation_type"] == "gallery_asset"
        ]
        parent_type = nodes.get(parents[0], {}).get("node_type") if len(parents) == 1 else None
        if parent_type not in {"product", "product_group"}:
            raise ValueError(f"asset must have exactly one product or product_group owner: {node['id']}")
        if len(galleries) != 1 or nodes.get(galleries[0], {}).get("node_type") != "gallery":
            raise ValueError(f"asset must link to exactly one gallery: {node['id']}")
        rows.append({
            "node_id": node["id"],
            "projection_node_id": node["projection_node_id"],
            "product_node_id": parents[0],
            "gallery_node_id": galleries[0],
            "owner_node_id": parents[0],
            "owner_node_type": parent_type,
            "registry_id": str(data.get("registry_id") or media.get("registry_id") or ""),
            "title": node["title"],
            "source": data.get("source"),
            "asset_role": data.get("asset_role"),
            "local_path": str(local_path),
            "bucket": str(media.get("bucket") or ""),
            "path": str(media.get("path") or ""),
            "filename": str(media.get("filename") or local_path.name),
            "mime": str(media.get("mime") or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"),
            "sha256": digest,
            "size": local_path.stat().st_size,
        })
    return normalized, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--expected-file-sha256")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    bundle_path = Path(args.bundle).resolve()
    bundle_path.relative_to(ROOT.resolve())
    file_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if args.expected_file_sha256 and file_sha != args.expected_file_sha256.lower():
        raise RuntimeError("bundle file checksum mismatch")
    normalized, rows = _candidate_rows(bundle_path, asset_root=args.asset_root)
    if args.expected_count is not None and len(rows) != args.expected_count:
        raise RuntimeError(f"expected {args.expected_count} assets, found {len(rows)}")
    result = {
        "apply": args.apply,
        "persona": normalized["persona"],
        "bundle_file_sha256": file_sha,
        "asset_count": len(rows),
        "assets": rows,
    }
    if not args.apply:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    persona = supabase_client.get_persona(normalized["persona"]["slug"])
    if not persona or str(persona.get("id")) != normalized["persona"]["id"]:
        raise RuntimeError("production persona does not match bundle")
    client = supabase_client.get_client()
    mutations = []
    for row in rows:
        data = Path(row["local_path"]).read_bytes()
        try:
            remote = supabase_client.download_from_storage(row["bucket"], row["path"])
        except Exception as exc:
            message = str(exc).lower()
            if not any(marker in message for marker in ("not found", "404", "no such")):
                raise RuntimeError(f"storage preflight failed: {row['node_id']}") from exc
            remote = None
        if remote is not None:
            remote_sha = hashlib.sha256(remote).hexdigest()
            if remote_sha != row["sha256"]:
                raise RuntimeError(f"existing object checksum mismatch: {row['node_id']}")
            url = client.storage.from_(row["bucket"]).get_public_url(row["path"])
            storage_action = "reused"
        else:
            url = supabase_client.upload_to_storage(
                row["bucket"], row["path"], data, row["mime"],
            )
            storage_action = "uploaded"
        payload = {
            "persona_id": persona["id"], "type": "image", "name": row["title"],
            "url": url, "source": "imported", "storage_bucket": row["bucket"],
            "storage_path": row["path"], "mime_type": row["mime"],
            "file_size": row["size"], "original_filename": row["filename"],
            "status": "ready", "approval_status": "approved", "upload_context": "imported",
            "metadata": {
                "source": row["source"], "sha256": row["sha256"],
                "asset_role": row["asset_role"], "graph_node_id": row["node_id"],
                "projection_node_id": row["projection_node_id"],
                "owner_node_id": row["owner_node_id"],
                "owner_node_type": row["owner_node_type"],
                "product_node_id": row["owner_node_id"] if row["owner_node_type"] == "product" else None,
                "gallery_node_id": row["gallery_node_id"],
                "validation_status": "validated",
            },
        }
        existing = (
            client.table("assets").select("id,metadata")
            .eq("persona_id", persona["id"]).eq("storage_bucket", row["bucket"])
            .eq("storage_path", row["path"]).limit(1).execute().data or []
        )
        if existing:
            if row["registry_id"] and str(existing[0]["id"]) != row["registry_id"]:
                raise RuntimeError(f"existing asset registry id mismatch: {row['node_id']}")
            payload["metadata"] = {
                **(existing[0].get("metadata") or {}),
                **payload["metadata"],
            }
            saved = supabase_client.update_asset(str(existing[0]["id"]), payload)
            action = "updated"
        else:
            if row["registry_id"]:
                payload["id"] = row["registry_id"]
            saved = supabase_client.insert_asset(payload)
            action = "inserted"
        mutations.append({
            "storage_action": storage_action,
            "asset_action": action,
            "asset_id": saved.get("id"),
            "node_id": row["node_id"],
            "sha256": row["sha256"],
        })
    print(json.dumps({**result, "mutations": mutations}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
