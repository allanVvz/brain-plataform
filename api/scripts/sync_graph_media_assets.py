"""Validate or upload graph-declared local media assets; dry-run by default."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
ROOT = API_DIR.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import graph_bundle, supabase_client  # noqa: E402


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bundle must be a JSON object")
    return value


def _candidate_rows(bundle_path: Path) -> tuple[dict, list[dict]]:
    normalized = graph_bundle.normalize_bundle(_load(bundle_path))
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
        local_path = (ROOT / local_value).resolve()
        local_path.relative_to(ROOT.resolve())
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
        if digest != str(media.get("sha256") or "").lower():
            raise ValueError(f"checksum mismatch: {node['id']}")
        parents = [
            edge["source"] for edge in edges
            if edge["target"] == node["id"] and edge["relation_type"] in {"contains", "uses_asset"}
        ]
        galleries = [
            edge["target"] for edge in edges
            if edge["source"] == node["id"] and edge["relation_type"] == "gallery_asset"
        ]
        if len(parents) != 1 or nodes.get(parents[0], {}).get("node_type") != "product":
            raise ValueError(f"asset must have exactly one product parent: {node['id']}")
        if len(galleries) != 1 or nodes.get(galleries[0], {}).get("node_type") != "gallery":
            raise ValueError(f"asset must link to exactly one gallery: {node['id']}")
        rows.append({
            "node_id": node["id"],
            "projection_node_id": node["projection_node_id"],
            "product_node_id": parents[0],
            "gallery_node_id": galleries[0],
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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    bundle_path = Path(args.bundle).resolve()
    bundle_path.relative_to(ROOT.resolve())
    file_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if args.expected_file_sha256 and file_sha != args.expected_file_sha256.lower():
        raise RuntimeError("bundle file checksum mismatch")
    normalized, rows = _candidate_rows(bundle_path)
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
        url = supabase_client.upload_to_storage(
            row["bucket"], row["path"], data, row["mime"],
        )
        payload = {
            "persona_id": persona["id"], "type": "image", "name": row["title"],
            "url": url, "source": "imported", "storage_bucket": row["bucket"],
            "storage_path": row["path"], "mime_type": row["mime"],
            "file_size": row["size"], "original_filename": row["filename"],
            "status": "ready", "upload_context": "imported",
            "metadata": {
                "source": row["source"], "sha256": row["sha256"],
                "asset_role": row["asset_role"], "graph_node_id": row["node_id"],
                "projection_node_id": row["projection_node_id"],
                "product_node_id": row["product_node_id"],
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
            saved = supabase_client.update_asset(str(existing[0]["id"]), payload)
            action = "updated"
        else:
            saved = supabase_client.insert_asset(payload)
            action = "inserted"
        mutations.append({"action": action, "asset_id": saved.get("id"), "node_id": row["node_id"]})
    print(json.dumps({**result, "mutations": mutations}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
