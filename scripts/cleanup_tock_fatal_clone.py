#!/usr/bin/env python3
"""Hard-delete every row cloned from vz-lupas into tock-fatal in QA.

Use after the e2e clone experiment to leave tock-fatal back at its
original seed state. Safe to re-run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

env = yaml.safe_load((ROOT / "env.qa.yaml").read_text(encoding="utf-8"))
for k, v in env.items():
    os.environ[k] = str(v)

from services import supabase_client  # noqa: E402

TF_PID = "409e5958-3a43-446a-9478-475b2f77ee18"
client = supabase_client.get_client()

# 1. List every cloned node id
node_rows = (
    client.table("knowledge_nodes")
    .select("id")
    .eq("persona_id", TF_PID)
    .execute().data or []
)
node_ids: list[str] = []
for row in node_rows:
    full = (
        client.table("knowledge_nodes").select("id,metadata")
        .eq("id", row["id"]).maybe_single().execute().data
    )
    if not full:
        continue
    meta = full.get("metadata") or {}
    if meta.get("cloned_from_persona") == "vz-lupas":
        node_ids.append(row["id"])

print(f"cloned tock-fatal nodes: {len(node_ids)}")

# 2. Delete edges that touch any cloned node
edges_deleted = 0
if node_ids:
    for chunk_start in range(0, len(node_ids), 100):
        chunk = node_ids[chunk_start:chunk_start + 100]
        res_src = client.table("knowledge_edges").delete().in_("source_node_id", chunk).execute()
        res_tgt = client.table("knowledge_edges").delete().in_("target_node_id", chunk).execute()
        edges_deleted += len(res_src.data or []) + len(res_tgt.data or [])
print(f"edges deleted: {edges_deleted}")

# 3. Delete the cloned assets rows (filtered by metadata.cloned_from_persona)
asset_rows = (
    client.table("assets").select("id,metadata")
    .eq("persona_id", TF_PID).execute().data or []
)
cloned_asset_ids = [
    r["id"] for r in asset_rows
    if (r.get("metadata") or {}).get("cloned_from_persona") == "vz-lupas"
]
if cloned_asset_ids:
    client.table("assets").delete().in_("id", cloned_asset_ids).execute()
print(f"assets deleted: {len(cloned_asset_ids)}")

# 4. Delete the cloned nodes
if node_ids:
    for chunk_start in range(0, len(node_ids), 100):
        chunk = node_ids[chunk_start:chunk_start + 100]
        client.table("knowledge_nodes").delete().in_("id", chunk).execute()
print(f"nodes deleted: {len(node_ids)}")

# 5. Clear catalog_url on tock-fatal
client.table("personas").update({"catalog_url": None}).eq("slug", "tock-fatal").execute()
print("tock-fatal catalog_url cleared")
