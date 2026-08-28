from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.generate_tock_fatal_conversation_faqs import GENERATOR, generate  # noqa: E402


BUNDLE = (
    ROOT / "data" / "graph_bundles" / "tock-fatal"
    / "sdr-qualification-v10-full-catalog.json"
)


def _bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def test_every_product_group_has_one_approved_navigation_faq_in_embedded():
    candidate = generate(_bundle(), approved=True)
    nodes = candidate["nodes"]
    edges = candidate["edges"]
    groups = {node["id"] for node in nodes if node.get("node_type") == "product_group"}
    navigation = [
        node for node in nodes
        if ((node.get("data") or {}).get("metadata") or {}).get("generator") == GENERATOR
        and str(node.get("id") or "").endswith("-navegacao")
    ]
    assert len(navigation) == len(groups) == 7
    for faq in navigation:
        assert faq["status"] == "approved"
        assert faq["data"]["channel"] == "all"
        assert faq["data"]["source_node_type"] == "product_group"
        projections = [
            edge for edge in edges
            if edge.get("source") == faq["id"]
            and edge.get("relation_type") == "publishes_to"
        ]
        assert len(projections) == 1


def test_lower_body_navigation_faq_exposes_the_published_short_skirt_option():
    candidate = generate(_bundle(), approved=True)
    faq = next(
        node for node in candidate["nodes"]
        if node.get("id")
        == "faq:tock-calcas-leggings-shorts-e-partes-de-baixo-navegacao"
    )
    searchable = " ".join([
        faq["data"]["question"],
        *faq["data"]["question_aliases"],
        faq["data"]["answer"],
    ]).lower()
    assert "short saia resinada" in searchable
    assert "r$" not in faq["data"]["answer"].lower()
