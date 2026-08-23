"""The restructured Tock Fatal bundle must not leak one channel's price.

Every product carries a retail offer and a wholesale offer. While both hang off
the shared product node, branch closure reaches both from either branch, so a
retail customer can be quoted the wholesale price. This pins the fix: channel
content lives on its channel's brand, the catalog stays shared, and the two
branches stop being interchangeable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle  # noqa: E402

sys.path.insert(0, str(API_ROOT / "scripts"))
from restructure_tock_fatal_brand_scope import (  # noqa: E402
    RESELLER_ANCHOR,
    RETAIL_ANCHOR,
    restructure,
)

DRAFT = REPO_ROOT / "data" / "graph_bundles" / "tock-fatal" / "sdr-qualification-v3-draft-two-brands.json"


@pytest.fixture(scope="module")
def memberships() -> dict[str, set[str]]:
    bundle = json.loads(DRAFT.read_text(encoding="utf-8"))
    restructured, _report = restructure(bundle)
    document = graph_bundle.compile_bundle(restructured)
    return {
        anchor: set(members)
        for anchor, members in (document.get("branch_memberships") or {}).items()
    }


def _offers(members: set[str], suffix: str) -> set[str]:
    return {
        node_id for node_id in members
        if node_id.startswith("offer:") and node_id.endswith(suffix)
    }


def test_neither_branch_sees_the_other_channels_offers(memberships):
    retail = memberships[RETAIL_ANCHOR]
    reseller = memberships[RESELLER_ANCHOR]

    assert _offers(retail, "-varejo")
    assert _offers(reseller, "-atacado")
    # The whole point: no wholesale price reachable from the retail branch.
    assert _offers(retail, "-atacado") == set()
    assert _offers(reseller, "-varejo") == set()


def test_the_catalog_itself_stays_shared(memberships):
    retail = memberships[RETAIL_ANCHOR]
    reseller = memberships[RESELLER_ANCHOR]
    retail_products = {n for n in retail if n.startswith("product:")}

    assert retail_products, "retail branch lost the catalog entirely"
    assert retail_products <= reseller, "products stopped being shared"


def test_copy_follows_its_own_channel(memberships):
    retail = memberships[RETAIL_ANCHOR]
    reseller = memberships[RESELLER_ANCHOR]
    retail_copy = {n for n in retail if n.startswith("copy:") and n.endswith("-atacado")}
    reseller_copy = {n for n in reseller if n.startswith("copy:") and n.endswith("-varejo")}

    assert retail_copy == set()
    assert reseller_copy == set()


def test_restructure_does_not_mutate_its_input():
    bundle = json.loads(DRAFT.read_text(encoding="utf-8"))
    before = json.dumps(bundle, sort_keys=True)
    restructure(bundle)
    assert json.dumps(bundle, sort_keys=True) == before
