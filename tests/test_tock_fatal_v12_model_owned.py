from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle  # noqa: E402


BUNDLE = (
    ROOT
    / "data"
    / "graph_bundles"
    / "tock-fatal"
    / "sdr-qualification-v12-model-owned.json"
)


def _bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def _node(bundle: dict, node_id: str) -> dict:
    return next(node for node in bundle["nodes"] if node["id"] == node_id)


def test_v12_keeps_the_audited_v11_catalog_and_faq_coverage() -> None:
    bundle = _bundle()
    metadata = bundle["metadata"]

    assert metadata["baseline_publication"] == {
        "version": 11,
        "checksum": "sha256:e139c1370211ae59abe1624501addea6b22c9222c3d66a5964c67ce9a9a5dc65",
    }
    assert metadata["preserved_v11_fingerprints"] == {
        "catalog_content_sha256": "e41d00fe5bb7bbe3d36f0be7a528dc6da8b6d274d095ebd71f37683685a083ef",
        "edges_sha256": "9be24719adc32c24439683aae69daa549796eb954e63a5f549833b31db90ac1c",
        "rules_sha256": "06c16d190d543394c010cbc15904115fb2644864a3aae4b0c858da0426f1699b",
    }
    assert metadata["faq_coverage_audit"]["new_faqs_added"] == 0
    assert len(bundle["nodes"]) == 1001
    assert len(bundle["edges"]) == 1904

    faq_ids = {node["id"] for node in bundle["nodes"] if node["node_type"] == "faq"}
    embed_ids = {
        node["id"]
        for node in bundle["nodes"]
        if node["node_type"] in {"embed", "embedded"}
    }
    projected = {
        edge["source"]
        for edge in bundle["edges"]
        if edge["relation_type"] == "publishes_to" and edge["target"] in embed_ids
    }
    assert len(faq_ids) == 605
    assert faq_ids <= projected
    assert all((_node(bundle, faq_id).get("data") or {}).get("source") for faq_id in faq_ids)


def test_v12_declares_model_owned_natural_conversation_policy() -> None:
    bundle = _bundle()
    persona = _node(bundle, "persona:tock-fatal")
    policy = persona["data"]["conversation_policy"]

    assert policy["response_ownership"] == {
        "mode": "model",
        "answer_and_explain_before_qualification": True,
        "deterministic_validator": "advisory",
    }
    assert policy["opening"]["customer_name_required_before_help"] is False
    assert policy["opening"]["respond_to_current_content_first"] is True
    assert policy["question_policy"]["max_useful_questions_per_reply"] == 1
    assert policy["question_policy"]["force_question"] is False
    assert policy["catalog_discovery"]["allow_before_purchase_profile"] is True
    assert policy["explicit_unknown_only"] is True
    assert policy["doubt_handling"]["deferred_response"] == (
        "Vou registrar seu interesse. Um atendente confirmará os valores "
        "ao final do atendimento."
    )


def test_v12_retail_and_reseller_contracts_remain_isolated() -> None:
    document = graph_bundle.compile_bundle(_bundle())
    retail = document["branch_contracts"]["audience:tock-retail"]
    reseller = document["branch_contracts"]["audience:tock-reseller"]

    assert retail["required_fields"] == [
        "purchase_profile",
        "retail_need",
        "retail_style",
    ]
    assert "resale_stage" not in retail["required_fields"]
    assert reseller["required_fields"] == [
        "purchase_profile",
        "resale_stage",
        "volume_interest",
    ]
    assert "retail_need" not in reseller["required_fields"]

    retail_members = set(document["branch_memberships"]["audience:tock-retail"])
    reseller_members = set(document["branch_memberships"]["audience:tock-reseller"])
    assert not {node for node in retail_members if node.startswith("offer:") and node.endswith("-atacado")}
    assert not {node for node in reseller_members if node.startswith("offer:") and node.endswith("-varejo")}
    assert any(node.startswith("product_group:") for node in retail_members)
    assert any(node.startswith("product_group:") for node in reseller_members)


def test_v12_projects_faq_aliases_and_authors_cotele_followups() -> None:
    bundle = _bundle()
    audit = bundle["metadata"]["faq_coverage_audit"]

    assert audit["runtime_aliases_projected"] == 4
    assert audit["targeted_query_aliases_added"] == 20
    for channel in ("varejo", "atacado"):
        price = _node(
            bundle,
            f"faq:tock-conjuntos-conjunto-em-cotele-{channel}-preco-canal-quantidade",
        )
        description = _node(
            bundle,
            f"faq:tock-conjuntos-conjunto-em-cotele-{channel}-descricao-indicacao",
        )
        assert "qual o valor do cotele" in price["data"]["aliases"]
        assert "qual o valor do cotelÃª" in price["data"]["aliases"]
        assert "qual o tecido do cotele" in description["data"]["aliases"]


def test_every_faq_published_to_embed_is_approved() -> None:
    bundle = _bundle()
    nodes = {node["id"]: node for node in bundle["nodes"]}
    published_faqs = {
        edge["source"]
        for edge in bundle["edges"]
        if edge["relation_type"] == "publishes_to"
        and nodes[edge["source"]]["node_type"] == "faq"
    }

    assert published_faqs
    for faq_id in published_faqs:
        assert nodes[faq_id]["status"] == "approved"
        assert nodes[faq_id]["data"]["status"] == "approved"
