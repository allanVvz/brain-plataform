"""Read-only inventory of declared initial product photos. Never uploads."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(bundle, evidence_root):
    rows = []
    for node in bundle.get("nodes", []):
        data = node.get("data") or {}
        if node.get("node_type") != "asset" or data.get("asset_role") != "primary_product_media":
            continue
        media = data.get("media") or {}
        relative = data.get("local_evidence_path")
        path = (evidence_root / relative).resolve() if relative else None
        if path and not path.is_relative_to(evidence_root.resolve()):
            raise ValueError("evidence_path_outside_root")
        exists = bool(path and path.is_file())
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
        links = [edge["id"] for edge in bundle.get("edges", [])
                 if edge.get("target") == node["id"] and edge.get("source") == data.get("product_node_id")]
        rows.append({"asset_node_id": node["id"], "product_node_id": data.get("product_node_id"),
                     "bucket": media.get("bucket"), "path": media.get("path"),
                     "expected_sha256": media.get("sha256"), "sha256": digest,
                     "exists": exists, "hash_matches": exists and digest == media.get("sha256"),
                     "edge_ids": links, "action": "reuse_declared_asset"})
    return {"mode": "dry_run", "persona": bundle.get("persona"), "count": len(rows),
            "ready": len(rows) == 4 and all(r["hash_matches"] and r["edge_ids"] for r in rows),
            "production_storage_verified": False, "uploads": 0, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.bundle.read_text(encoding="utf-8")), args.evidence_root), indent=2))
