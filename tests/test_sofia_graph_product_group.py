#!/usr/bin/env python3
"""[PATH: GRAPH] Sofia Graph path shares the SAME hierarchy rules as Create.

Graph path: UI /knowledge/graph, endpoint /sofia/graph-command, service
`sofia_orchestrator`. After unification it validates parent/edge hierarchy via
the shared `services/graph_validation.py` (same rules as the Create path),
instead of the old divergent stub. See tests/SOFIA_PATHS.md.

Covers:
  * shared rules: audience -> product and product_group -> product valid; product_group under product invalid
  * _validate_plan_json blocks product_group-under-product, accepts the chain
  * _validate_patch_canonical (was a stub) blocks an inverted patch
  * anti-hallucination signal shared by both paths
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import sofia_orchestrator as orch  # noqa: E402
from services import graph_validation as gv  # noqa: E402


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"ok {msg}")


# ── shared hierarchy rules (graph_validation) ────────────────────────────────
def test_shared_rules_product_group() -> None:
    expect(gv.parent_violation("product", "product_group") is None,
           "product under product_group is valid")
    expect(gv.parent_violation("product", "audience") is None,
           "product directly under audience is valid")
    expect(gv.parent_violation("product_group", "audience") is None,
           "product_group under audience is valid")
    expect(gv.parent_violation("product_group", "product") is not None,
           "product_group under product is INVALID")
    expect(gv.edge_violation("product_group", "product", "product_group_has_product") is None,
           "edge product_group->product valid")
    expect(gv.edge_violation("product", "product_group", "") is not None,
           "edge product->product_group invalid")


# ── Graph plan_json validator now uses the shared rules ──────────────────────
def _plan_json(parent_of_product: str) -> dict:
    return {
        "plan": {
            "campaign": [{"slug": "camp-esport", "title": "Campanha", "parent_slug": "briefing-vz"}],
            "audience": [{"slug": "pub-esport", "title": "Publico", "parent_slug": "camp-esport"}],
            "product_group": [{"slug": "grupo-radar", "title": "Radar", "parent_slug": parent_of_product if parent_of_product == "radar-areia" else "pub-esport"}],
            "product": [{"slug": "radar-areia", "title": "Radar Areia", "parent_slug": parent_of_product}],
        }
    }


def test_graph_validate_plan_json_accepts_group_chain() -> None:
    res = orch._validate_plan_json(_plan_json("grupo-radar"))
    bad = [b for b in res["blocking"] if b.get("code") == "INVALID_PARENT"]
    expect(not bad, f"audience->product_group->product passes _validate_plan_json (got {bad})")


def test_graph_validate_plan_json_blocks_inverted() -> None:
    # product_group parented to the product -> inversion must block.
    res = orch._validate_plan_json(_plan_json("radar-areia"))
    bad = [b for b in res["blocking"] if b.get("code") == "INVALID_PARENT" and "product_group" in b.get("message", "")]
    expect(bool(bad), f"product_group under product is blocked (got {res['blocking']})")


# ── Graph patch canonical validation (replaces the old stub) ────────────────
def _patch(rel_src: str, rel_tgt: str, relation: str) -> dict:
    return {
        "nodes_upsert": [
            {"node_type": "product_group", "slug": "grupo-radar"},
            {"node_type": "product", "slug": "radar-areia"},
        ],
        "edges_upsert": [{
            "source_ref": f"slug:{rel_src}",
            "target_ref": f"slug:{rel_tgt}",
            "relation_type": relation,
            "metadata": {"primary_tree": True, "active": True},
        }],
    }


def test_graph_patch_canonical_ok() -> None:
    v = orch._validate_patch_canonical(_patch("grupo-radar", "radar-areia", "product_group_has_product"))
    expect(not v, f"canonical patch product_group->product has no violations (got {v})")


def test_graph_patch_canonical_blocks_inversion() -> None:
    v = orch._validate_patch_canonical(_patch("radar-areia", "grupo-radar", "product_has_product_group"))
    expect(bool(v), f"inverted patch product->product_group is flagged (got {v})")


# ── anti-hallucination shared by both paths ─────────────────────────────────
def test_anti_hallucination_signals() -> None:
    expect(gv.has_explicit_product_signal("Crie uma campanha para óculos esportivos da VZ Lupas.") is False,
           "broad 'óculos esportivos' is NOT a product signal (Sofia must ask)")
    expect(gv.has_explicit_product_signal("crie 9 produtos") is True,
           "explicit quantity '9 produtos' IS a signal")
    expect(gv.has_explicit_product_signal("3 produtos para cada grupo") is True,
           "'3 produtos para cada grupo' IS a signal")
    expect(gv.has_explicit_product_signal("Produtos: Radar Areia, Radar Transparente") is True,
           "explicit 'Produtos:' list IS a signal")


def main() -> int:
    test_shared_rules_product_group()
    test_graph_validate_plan_json_accepts_group_chain()
    test_graph_validate_plan_json_blocks_inverted()
    test_graph_patch_canonical_ok()
    test_graph_patch_canonical_blocks_inversion()
    test_anti_hallucination_signals()
    print("PASS test_sofia_graph_product_group")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
