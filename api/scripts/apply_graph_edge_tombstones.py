"""Soft-disable the exact GraphBundle edges approved for replacement.

This is a publication pre-step, not a delete. The active graph publication is
unchanged until the normal stage + CAS activation succeeds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402


def _active(row: dict[str, Any]) -> bool:
    return (row.get("metadata") or {}).get("active", True) is not False


def plan_tombstones(
    bundle: dict[str, Any],
    node_rows: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reconciliation = (
        (bundle.get("metadata") or {}).get("visual_media_reconciliation") or {}
    )
    tombstones = reconciliation.get("soft_disabled_edges") or []
    if not isinstance(tombstones, list):
        raise RuntimeError("soft_disabled_edges_must_be_a_list")
    declared_count = reconciliation.get("soft_disabled_edge_count")
    if declared_count != len(tombstones):
        raise RuntimeError("soft_disabled_edge_count_mismatch")

    projection_by_stable = {
        str((row.get("metadata") or {}).get("graph_json_node_id") or ""): str(row.get("id") or "")
        for row in node_rows
        if (row.get("metadata") or {}).get("graph_json_node_id")
    }
    planned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tombstones:
        edge_id = str(item.get("id") or "")
        source = str(item.get("source") or "")
        target = str(item.get("target") or "")
        relation = str(item.get("relation_type") or "")
        reason = str(item.get("removal_reason") or "")
        if not all((edge_id, source, target, relation, reason)) or edge_id in seen:
            raise RuntimeError(f"invalid_or_duplicate_tombstone:{edge_id}")
        seen.add(edge_id)
        source_projection = projection_by_stable.get(source)
        target_projection = projection_by_stable.get(target)
        if not source_projection or not target_projection:
            raise RuntimeError(f"tombstone_node_projection_missing:{edge_id}")
        matches = [
            row for row in edge_rows
            if str(row.get("source_node_id") or "") == source_projection
            and str(row.get("target_node_id") or "") == target_projection
            and str(row.get("relation_type") or "") == relation
        ]
        if len(matches) != 1:
            raise RuntimeError(f"tombstone_edge_match_count:{edge_id}:{len(matches)}")
        row = matches[0]
        materialized_id = str((row.get("metadata") or {}).get("graph_json_edge_id") or "")
        if materialized_id and materialized_id != edge_id:
            raise RuntimeError(f"tombstone_edge_id_mismatch:{edge_id}:{materialized_id}")
        planned.append({
            "edge_id": edge_id,
            "row_id": str(row.get("id") or ""),
            "reason": reason,
            "status": "active" if _active(row) else "already_inactive",
            "metadata": dict(row.get("metadata") or {}),
        })
    return planned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--approved-draft-checksum", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    persona_scope = bundle.get("persona") or {}
    persona_id = str(persona_scope.get("id") or "")
    persona_slug = str(persona_scope.get("slug") or "")
    persona = supabase_client.get_persona(persona_slug)
    if not persona or str(persona.get("id") or "") != persona_id:
        raise RuntimeError("persona_scope_mismatch")
    node_rows, edge_rows = supabase_client.list_all_knowledge_graph(
        persona_id=persona_id, limit_nodes=10000
    )
    planned = plan_tombstones(bundle, node_rows, edge_rows)
    changed = []
    if args.apply:
        for item in planned:
            if item["status"] == "already_inactive":
                continue
            metadata = {
                **item["metadata"],
                "active": False,
                "primary_tree": False,
                "removal_reason": item["reason"],
                "graph_bundle_draft_checksum": args.approved_draft_checksum,
                "removed_by": args.actor,
            }
            updated = supabase_client.update_knowledge_edge(
                item["row_id"], {"metadata": metadata}
            )
            if not updated:
                raise RuntimeError(f"tombstone_update_failed:{item['edge_id']}")
            changed.append(item["edge_id"])
        supabase_client.insert_event({
            "event_type": "graph_bundle_edges_soft_disabled",
            "entity_type": "persona",
            "entity_id": persona_id,
            "persona_id": persona_id,
            "payload": {
                "persona_slug": persona_slug,
                "draft_checksum": args.approved_draft_checksum,
                "edge_ids": changed,
                "actor": args.actor,
            },
        }, source="scripts.apply_graph_edge_tombstones")
    print(json.dumps({
        "apply": args.apply,
        "persona_slug": persona_slug,
        "planned_count": len(planned),
        "active_count": sum(item["status"] == "active" for item in planned),
        "already_inactive_count": sum(item["status"] == "already_inactive" for item in planned),
        "changed_edge_ids": changed,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
