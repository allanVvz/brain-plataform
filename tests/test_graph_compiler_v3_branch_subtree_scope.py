"""Branch scope for shared content: one edge instead of one edge per node.

Branch closure walks the primary `contains` tree and then expands over
semantic edges in a SINGLE non-transitive pass -- an `include_in_branch` edge
admits exactly the node it points at, never that node's subtree. Scoping a
whole shared catalog to a branch therefore needed one edge per node, and the
shortcut people reached for (rooting those edges at the persona, which is an
ancestor of every branch) put every node in every branch and erased the
difference between the branches.

`include_subtree_in_branch` is the additive fix: the edge admits the node and
everything below it, so a catalog is scoped with one edge per branch and each
branch can keep content the other must not see.
"""
from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_compiler_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000001", "slug": "aria"}


def node(index: int, stable_id: str, *, node_type: str = "knowledge", data=None):
    return {
        "id": f"20000000-0000-0000-0000-{index:012d}",
        "node_type": node_type,
        "slug": stable_id.replace(":", "-"),
        "title": stable_id,
        "summary": stable_id,
        "tags": [],
        "status": "validated",
        "metadata": {"graph_json_node_id": stable_id, **(data or {})},
    }


def edge(index: int, source: dict, target: dict, relation="contains", data=None):
    return {
        "id": f"30000000-0000-0000-0000-{index:012d}",
        "source_node_id": source["id"],
        "target_node_id": target["id"],
        "relation_type": relation,
        "weight": 1,
        "metadata": {"active": True, "graph_json_edge_id": f"edge:{index}", **(data or {})},
    }


def _branch(index: int, stable_id: str, field_key: str, question_id: str):
    return node(index, stable_id, node_type="audience", data={
        "capabilities": {"branch_anchor": True},
        "qualification": {"fields": [{
            "key": field_key, "question_node_id": question_id, "required": True,
            "accepted_statuses": ["known"],
            "value_schema": {"type": "string", "minLength": 1},
            "owner_node_id": stable_id,
        }]},
    })


def _two_brand_graph(scope_metadata: dict):
    """Two branches, a shared catalog, and one channel-only offer per branch."""
    root = node(1, "persona:aria", node_type="persona")
    retail = _branch(2, "audience:retail", "retail_need", "question:retail")
    reseller = _branch(3, "audience:reseller", "resale_stage", "question:reseller")
    q_retail = node(4, "question:retail", node_type="faq", data={"question": "O que procura?"})
    q_reseller = node(5, "question:reseller", node_type="faq", data={"question": "Já revende?"})

    catalog = node(6, "campaign:catalog", node_type="campaign")
    product = node(7, "product:dress", node_type="product")

    retail_brand = node(8, "brand:retail", node_type="brand")
    retail_offer = node(9, "offer:dress-retail", node_type="offer")
    reseller_brand = node(10, "brand:reseller", node_type="brand")
    reseller_offer = node(11, "offer:dress-wholesale", node_type="offer")

    rows = [root, retail, reseller, q_retail, q_reseller, catalog, product,
            retail_brand, retail_offer, reseller_brand, reseller_offer]
    edges = [
        edge(1, root, retail),
        edge(2, root, reseller),
        edge(3, root, q_retail),
        edge(4, root, q_reseller),
        edge(5, root, catalog),
        edge(6, catalog, product),
        edge(7, root, retail_brand),
        edge(8, retail_brand, retail_offer),
        edge(9, root, reseller_brand),
        edge(10, reseller_brand, reseller_offer),
        # Shared catalog reaches both branches; each channel's offers reach
        # only their own branch.
        edge(11, retail, catalog, relation="visible_to_agent", data=scope_metadata),
        edge(12, reseller, catalog, relation="visible_to_agent", data=scope_metadata),
        edge(13, retail, retail_brand, relation="visible_to_agent", data=scope_metadata),
        edge(14, reseller, reseller_brand, relation="visible_to_agent", data=scope_metadata),
    ]
    return rows, edges


def _memberships(scope_metadata: dict):
    rows, edges = _two_brand_graph(scope_metadata)
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA, node_rows=rows, edge_rows=edges,
    )
    return {
        anchor: set(members)
        for anchor, members in (document.get("branch_memberships") or {}).items()
    }


def test_subtree_scope_shares_the_catalog_and_splits_the_offers():
    """The whole point: shared content in both branches, channel content in one."""
    memberships = _memberships({"include_subtree_in_branch": True})
    retail = memberships["audience:retail"]
    reseller = memberships["audience:reseller"]

    # Shared catalog reaches both, subtree included -- the product below the
    # campaign comes along, which a single-node edge would not have brought.
    for shared in ("campaign:catalog", "product:dress"):
        assert shared in retail, shared
        assert shared in reseller, shared

    # Each channel's offer stays in its own branch. This is what stops a
    # retail customer being quoted a wholesale price.
    assert "offer:dress-retail" in retail
    assert "offer:dress-retail" not in reseller
    assert "offer:dress-wholesale" in reseller
    assert "offer:dress-wholesale" not in retail


def test_single_node_scope_admits_the_node_but_not_its_subtree():
    """`include_in_branch` keeps its old meaning, so published graphs are safe."""
    memberships = _memberships({"include_in_branch": True})
    retail = memberships["audience:retail"]

    assert "campaign:catalog" in retail
    assert "product:dress" not in retail


def test_unscoped_semantic_edge_admits_nothing():
    """An edge that declares no branch scope must not leak either way."""
    memberships = _memberships({})
    retail = memberships["audience:retail"]

    assert "campaign:catalog" not in retail
    assert "product:dress" not in retail
    assert "offer:dress-retail" not in retail
