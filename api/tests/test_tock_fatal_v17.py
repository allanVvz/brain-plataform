from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v16-voice-reachable.json"
BUILDER_PATH = ROOT / "api/scripts/build_tock_fatal_v17.py"

spec = importlib.util.spec_from_file_location("build_tock_fatal_v17", BUILDER_PATH)
builder = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(builder)


def _candidate() -> dict:
    return builder.build(json.loads(SOURCE_PATH.read_text(encoding="utf-8")))


def _nodes(bundle: dict) -> dict[str, dict]:
    return {node["id"]: node for node in bundle["nodes"]}


def test_v17_adds_persona_owned_name_readiness_and_fulfillment_fields():
    bundle = _candidate()
    nodes = _nodes(bundle)
    persona = nodes["persona:tock-fatal"]
    fields = (persona["data"]["qualification"] or {})["fields"]
    by_key = {field["key"]: field for field in fields}

    assert set(by_key) == {"nome_cliente", "grau_qualificacao", "forma_recebimento"}
    assert by_key["nome_cliente"]["owner_node_id"] == "persona:tock-fatal"
    assert by_key["nome_cliente"]["validation"]["semantic_type"] == "human_full_name"
    assert by_key["nome_cliente"]["validation"]["min_tokens"] == 1
    assert by_key["nome_cliente"]["validation"]["extraction_required_when_expected"] is True
    assert by_key["nome_cliente"]["validation"]["acknowledgement_requires_fact"] is True
    assert by_key["nome_cliente"]["validation"]["model_confidence_min"] == 0.0
    assert by_key["nome_cliente"]["depends_on"] == ["purchase_profile"]
    assert persona["data"]["conversation_policy"]["sales_routing"]["service_selector_enabled"] is False

    question_policy = persona["data"]["conversation_policy"]["question_policy"]
    assert question_policy["current_turn_facts_precede_question"] is True
    assert question_policy["never_ask_field_answered_in_current_message"] is True
    assert question_policy["branch_selection_question_forbidden_after_profile_understood"] is True
    assert question_policy["preferred_field_order_after_purchase_profile"][0] == "nome_cliente"
    assert any("Nunca pergunte novamente o perfil de compra" in item for item in question_policy["instructions"])
    assert any("pode me chamar de X" in item for item in question_policy["instructions"])
    assert any("deixando esse fato fora de facts" in item for item in question_policy["instructions"])

    for audience_id in ("audience:tock-retail", "audience:tock-reseller"):
        branch_fields = nodes[audience_id]["data"]["qualification"]["fields"]
        for field in branch_fields:
            if field["key"] != "purchase_profile":
                assert "nome_cliente" in field["depends_on"]
        assert not any(field["key"] in {"servico", "service"} for field in branch_fields)


def test_every_new_approved_faq_is_projected_to_embedded_once():
    bundle = _candidate()
    new_faqs = [
        node for node in bundle["nodes"]
        if (node.get("data") or {}).get("source") == builder.SOURCE
        and node.get("node_type") == "faq"
        and node["id"] not in {
            "faq:tock-greeting-oi", "faq:tock-greeting-ola",
            "faq:tock-greeting-bom-dia", "faq:tock-greeting-boa-tarde",
            "faq:tock-greeting-boa-noite", "faq:tock-greeting-tudo-bem",
        }
    ]
    assert len(new_faqs) == 18
    for faq in new_faqs:
        projections = [
            edge for edge in bundle["edges"]
            if edge["source"] == faq["id"]
            and edge["target"] == "embed:tock-default"
            and edge["relation_type"] == "publishes_to"
        ]
        assert len(projections) == 1, faq["id"]
        assert faq["data"]["source_node_id"]
        assert faq["data"]["source_node_type"]
        assert faq["data"]["branch_path"][-1] == faq["id"]


def test_v17_introduces_vitoria_as_ai_only_in_opening_content():
    bundle = _candidate()
    nodes = _nodes(bundle)
    greeting_ids = nodes["persona:tock-fatal"]["data"]["conversation_policy"]["intents"]["greeting"]["response_node_ids"]
    for node_id in greeting_ids:
        answer = nodes[node_id]["data"]["answer"]
        assert "Vitória" in answer
        assert "inteligência artificial" in answer
    opening = nodes["persona:tock-fatal"]["data"]["conversation_policy"]["opening"]
    assert opening["self_introduction_required_on_first_reply"] is True


def test_v17_removes_technical_navigation_language():
    bundle = _candidate()
    for node in bundle["nodes"]:
        if node.get("node_type") != "faq" or not str(node.get("id") or "").endswith("-navegacao"):
            continue
        answer = str((node.get("data") or {}).get("answer") or "").casefold()
        assert "no grupo " not in answer
        assert "opções publicadas" not in answer


def test_photo_policy_distinguishes_four_approved_assets_from_missing_media():
    bundle = _candidate()
    nodes = _nodes(bundle)
    photo_faqs = [
        node for node in bundle["nodes"]
        if node.get("node_type") == "faq"
        and (node.get("data") or {}).get("media_availability")
    ]
    assert len(photo_faqs) == 4
    for faq in photo_faqs:
        media = faq["data"]["media_availability"]
        assert media["status"] == "approved"
        assert nodes[media["asset_node_id"]]["node_type"] == "asset"
        assert media["sha256"]

    unavailable = nodes["faq:tock-photo-unavailable"]["data"]
    assert "Quando não houver uma foto aprovada" in unavailable["answer"]
    assert "atendente" in unavailable["answer"]
    content_policy = nodes["persona:tock-fatal"]["data"]["conversation_policy"]["content_delivery"]
    assert content_policy["offer_only_when_exact_product_has_approved_asset"] is True
    assert content_policy["without_approved_asset"]["mention_only_after_explicit_photo_request"] is True


def test_handoff_notice_and_freight_specialist_are_graph_owned():
    bundle = _candidate()
    nodes = _nodes(bundle)
    policy = nodes["persona:tock-fatal"]["data"]["conversation_policy"]
    assert policy["handoff"]["pre_notice_required"] is True
    assert policy["handoff"]["silent_handoff_forbidden"] is True
    assert "pessoa da equipe" in policy["handoff"]["notice"]
    assert "especialista" in nodes["faq:tock-freight-value"]["data"]["answer"]
    assert "visitar a loja física" in nodes["faq:tock-fulfillment-preference"]["data"]["question"]
