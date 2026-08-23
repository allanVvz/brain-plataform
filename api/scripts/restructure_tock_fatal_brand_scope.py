"""Re-scope the Tock Fatal bundle so each channel's content lives on its brand.

Why this exists
---------------
Every product carries two offers and two copies -- one retail, one wholesale --
and today all four hang off the shared ``product`` node. Branch closure walks
the primary tree, so anything reachable from a shared product is reachable from
both branches: a retail customer can be quoted the wholesale price. The v8
"make it visible" repair made this worse by rooting 165 edges at the persona,
which is an ancestor of every branch, so both branches ended up seeing 176 of
182 nodes and the branches stopped differing at all.

What it does
------------
* Re-parents ``offer:*-varejo`` / ``copy:*-varejo`` under the retail brand and
  the ``-atacado`` ones under the wholesale brand.
* Keeps the product link as a semantic ``about_product`` edge, so nothing loses
  its meaning -- only its place in the primary tree changes.
* Leaves products, product groups and the catalog campaign shared.
* Adds one ``include_subtree_in_branch`` edge per branch per shared/own subtree,
  replacing the ~300 point-to-point edges the old approach needed.
* Drops the persona-rooted visibility edges that erased the branches.

Run with ``--check`` to print what would change without writing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RETAIL_ANCHOR = "audience:tock-retail"
RESELLER_ANCHOR = "audience:tock-reseller"
RETAIL_BRAND = "brand:tock-fatal-varejo"
RESELLER_BRAND = "brand:tock-fatal-atacado"
CATALOG_CAMPAIGN = "campaign:tock-catalogo-produtos"
PERSONA = "persona:tock-fatal"

# Suffix -> (owning brand, branch that may see it)
CHANNELS = {
    "-varejo": (RETAIL_BRAND, RETAIL_ANCHOR),
    "-atacado": (RESELLER_BRAND, RESELLER_ANCHOR),
}
CHANNEL_TYPES = {"offer", "copy"}


def _channel_of(node_id: str) -> str | None:
    return next((suffix for suffix in CHANNELS if node_id.endswith(suffix)), None)


def restructure(bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new_bundle, report). Pure: the input is not mutated."""
    nodes = [dict(node) for node in bundle.get("nodes") or []]
    edges = [dict(edge) for edge in bundle.get("edges") or []]
    by_id = {node["id"]: node for node in nodes}

    channel_nodes = {
        node["id"] for node in nodes
        if node.get("node_type") in CHANNEL_TYPES and _channel_of(node["id"])
    }

    kept_edges: list[dict[str, Any]] = []
    reparented: list[dict[str, Any]] = []
    dropped_persona_visibility = 0

    for edge in edges:
        relation = edge.get("relation_type")
        target = edge.get("target")
        source = edge.get("source")

        # The v8 repair: persona -> everything. This is what erased the
        # branches, so it goes.
        if relation == "visible_to_agent" and source == PERSONA:
            dropped_persona_visibility += 1
            continue

        # A channel node's primary parent moves to its brand; the old product
        # link survives as meaning, not as tree position.
        if relation == "contains" and target in channel_nodes:
            suffix = _channel_of(target)
            brand = CHANNELS[suffix][0]
            reparented.append({
                "node": target, "from": source, "to": brand,
            })
            kept_edges.append({
                **edge,
                "id": f"edge:contains:{brand}:{target}",
                "source": brand,
                "target": target,
            })
            if by_id.get(source, {}).get("node_type") == "product":
                kept_edges.append({
                    "id": f"edge:about-product:{target}",
                    "source": target,
                    "target": source,
                    "relation_type": "about_product",
                    "weight": 1.0,
                    "metadata": {"source": "brand_scope_restructure"},
                })
            continue

        kept_edges.append(edge)

    # One edge per branch per subtree it may see. The shared catalog reaches
    # both; each brand reaches only its own branch.
    scope_edges = [
        (RETAIL_ANCHOR, CATALOG_CAMPAIGN),
        (RETAIL_ANCHOR, RETAIL_BRAND),
        (RESELLER_ANCHOR, CATALOG_CAMPAIGN),
        (RESELLER_ANCHOR, RESELLER_BRAND),
    ]
    existing = {
        (edge.get("source"), edge.get("target"), edge.get("relation_type"))
        for edge in kept_edges
    }
    added_scope = 0
    for anchor, subtree_root in scope_edges:
        if subtree_root not in by_id:
            continue
        key = (anchor, subtree_root, "visible_to_agent")
        kept_edges = [
            edge for edge in kept_edges
            if (edge.get("source"), edge.get("target"), edge.get("relation_type")) != key
        ]
        kept_edges.append({
            "id": f"edge:branch-scope:{anchor}:{subtree_root}",
            "source": anchor,
            "target": subtree_root,
            "relation_type": "visible_to_agent",
            "weight": 1.0,
            "metadata": {
                "include_subtree_in_branch": True,
                "source": "brand_scope_restructure",
            },
        })
        added_scope += 1
        existing.add(key)

    report = {
        "channel_nodes_reparented": len(reparented),
        "persona_visibility_edges_dropped": dropped_persona_visibility,
        "branch_scope_edges": added_scope,
        "about_product_edges_added": sum(
            1 for edge in kept_edges if edge.get("relation_type") == "about_product"
        ),
        "edges_before": len(edges),
        "edges_after": len(kept_edges),
    }
    return {**bundle, "nodes": nodes, "edges": kept_edges}, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="print the report without writing anything")
    args = parser.parse_args()

    bundle = json.loads(args.source.read_text(encoding="utf-8"))
    restructured, report = restructure(bundle)
    print(json.dumps(report, indent=2))
    if args.check:
        return
    if not args.out:
        raise SystemExit("--out is required unless --check is given")
    args.out.write_text(
        json.dumps(restructured, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
