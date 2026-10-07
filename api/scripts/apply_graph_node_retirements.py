"""Archive the exact GraphBundle nodes approved for retirement.

This is a publication pre-step, not a delete: each listed node row moves from a
published status to ``archived`` with its previous status kept in metadata, so
``--restore`` can bring it back if staging or activation fails. The active graph
publication is unchanged until the normal stage + CAS activation succeeds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


API_DIR = next(
    (
        candidate
        for candidate in (Path(__file__).resolve().parents[1], Path.cwd())
        if (candidate / "services").is_dir()
    ),
    Path(__file__).resolve().parents[1],
)
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402

PUBLISHED_STATUSES = {"approved", "active", "validated", "ativo", "embedded"}
RETIRED_STATUS = "archived"


def plan_retirements(
    bundle: dict[str, Any], node_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retired = (bundle.get("metadata") or {}).get("retired_nodes") or []
    if not isinstance(retired, list):
        raise RuntimeError("retired_nodes_must_be_a_list")
    bundle_ids = {str(node.get("id") or "") for node in bundle.get("nodes") or []}
    rows_by_stable = {
        str((row.get("metadata") or {}).get("graph_json_node_id") or ""): row
        for row in node_rows
        if (row.get("metadata") or {}).get("graph_json_node_id")
    }
    planned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in retired:
        stable_id = str(item.get("id") or "")
        node_type = str(item.get("node_type") or "")
        slug = str(item.get("slug") or "")
        reason = str(item.get("removal_reason") or "")
        if not all((stable_id, node_type, slug, reason)) or stable_id in seen:
            raise RuntimeError(f"invalid_or_duplicate_retirement:{stable_id}")
        if stable_id in bundle_ids:
            raise RuntimeError(f"retired_node_still_in_bundle:{stable_id}")
        seen.add(stable_id)
        row = rows_by_stable.get(stable_id) or next(
            (
                candidate for candidate in node_rows
                if str(candidate.get("node_type") or "") == node_type
                and str(candidate.get("slug") or "") == slug
            ),
            None,
        )
        if row is None:
            planned.append({"id": stable_id, "row_id": "", "reason": reason, "status": "absent"})
            continue
        if (str(row.get("node_type") or ""), str(row.get("slug") or "")) != (node_type, slug):
            raise RuntimeError(f"retirement_identity_mismatch:{stable_id}")
        status = str(row.get("status") or "").lower()
        planned.append({
            "id": stable_id,
            "row_id": str(row.get("id") or ""),
            "reason": reason,
            "status": "published" if status in PUBLISHED_STATUSES else "already_retired",
            "row_status": status,
            "metadata": dict(row.get("metadata") or {}),
        })
    return planned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--approved-draft-checksum", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.apply and args.restore:
        raise RuntimeError("apply_and_restore_are_mutually_exclusive")

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    persona_scope = bundle.get("persona") or {}
    persona_id = str(persona_scope.get("id") or "")
    persona_slug = str(persona_scope.get("slug") or "")
    persona = supabase_client.get_persona(persona_slug)
    if not persona or str(persona.get("id") or "") != persona_id:
        raise RuntimeError("persona_scope_mismatch")
    node_rows, _edge_rows = supabase_client.list_all_knowledge_graph(
        persona_id=persona_id, limit_nodes=10000
    )
    planned = plan_retirements(bundle, node_rows)
    changed = []
    if args.restore:
        for item in planned:
            metadata = item.get("metadata") or {}
            if (item["status"] != "already_retired"
                    or metadata.get("retired_by") != args.actor
                    or metadata.get("graph_bundle_draft_checksum") != args.approved_draft_checksum):
                continue
            restored = dict(metadata)
            previous_status = restored.pop("previous_status", "active")
            restored.pop("retired_by", None)
            restored.pop("retirement_reason", None)
            updated = supabase_client.update_knowledge_node(
                item["row_id"], {"status": previous_status, "metadata": restored},
                mark_related_faqs=False,
            )
            if not updated:
                raise RuntimeError(f"retirement_restore_failed:{item['id']}")
            changed.append(item["id"])
    if args.apply:
        for item in planned:
            if item["status"] != "published":
                continue
            metadata = {
                **item["metadata"],
                "previous_status": item["row_status"],
                "retirement_reason": item["reason"],
                "retired_by": args.actor,
                "graph_bundle_draft_checksum": args.approved_draft_checksum,
            }
            updated = supabase_client.update_knowledge_node(
                item["row_id"], {"status": RETIRED_STATUS, "metadata": metadata},
                mark_related_faqs=False,
            )
            if not updated:
                raise RuntimeError(f"retirement_update_failed:{item['id']}")
            changed.append(item["id"])
        supabase_client.insert_event({
            "event_type": "graph_bundle_nodes_retired",
            "entity_type": "persona",
            "entity_id": persona_id,
            "persona_id": persona_id,
            "payload": {
                "persona_slug": persona_slug,
                "draft_checksum": args.approved_draft_checksum,
                "node_ids": changed,
                "actor": args.actor,
            },
        }, source="scripts.apply_graph_node_retirements")
    print(json.dumps({
        "apply": args.apply,
        "restore": args.restore,
        "persona_slug": persona_slug,
        "planned_count": len(planned),
        "published_count": sum(item["status"] == "published" for item in planned),
        "already_retired_count": sum(item["status"] == "already_retired" for item in planned),
        "absent_count": sum(item["status"] == "absent" for item in planned),
        "changed_node_ids": changed,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
