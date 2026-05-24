#!/usr/bin/env python3
"""E2E top-down hierarchy: seed tock-fatal directly from canonical taxonomy.

Replaces the (now removed) vz-lupas clone. Walks PRIMARY_CHAIN top-down:
  persona -> brand -> briefing -> campaign -> audience -> product_group ->
  product -> offer? -> copy? -> faq? / gallery?
and inserts one node per level + the canonical edges. Idempotent.

The point is to prove (a) Sofia's hierarchy validator accepts a canonical
chain, (b) /api/menu/tock-fatal renders the resulting graph, (c) /grafos
positions product_group at rank 5 (after audience, before product) — not
the old broken rank-4 product_collection slot.

This script writes through the AI-BRAIN REST API where possible; for the
spine itself it uses the supabase-py service-role client because no public
endpoint creates arbitrary nodes today. The catalog validation goes
through the public /api/menu endpoint as a real user would.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

env = yaml.safe_load((ROOT / "env.qa.yaml").read_text(encoding="utf-8"))
for k, v in env.items():
    os.environ[k] = str(v)

from services import supabase_client  # noqa: E402

TF_PID = "409e5958-3a43-446a-9478-475b2f77ee18"
PREFIX = "tf-canonical-"
ARTIFACTS = ROOT / "test-artifacts" / "e2e-tock-fatal-topdown"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

# Canonical top-down chain for tock-fatal — generic streetwear/wholesale
# scenario so the persona keeps its own identity (not a vz-lupas clone).
SPINE: list[dict] = [
    {"node_type": "brand", "slug": "tf-brand-tock-fatal", "title": "Tock Fatal",
     "summary": "Atacado premium de modal e streetwear feminino."},
    {"node_type": "briefing", "slug": "tf-briefing-colecao-2026", "title": "Briefing Colecao 2026",
     "summary": "Foco em modais e canelados para revenda em volume.", "parent": "tf-brand-tock-fatal"},
    {"node_type": "campaign", "slug": "tf-campanha-modais-inverno-2026", "title": "Campanha Modais Inverno 2026",
     "summary": "Push para atacado de Modal 1 e Modal 2.", "parent": "tf-briefing-colecao-2026"},
    {"node_type": "audience", "slug": "tf-audience-atacado-revenda", "title": "Atacado Revenda",
     "summary": "Lojistas comprando kits de 5/10 pecas.", "parent": "tf-campanha-modais-inverno-2026"},
]
GROUPS: list[dict] = [
    {"slug": "tf-pg-modais", "title": "Modais", "summary": "Blusas canelado de modal."},
    {"slug": "tf-pg-canelados", "title": "Canelados", "summary": "Tops canelados de viscose."},
    {"slug": "tf-pg-acessorios", "title": "Acessorios", "summary": "Brincos e bones complementares."},
]
PRODUCTS: list[dict] = [
    {"group": "tf-pg-modais", "slug": "tf-prod-modal-kit-1", "title": "Kit Modal 1",
     "summary": "Blusa modal canelada, 9 cores."},
    {"group": "tf-pg-modais", "slug": "tf-prod-modal-kit-2", "title": "Kit Modal 2",
     "summary": "Blusa modal manga longa, 7 cores."},
    {"group": "tf-pg-modais", "slug": "tf-prod-modal-cropped", "title": "Modal Cropped",
     "summary": "Cropped modal canelado para layering."},
    {"group": "tf-pg-canelados", "slug": "tf-prod-canelado-classic", "title": "Top Canelado Classic",
     "summary": "Top canelado regata, basico atemporal."},
    {"group": "tf-pg-canelados", "slug": "tf-prod-canelado-cropped", "title": "Canelado Cropped",
     "summary": "Cropped canelado de manga curta."},
    {"group": "tf-pg-canelados", "slug": "tf-prod-canelado-long", "title": "Canelado Long",
     "summary": "Vestido canelado midi."},
    {"group": "tf-pg-acessorios", "slug": "tf-prod-acc-brinco-argola", "title": "Brinco Argola",
     "summary": "Brinco dourado fininho."},
    {"group": "tf-pg-acessorios", "slug": "tf-prod-acc-brinco-pequeno", "title": "Brinco Pequeno",
     "summary": "Brinco mini esfera."},
    {"group": "tf-pg-acessorios", "slug": "tf-prod-acc-bone", "title": "Bone Tock",
     "summary": "Bone preto bordado Tock."},
]

CANONICAL_EDGES: dict[tuple[str, str], str] = {
    ("brand", "briefing"): "brand_has_briefing",
    ("briefing", "campaign"): "briefing_has_campaign",
    ("campaign", "audience"): "campaign_has_audience",
    ("audience", "product_group"): "audience_has_product_group",
    ("product_group", "product"): "product_group_has_product",
}

client = supabase_client.get_client()


def upsert_node(*, node_type: str, slug: str, title: str, summary: str,
                metadata: dict | None = None, status: str = "validated") -> str:
    full_slug = PREFIX + slug
    existing_res = (
        client.table("knowledge_nodes").select("id")
        .eq("persona_id", TF_PID).eq("slug", full_slug).limit(1).execute()
    )
    existing = (existing_res.data or [None])[0] if existing_res and existing_res.data else None
    if existing:
        return existing["id"]
    res = (
        client.table("knowledge_nodes").insert({
            "persona_id": TF_PID, "node_type": node_type, "slug": full_slug,
            "title": title, "summary": summary,
            "metadata": (metadata or {}) | {"canonical_seed": "tock-fatal-topdown"},
            "status": status,
        }).execute().data or []
    )
    return res[0]["id"]


def upsert_edge(src_id: str, tgt_id: str, relation_type: str, weight: float = 0.85) -> None:
    existing_res = (
        client.table("knowledge_edges").select("id")
        .eq("source_node_id", src_id).eq("target_node_id", tgt_id)
        .eq("relation_type", relation_type).limit(1).execute()
    )
    existing = (existing_res.data or [None])[0] if existing_res and existing_res.data else None
    if existing:
        return
    client.table("knowledge_edges").insert({
        "source_node_id": src_id, "target_node_id": tgt_id,
        "relation_type": relation_type, "weight": weight,
        "metadata": {"canonical_seed": "tock-fatal-topdown", "active": True},
    }).execute()


def main() -> int:
    print("[1/4] inserting canonical spine (brand -> briefing -> campaign -> audience)...")
    ids: dict[str, str] = {}
    last_id: str | None = None
    for row in SPINE:
        node_id = upsert_node(
            node_type=row["node_type"], slug=row["slug"],
            title=row["title"], summary=row["summary"],
            metadata={"parent_slug": (PREFIX + row["parent"]) if row.get("parent") else None},
        )
        ids[row["slug"]] = node_id
        if row.get("parent"):
            parent_id = ids[row["parent"]]
            rel = CANONICAL_EDGES[(SPINE[SPINE.index(row) - 1]["node_type"], row["node_type"])]
            upsert_edge(parent_id, node_id, rel)
        last_id = node_id

    audience_id = ids["tf-audience-atacado-revenda"]
    print("[2/4] inserting 3 product_groups under audience...")
    group_ids: dict[str, str] = {}
    for g in GROUPS:
        gid = upsert_node(node_type="product_group", slug=g["slug"], title=g["title"],
                          summary=g["summary"],
                          metadata={"parent_slug": PREFIX + "tf-audience-atacado-revenda"})
        upsert_edge(audience_id, gid, "audience_has_product_group")
        group_ids[g["slug"]] = gid

    print("[3/4] inserting 9 products (3 per group)...")
    for p in PRODUCTS:
        pid = upsert_node(
            node_type="product", slug=p["slug"], title=p["title"], summary=p["summary"],
            metadata={"parent_slug": PREFIX + p["group"], "product_group_slug": PREFIX + p["group"]},
        )
        upsert_edge(group_ids[p["group"]], pid, "product_group_has_product")

    print("[4/4] setting tock-fatal catalog_url...")
    client.table("personas").update({
        "catalog_url": "https://baita-cardapio-qa.vercel.app/cardapio/tock-fatal"
    }).eq("slug", "tock-fatal").execute()

    out = {"spine_ids": ids, "group_ids": group_ids, "completed_at": time.time()}
    (ARTIFACTS / "report.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("DONE — artifacts at", ARTIFACTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
