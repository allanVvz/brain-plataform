from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.generate_tock_fatal_conversation_faqs import (  # noqa: E402
    GENERATOR,
    _semantic_fold,
    generate,
)
from services import graph_bundle  # noqa: E402


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


def test_projection_uses_one_complete_faq_per_copy_instead_of_four_variants():
    candidate = generate(_bundle(), approved=True)
    copies = [node for node in candidate["nodes"] if node.get("node_type") == "copy"]
    generated = [
        node for node in candidate["nodes"]
        if ((node.get("data") or {}).get("metadata") or {}).get("generator") == GENERATOR
    ]
    product_faqs = [
        node for node in generated if str(node.get("id") or "").endswith("-produto-canal")
    ]

    assert len(copies) == len(product_faqs) == 146
    assert len(generated) == 146 + 7 + 1 + 2
    assert sum(node.get("node_type") == "faq" for node in candidate["nodes"]) == 168
    assert not any(
        str(node.get("id") or "").endswith(suffix)
        for node in candidate["nodes"]
        for suffix in (
            "-descricao-indicacao",
            "-preco-canal-quantidade",
            "-recomendacao-comparacao",
            "-duvida-indireta-proxima-acao",
        )
    )

    edges = candidate["edges"]
    for copy in copies:
        children = [
            edge["target"] for edge in edges
            if edge.get("source") == copy["id"]
            and edge.get("relation_type") == "contains"
            and str(edge.get("target") or "").endswith("-produto-canal")
        ]
        assert len(children) == 1


def test_product_faqs_keep_coverage_without_repeating_quantity_policy():
    candidate = generate(_bundle(), approved=True)
    product_faqs = [
        node for node in candidate["nodes"]
        if str(node.get("id") or "").endswith("-produto-canal")
    ]
    forbidden = (
        "pedido minimo",
        "quantidade minima",
        "a partir de 3 pecas",
        "minimo de 3 pecas",
        "compra unitaria",
    )

    for faq in product_faqs:
        data = faq["data"]
        searchable = _semantic_fold(" ".join([
            faq["title"],
            faq["summary"],
            data["question"],
            *data["question_aliases"],
            data["answer"],
        ]))
        assert not any(term in searchable for term in forbidden)
        assert "r$" in searchable
        assert {claim["claim_type"] for claim in data["claims"]} == {
            "price", "service_detail",
        }
        assert {item["node_id"].split(":", 1)[0] for item in data["sources"]} == {
            "product_group", "product", "offer", "copy",
        }


def test_exactly_two_channel_quantity_faqs_are_isolated_by_branch():
    candidate = generate(_bundle(), approved=True)
    quantity_faqs = {
        node["id"]: node for node in candidate["nodes"]
        if node.get("node_type") == "faq"
        and any(
            claim.get("claim_type") == "minimum_order"
            for claim in (node.get("data") or {}).get("claims") or []
        )
    }
    expected = {
        "faq:tock-retail-minimum-quantity": "audience:tock-retail",
        "faq:tock-reseller-minimum-quantity": "audience:tock-reseller",
    }
    assert set(quantity_faqs) == set(expected)
    assert quantity_faqs["faq:tock-retail-minimum-quantity"]["data"]["answer"] == (
        "No varejo, a compra mínima é de 1 peça."
    )
    assert quantity_faqs["faq:tock-reseller-minimum-quantity"]["data"]["answer"] == (
        "No atacado, o pedido mínimo é de 3 peças, iguais ou diferentes entre si."
    )

    for faq_id, parent_id in expected.items():
        primary = [
            edge for edge in candidate["edges"]
            if edge.get("target") == faq_id and edge.get("relation_type") == "contains"
        ]
        projections = [
            edge for edge in candidate["edges"]
            if edge.get("source") == faq_id
            and edge.get("relation_type") == "publishes_to"
        ]
        assert len(primary) == 1
        assert primary[0]["source"] == parent_id
        assert len(projections) == 1
        assert quantity_faqs[faq_id]["data"]["source_node_id"] == parent_id

    document = graph_bundle.compile_bundle(candidate)
    retail = document["branch_contracts"]["audience:tock-retail"]
    reseller = document["branch_contracts"]["audience:tock-reseller"]
    retail_id = "faq:tock-retail-minimum-quantity"
    reseller_id = "faq:tock-reseller-minimum-quantity"
    assert retail_id in retail["closure_node_ids"]
    assert retail_id in retail["eligible_faq_node_ids"]
    assert retail_id not in reseller["closure_node_ids"]
    assert retail_id not in reseller["eligible_faq_node_ids"]
    assert reseller_id in reseller["closure_node_ids"]
    assert reseller_id in reseller["eligible_faq_node_ids"]
    assert reseller_id not in retail["closure_node_ids"]
    assert reseller_id not in retail["eligible_faq_node_ids"]


def test_reseller_volume_question_does_not_claim_a_minimum_order():
    candidate = generate(_bundle(), approved=True)
    volume = next(
        node for node in candidate["nodes"] if node.get("id") == "faq:tock-reseller-volume"
    )
    assert not any(
        claim.get("claim_type") == "minimum_order"
        for claim in (volume.get("data") or {}).get("claims") or []
    )


def test_compact_projection_is_idempotent():
    first = generate(_bundle(), approved=True)
    second = generate(first, approved=True)

    assert second == first
