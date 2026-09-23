from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_API = ROOT / "apps" / "control-plane" / "api"
if str(CONTROL_PLANE_API) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE_API))

from services.graph_bundle import build_publication_plan, compile_bundle
from services.graph_compiler_v3 import semantic_chunks

BUNDLE_PATH = (
    ROOT
    / "data"
    / "graph_bundles"
    / "utzig-garage"
    / "site-and-appointment-v1.DRAFT.json"
)
JOURNEY_BUNDLE_PATH = (
    ROOT
    / "data"
    / "graph_bundles"
    / "utzig-garage"
    / "utzig-complete-knowledge-v5.DRAFT.json"
)
PRIVATE_BANDS = {"faixa_1", "faixa_2", "faixa_3"}
PRIVATE_SOURCE = "estimated_from_service_name"
EXPECTED_ASSET_IDS = {
    "1Gjn0p1Ku0W2XKUnALXhIvF2lW5rG9Euc",
    "1UKQvGeqcaJUGwmSMYHD7gujJ8z9eln9F",
    "1W0JhqXrgLoKleFtlxZr8pdvPBHVhnzYd",
    "1mI5zZq2bpThZGD8tA0Z-ovfUb99p_oVF",
    "1mfvmIJhkwKjLP5deQ-HYYjknPuriunhw",
    "1UYYI5fE0lzkkADgqiGYPvT0rCzWDtciN",
    "1nxtPQmJD59Ky_Vkc0OLE4ko5QGGb3PlT",
    "1NnMUYfXn0s6skNrJuNRqOtD0hrPcbO5a",
    "13rmwwwi_TgmmisFA7tAFmIYEUpMEClO5",
    "1Fc3awzwr2v0zWC3TMOUENol53QzctdQU",
    "1f_N0dYbjndfqFWe8rwMBX2Rau7qlmpdM",
    "1KIn1zb5MkVzVMr_fdy0goD7GdS_hSSev",
    "16nQsU6ET-fM2H862KUWGfQclOX2C3FYN",
    "1NCZV7hRBtS4YyxsQ5sdieBvow90181w0",
    "1suHfmj5FCpNUa_yn_HpF0ug59pu9tjsj",
    "1xvwjYcfyGwsMEh2pVXNmWJ4NSc6MAl-n",
}


def _bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def _nodes(bundle: dict) -> dict[str, dict]:
    return {node["id"]: node for node in bundle["nodes"]}


def test_vehicle_journey_intent_is_graph_owned_and_audience_tracked() -> None:
    bundle = json.loads(JOURNEY_BUNDLE_PATH.read_text(encoding="utf-8"))
    nodes = _nodes(bundle)
    compiled = compile_bundle(bundle)
    question = nodes["faq:qualification:objective"]["data"]

    assert question["question"] == (
        "Só pra eu entender melhor: a ideia é preparar o carro pra venda "
        "ou é pra manter ele bem cuidado?"
    )
    assert question["journey_tracking"]["semantic_type"] == "vehicle_journey_intent"
    assert question["journey_tracking"]["preserve_customer_wording"] is True
    assert nodes["audience:prepare-for-sale"]["data"]["capabilities"]["global_context"]
    assert nodes["audience:continuous-care"]["data"]["capabilities"]["global_context"]

    for product_id in ("product:evaluation", "product:ppf", "product:vitrification"):
        field = next(
            field for field in nodes[product_id]["data"]["qualification"]["fields"]
            if field["key"] == "objective"
        )
        assert field["validation"]["semantic_type"] == "vehicle_journey_intent"
        assert field["question_node_id"] == "faq:qualification:objective"

    tracking_edges = [
        edge for edge in bundle["edges"]
        if edge["metadata"].get("tracking_only") is True
    ]
    assert {edge["relation_type"] for edge in tracking_edges} == {"same_topic_as"}
    assert {edge["source"] for edge in tracking_edges} == {
        "audience:prepare-for-sale", "audience:continuous-care"
    }
    assert set(compiled["node_by_id"]) >= {
        "audience:prepare-for-sale", "audience:continuous-care",
        "campaign:prepare-for-sale", "campaign:continuous-care",
    }
    for contract in compiled["branch_contracts"].values():
        assert {"audience:prepare-for-sale", "audience:continuous-care"} <= set(
            contract["closure_node_ids"]
        )


def test_utzig_candidate_compiles_as_publishable_approved_plan() -> None:
    bundle = _bundle()
    plan = build_publication_plan(bundle)

    assert plan["validation_errors"] == []
    assert plan["disposition"] == "awaiting_approval"
    assert plan["publication_allowed"] is True
    assert plan["approval_scope"] == "publication_plan"
    assert len(plan["branches_affected"]) == 12
    assert bundle["persona"] == {
        "id": "e7b7b2e8-859e-4185-b675-79bc0f3d846e",
        "slug": "utzig-garage",
    }
    assert bundle["metadata"]["publication_blockers"] == []
    public_grants = {
        edge["source"]
        for edge in bundle["edges"]
        if edge["relation_type"] == "publishes_to" and edge["target"] == "gallery:utzig"
    }
    assert len(public_grants) == 32
    assert {
        edge["source"]
        for edge in bundle["edges"]
        if edge["relation_type"] == "uses_asset"
    } == {node["id"] for node in bundle["nodes"] if node["node_type"] == "product"}


