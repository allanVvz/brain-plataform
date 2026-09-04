"""Branch isolation for the public site output.

Tock Fatal sells the same 73 products under two brands at different prices.
A retail page that leaks a wholesale price, or a wholesale page that shows
retail pricing, is a commercial defect -- so scope isolation is a gate, not a
nice-to-have. These tests run against the real approved bundle rather than a
fixture, because the thing under test is whether the actual graph isolates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import site_blocks  # noqa: E402

BUNDLE_PATH = (
    ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v12-model-owned.json"
)

RETAIL = "audience:tock-retail"
RESELLER = "audience:tock-reseller"


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nodes(bundle) -> dict:
    return {node["id"]: node for node in bundle["nodes"]}


def _resolve(bundle: dict, scope: str) -> dict:
    return site_blocks.resolve_blocks(
        bundle,
        template_key="landing_page",
        scope=scope,
        site={"whatsapp_phone": "5551992623375"},
    )


def _channels(nodes: dict, scoped: set[str], node_type: str) -> set[str]:
    return {
        (nodes[node_id].get("data") or {}).get("channel")
        for node_id in scoped
        if node_id in nodes and nodes[node_id].get("node_type") == node_type
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "scope,expected_channel,expected_brand",
    [
        (RETAIL, "varejo", "brand:tock-fatal-varejo"),
        (RESELLER, "atacado", "brand:tock-fatal-atacado"),
    ],
)
def test_branch_closure_isolates_one_channel(
    bundle, nodes, scope, expected_channel, expected_brand
):
    scoped = site_blocks.branch_closure(nodes, bundle["edges"], scope)

    assert _channels(nodes, scoped, "offer") == {expected_channel}
    assert _channels(nodes, scoped, "copy") == {expected_channel}

    brands = [
        node_id
        for node_id in scoped
        if nodes.get(node_id, {}).get("node_type") == "brand"
    ]
    assert brands == [expected_brand]


@pytest.mark.unit
def test_retail_payload_never_mentions_wholesale(bundle):
    payload = _resolve(bundle, RETAIL)
    assert "atacado" not in json.dumps(payload, ensure_ascii=False).lower()


@pytest.mark.unit
def test_wholesale_payload_prices_differ_from_retail(bundle):
    """The 30% wholesale discount must actually show up as a different page."""
    retail = _resolve(bundle, RETAIL)
    wholesale = _resolve(bundle, RESELLER)

    def price_range(payload):
        block = next(b for b in payload["blocks"] if b["kind"] == "price_range")
        return block["data"]["min_cents"], block["data"]["max_cents"]

    assert price_range(retail) != price_range(wholesale)
    assert price_range(wholesale)[1] < price_range(retail)[1]


@pytest.mark.unit
def test_groups_resolve_with_counts_and_entry_price(bundle):
    payload = _resolve(bundle, RETAIL)
    groups = next(b for b in payload["blocks"] if b["kind"] == "group_index")["data"]["groups"]

    assert len(groups) == 7
    assert sum(group["product_count"] for group in groups) == 73
    assert all(group["price_from_cents"] for group in groups)
    # Every group carries the graph node id so a click can be attributed later.
    assert all(group["node_id"].startswith("product_group:") for group in groups)


@pytest.mark.unit
def test_group_renders_without_media(bundle):
    """Only 4 of 73 products have an approved image; the page must not depend
    on media that may never be bound."""
    payload = _resolve(bundle, RETAIL)
    groups = next(b for b in payload["blocks"] if b["kind"] == "group_index")["data"]["groups"]

    without_media = [group for group in groups if not group["assets"]]
    assert without_media, "expected groups with no bound asset"
    assert all(group["title"] and group["product_count"] for group in without_media)


@pytest.mark.unit
def test_derived_and_mechanical_faqs_stay_off_the_site(bundle):
    """605 FAQs exist, none elected for the site yet, so the block drops out."""
    payload = _resolve(bundle, RETAIL)
    assert [block["id"] for block in payload["blocks"] if block["kind"] == "faq"] == []


@pytest.mark.unit
def test_scope_must_be_a_branch_anchor(bundle, nodes):
    with pytest.raises(site_blocks.SiteBlockError, match="scope_is_not_branch_anchor"):
        site_blocks.branch_closure(nodes, bundle["edges"], "brand:tock-fatal-varejo")

    with pytest.raises(site_blocks.SiteBlockError, match="scope_anchor_not_found"):
        site_blocks.branch_closure(nodes, bundle["edges"], "audience:does-not-exist")


@pytest.mark.unit
def test_template_rejects_unregistered_relation():
    template = {
        "requires": [],
        "blocks": [{"id": "x", "kind": "hero", "relations": {"a": "not_a_relation"}}],
    }
    with pytest.raises(site_blocks.SiteBlockError, match="unregistered_relation"):
        site_blocks._check_relations(template)
