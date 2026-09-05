"""The deployed compiler must reproduce the branch isolation that is live.

## Why this exists

Tock Fatal sells the same catalogue under two brands at different prices. The
isolation between them is not enforced by prose -- it is the branch closure the
compiler computes. If a compiler stops putting `brand:tock-fatal-atacado`
outside the retail branch, wholesale pricing becomes reachable for a retail
customer and nothing downstream notices.

That isolation depends on one mechanism, `include_subtree_in_branch`, declared
on the `audience -> brand` edges. Support for it arrived in
`graph-compiler-v3.6.4`:

    3.6.2:  (edge.metadata).get("include_in_branch") is True
    3.6.4:  metadata.get("include_in_branch") is True or subtree

The Tock edges carry only `include_subtree_in_branch`, so a compiler without
that clause silently drops both brands out of both branches.

## The situation this pins

On 2026-09-05 the active publication (v12) was found to have been compiled by
`graph-compiler-v3.6.4`, while **every container in production runs 3.6.2** --
the graph in production was produced by a compiler that does not exist in
production. Republishing through the deployed control-plane would recompute the
closure with 3.6.2 and erase the isolation.

So this is a canary, not a unit test: it asserts that whichever compiler a
deployable app ships reproduces, from the same bundle, the closure that is
actually live. It fails today for the microservice copies, on purpose, and that
failure is the work item.

Ground truth captured from the active publication on 2026-09-05:
version 12, checksum sha256:002a533e…, compiler graph-compiler-v3.6.4.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

BUNDLE_PATH = (
    ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v12-model-owned.json"
)

# Read back from graph_publications for the active v12 publication. These are
# the numbers the live agent is scoped by right now.
LIVE_MEMBER_COUNTS = {
    "audience:tock-retail": 552,
    "audience:tock-reseller": 553,
}

# One brand per branch, and the nodes that must never cross. `reseller_stage` is
# the question that reached a retail customer on 2026-09-04 when the branch
# failed to close; `desconto_rule` carries the wholesale discount.
LIVE_ISOLATION = {
    "audience:tock-retail": {
        "brand:tock-fatal-varejo": True,
        "brand:tock-fatal-atacado": False,
        "faq:tock-reseller-stage": False,
        "faq:tock-retail-need": True,
        "rule:tock-desconto-atacado-30": False,
    },
    "audience:tock-reseller": {
        "brand:tock-fatal-varejo": False,
        "brand:tock-fatal-atacado": True,
        "faq:tock-reseller-stage": True,
        "faq:tock-retail-need": False,
        "rule:tock-desconto-atacado-30": True,
    },
}

# Every tree that ships a compiler. The monolith is not deployed but is the
# version the live publication was built with, so it is the reference.
COMPILER_COPIES = {
    "monolith (api/services)": ROOT / "api/services/graph_compiler_v3.py",
    "control-plane": ROOT / "apps/control-plane/api/services/graph_compiler_v3.py",
    "conversation-runtime": ROOT / "apps/conversation-runtime/api/services/graph_compiler_v3.py",
}

DEPLOYED_COPIES = ["control-plane", "conversation-runtime"]


def _load(path: Path):
    """Import one compiler copy in isolation, so two versions can coexist."""
    spec = importlib.util.spec_from_file_location(f"compiler_{path.parent.parent.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _closure(module, bundle: dict) -> dict[str, set[str]]:
    """Branch memberships this compiler derives from the bundle.

    Compiles through the same entry point the publisher uses so the result is
    what a real publication would carry, not a reimplementation of the rules.
    """
    document = module.compile_graph(
        persona={"id": bundle["persona"]["id"], "slug": bundle["persona"]["slug"]},
        node_rows=[
            {
                "id": node["id"],
                "persona_id": bundle["persona"]["id"],
                "node_type": node["node_type"],
                "slug": node.get("slug"),
                "title": node.get("title"),
                "summary": node.get("summary"),
                "tags": node.get("tags") or [],
                "status": node.get("status"),
                # graph_bundle_publisher.stage_bundle writes the stable id into
                # metadata, and the compiler derives node identity from it.
                # Without it the ids drift and the closure references nodes the
                # compiler never indexed.
                "metadata": {"graph_json_node_id": node["id"], **(node.get("data") or {})},
            }
            for node in bundle["nodes"]
        ],
        edge_rows=[
            {
                "id": edge["id"],
                "persona_id": bundle["persona"]["id"],
                "source_node_id": edge["source"],
                "target_node_id": edge["target"],
                "relation_type": edge["relation_type"],
                "weight": edge.get("weight"),
                "metadata": edge.get("metadata") or {},
            }
            for edge in bundle["edges"]
        ],
        embedding_profile=bundle["metadata"]["embedding_profile"],
    )
    return {
        anchor: set(members)
        for anchor, members in (document.get("branch_memberships") or {}).items()
    }


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_reference_compiler_reproduces_the_live_closure(bundle):
    """The monolith copy built the live publication; it must still match it."""
    closure = _closure(_load(COMPILER_COPIES["monolith (api/services)"]), bundle)

    assert {anchor: len(members) for anchor, members in closure.items()} == LIVE_MEMBER_COUNTS
    for anchor, expectations in LIVE_ISOLATION.items():
        for node_id, present in expectations.items():
            assert (node_id in closure[anchor]) is present, (anchor, node_id)


@pytest.mark.unit
@pytest.mark.parametrize("app", DEPLOYED_COPIES)
def test_deployed_compiler_reproduces_the_live_closure(bundle, app):
    """The canary.

    A deployed compiler that cannot reproduce the live closure must never
    publish: republishing would recompute the branches and silently drop the
    brand isolation the live graph has. Expected to fail while the microservice
    copies lag behind the version that built the live publication.
    """
    closure = _closure(_load(COMPILER_COPIES[app]), bundle)

    assert {anchor: len(members) for anchor, members in closure.items()} == LIVE_MEMBER_COUNTS, (
        f"{app} derives a different branch closure than the live publication; "
        "publishing through it would change which brand each customer can see"
    )
    for anchor, expectations in LIVE_ISOLATION.items():
        for node_id, present in expectations.items():
            assert (node_id in closure[anchor]) is present, (app, anchor, node_id)


@pytest.mark.unit
@pytest.mark.parametrize("app", DEPLOYED_COPIES)
def test_deployed_compiler_supports_subtree_branch_scoping(bundle, app):
    """The single mechanism the isolation rests on.

    Isolated from the closure assertions above because it is the specific clause
    that differs between 3.6.2 and 3.6.4, and naming it makes a failure
    actionable instead of merely red.
    """
    source = COMPILER_COPIES[app].read_text(encoding="utf-8")
    assert "include_subtree_in_branch" in source, (
        f"{app} ignores include_subtree_in_branch, so an audience never reaches "
        "its brand and both brands fall out of both branches"
    )