def test_appointment_fields_are_graph_owned_and_use_agentic_execution() -> None:
    bundle = _bundle()
    nodes = _nodes(bundle)
    persona = nodes["persona:utzig-garage"]["data"]
    policy = persona["appointment_policy"]

    assert persona["business_model"] == "appointment"
    assert (
        persona["conversation_policy"]["execution_strategy_by_role"]["sdr"]
        == "interpret_then_respond"
    )
    assert persona["agent_identity"]["named_identity"] is False
    assert policy["required_fields"] == ["nome_cliente", "servico"]

    products = [node for node in bundle["nodes"] if node["node_type"] == "product"]
    assert len(products) == 12
    for product in products:
        required = product["data"]["booking"]["required_fields"]
        declared = {
            field["key"]: field
            for field in product["data"]["qualification"]["fields"]
        }
        assert required
        assert set(required) == set(declared)
        assert set(required) <= set(policy["field_questions"])
        for key in required:
            question_id = declared[key]["question_node_id"]
            assert question_id == f"faq:qualification:{key}"
            assert nodes[question_id]["data"]["question"] == policy["field_questions"][key]
            assert nodes[question_id]["data"]["role"] == "qualification_question"


def test_private_value_bands_do_not_reach_site_rag_or_runtime_contract_text() -> None:
    bundle = _bundle()
    nodes = _nodes(bundle)
    compiled = compile_bundle(bundle)

    products = [node for node in bundle["nodes"] if node["node_type"] == "product"]
    assert {
        product["data"]["metadata"]["internal_commercial_value_band"]["band"]
        for product in products
    } == PRIVATE_BANDS
    assert all(
        product["data"]["metadata"]["internal_commercial_value_band"]["source"]
        == PRIVATE_SOURCE
        for product in products
    )

    customer_facing_site = {
        "theme": nodes["persona:utzig-garage"]["data"]["public_site"]["theme"],
        "pages": [
            node["data"]["page"]
            for node in bundle["nodes"]
            if node["node_type"] == "campaign" and "page" in node["data"]
        ],
    }
    site_text = json.dumps(customer_facing_site, ensure_ascii=False, sort_keys=True)

    projected_rag_text = json.dumps(
        {
            node_id: semantic_chunks(node)
            for node_id, node in compiled["node_by_id"].items()
            if node_id in compiled["eligible_faq_node_ids"]
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    runtime_contract_text = json.dumps(
        {
            "common_contract": compiled["common_contract"],
            "branch_contracts": compiled["branch_contracts"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    public_authored_text = json.dumps(
        [
            {
                key: value
                for key, value in node.items()
                if key != "data"
            }
            | {
                "data": {
                    key: value
                    for key, value in node["data"].items()
                    if key != "metadata"
                }
            }
            for node in bundle["nodes"]
        ],
        ensure_ascii=False,
        sort_keys=True,
    )

    for token in PRIVATE_BANDS | {PRIVATE_SOURCE}:
        assert token not in site_text
        assert token not in projected_rag_text
        assert token not in runtime_contract_text
        assert token not in public_authored_text


def test_assets_are_strictly_allowlisted_and_have_approved_public_derivatives() -> None:
    bundle = _bundle()
    assets = [node for node in bundle["nodes"] if node["node_type"] == "asset"]

    assert {
        asset["data"]["provenance"]["file_id"] for asset in assets
    } == EXPECTED_ASSET_IDS
    assert set(bundle["metadata"]["asset_policy"]["allowlisted_google_drive_file_ids"]) == EXPECTED_ASSET_IDS
    assert all(
        asset["data"]["web_derivative"]["url"].startswith(
            "https://storage.vzforeal.com/storage/v1/object/public/assets-derived/"
        )
        for asset in assets
    )
    assert all(asset["data"]["public_asset_ready"] is True for asset in assets)
    assert all(asset["data"]["registry_id"] for asset in assets)
    assert all(
        asset["data"]["web_derivative"]["status"]
        == "approved"
        for asset in assets
    )

    authored = BUNDLE_PATH.read_text(encoding="utf-8").casefold()
    assert "r$" not in authored


def test_public_site_root_is_canonical_and_graph_referenced() -> None:
    bundle = _bundle()
    nodes = _nodes(bundle)
    site = nodes["persona:utzig-garage"]["data"]["public_site"]

    assert {
        "slug",
        "name",
        "format_key",
        "default_collection_slug",
        "brand_family",
        "brand_channel",
        "whatsapp",
        "identity",
        "pages",
        "contacts",
        "covers",
        "audiences",
        "locations",
        "theme",
    } <= set(site)
    assert [item["node_id"] for item in site["pages"]] == [
        "campaign:home",
        "campaign:automotive-detailing",
    ]
    assert site["contacts"] == [{"node_id": "copy:contact-human"}]
    assert {item["node_id"] for item in site["audiences"]} == {
        "audience:preservation",
        "audience:revitalization",
        "audience:enhancement",
    }
    assert site["locations"] == [{"node_id": "campaign:physical-store"}]
    home = nodes["campaign:home"]["data"]["page"]
    assert home["title"] != site["name"]
    assert home["template_key"] == "automotive_detailing"
    assert {action["kind"] for action in home["actions"]} >= {
        "internal", "whatsapp", "location", "social",
    }
    assert next(action for action in home["actions"] if action["id"] == "instagram")["href"] == (
        "https://www.instagram.com/utziggarage"
    )
    assert {
        site["identity"][key]["node_id"]
        for key in ("logo_round", "logo_wordmark", "logo_reverse")
    } == {"asset:logo"}

    page_refs = [nodes[item["node_id"]] for item in site["pages"]]
    assert {page["data"]["page"]["route"] for page in page_refs} == {
        "/",
        "/estetica-automotiva",
    }
    location = nodes["campaign:physical-store"]["data"]
    assert location["campaign_subtype"] == "physical_store"
    assert location["location"]["coordinates"] == {
        "latitude": -29.5117618,
        "longitude": -50.99811,
    }
