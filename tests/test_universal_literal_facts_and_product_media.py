from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.conversation import (
    AgentResponse,
    ConversationRoute,
    CustomerQuestion,
    CustomerQuestionKind,
    SemanticInterpretation,
)
from services import (
    conversation_runtime,
    graph_agent_runtime_v3,
    graph_bundle,
    graph_proof_checker_v3,
)
from services.semantic_interpretation_validator import ValidationResult


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v11-product-media.json"


@pytest.mark.parametrize(
    ("message", "span"),
    [
        ("Somente quando viajo", "Somente quando viajo"),
        ("Sim, toda semana", "Sim, toda semana"),
        ("Quero umas oito pecas variadas", "Quero umas oito pecas variadas"),
        ("Atendo cerca de vinte pacientes por mes", "Atendo cerca de vinte pacientes por mes"),
        ("Prefiro depois das seis", "Prefiro depois das seis"),
        ("Hoje compro so quando aparece pedido", "Hoje compro so quando aparece pedido"),
    ],
)
def test_literal_text_capture_preserves_customer_language(message: str, span: str):
    field = {
        "capture_mode": "literal_text_v1",
        "value_schema": {"type": "string", "minLength": 1},
    }
    value, error = graph_proof_checker_v3._canonical_field_value(
        field, "categoria inventada", span, message=message,
    )
    assert error is None
    assert value == span


def test_unknown_and_needs_confirmation_do_not_complete_required_field():
    contract = {
        "fields": [{
            "key": "contexto", "owner_node_id": "persona:test", "required": True,
            "accepted_statuses": ["known", "unknown", "declined", "needs_confirmation"],
        }]
    }
    for status in ("unknown", "declined", "needs_confirmation"):
        missing = graph_proof_checker_v3.pending_fields(
            contract, {"contexto": {"status": status, "value": None}},
        )
        assert [field["key"] for field in missing] == ["contexto"]


def test_backend_never_creates_ignored_twice_fact():
    assert graph_agent_runtime_v3._unanswered_fact_after_question_limit(
        context=None, contract={}, ledger_facts={}, proposal=None,
    ) is None


def _response(*, complete: bool, next_question: str | None, notice: str | None):
    return AgentResponse(
        reply_text=notice,
        role=ConversationRoute.HUMAN,
        cart_state={},
        handoff_required=True,
        proof={
            "qualification_complete": complete,
            "next_question_node_id": next_question,
        },
    )


def test_full_handoff_requires_completion_notice_and_no_question():
    assert conversation_runtime._graph_handoff_level(
        _response(complete=True, next_question=None, notice="Vou encaminhar agora.")
    ) == "full"
    assert conversation_runtime._graph_handoff_level(
        _response(complete=True, next_question="q:one", notice="Vou encaminhar. E sua cidade?")
    ) == "partial"
    assert conversation_runtime._graph_handoff_level(
        _response(complete=False, next_question=None, notice="Vou encaminhar agora.")
    ) == "partial"
    assert conversation_runtime._graph_handoff_level(
        _response(complete=True, next_question=None, notice=None)
    ) == "partial"


def _compiled_tock() -> dict:
    return graph_bundle.compile_bundle(json.loads(BUNDLE.read_text(encoding="utf-8")))


def test_tock_bundle_links_every_approved_image_to_product_and_gallery():
    document = _compiled_tock()
    nodes = document["node_by_id"]
    assets = [node for node in document["nodes"] if node["node_type"] == "asset"]
    approved = [
        node for node in assets
        if (node.get("data") or {}).get("asset_role") == "primary_product_media"
    ]
    assert len(approved) == 4
    edges = document["edges"]
    for asset in approved:
        product_id = asset["data"]["product_node_id"]
        assert nodes[product_id]["node_type"] == "product"
        assert any(
            edge["source"] == product_id and edge["target"] == asset["id"]
            and edge["relation_type"] == "contains"
            for edge in edges
        )
        assert any(
            edge["source"] == asset["id"] and edge["target"] == "gallery:tock-default"
            and edge["relation_type"] == "gallery_asset"
            for edge in edges
        )


def test_media_resolver_returns_four_items_in_requested_order():
    document = _compiled_tock()
    product_ids = [
        "product:tock-blusas-bodies-camisas-e-partes-de-cima-body-rendado",
        "product:tock-blusas-bodies-camisas-e-partes-de-cima-body-mula-manca",
        "product:tock-blusas-bodies-camisas-e-partes-de-cima-blusa-em-poa",
        "product:tock-blusas-bodies-camisas-e-partes-de-cima-blusa-tule-texturizado",
    ]
    interpretation = SemanticInterpretation(
        questions=[CustomerQuestion(
            kind=CustomerQuestionKind.MEDIA,
            topic="fotos das roupas",
            entity_node_ids=product_ids,
            evidence_span="manda as fotos dessas roupas",
        )]
    )
    result = graph_agent_runtime_v3._media_delivery_request(
        ValidationResult(valid=True, interpretation=interpretation), document, [],
    )
    assert result["errors"] == []
    assert [item["product_node_id"] for item in result["items"]] == product_ids
    assert all(item["bucket"] == "assets-raw" for item in result["items"])


def test_media_resolver_supports_more_than_five_items_without_persona_code():
    document = _compiled_tock()
    original_product = document["node_by_id"][
        "product:tock-blusas-bodies-camisas-e-partes-de-cima-body-rendado"
    ]
    original_asset = next(
        node for node in document["nodes"]
        if (node.get("data") or {}).get("product_node_id") == original_product["id"]
    )
    product_ids = []
    for index in range(6):
        product_id = f"product:test:{index}"
        asset_id = f"asset:test:{index}"
        product = {**original_product, "id": product_id, "title": f"Produto {index}"}
        asset = {
            **original_asset, "id": asset_id,
            "data": {**original_asset["data"], "product_node_id": product_id},
        }
        document["nodes"].extend([product, asset])
        document["node_by_id"][product_id] = product
        document["node_by_id"][asset_id] = asset
        document["edges"].extend([
            {"source": product_id, "target": asset_id, "relation_type": "contains"},
            {"source": asset_id, "target": "gallery:tock-default", "relation_type": "gallery_asset"},
        ])
        product_ids.append(product_id)
    interpretation = SemanticInterpretation(questions=[CustomerQuestion(
        kind="media", topic="seis fotos", entity_node_ids=product_ids,
        evidence_span="manda as seis fotos",
    )])
    result = graph_agent_runtime_v3._media_delivery_request(
        ValidationResult(valid=True, interpretation=interpretation), document, [],
    )
    assert len(result["items"]) == 6
    assert result["errors"] == []


def test_tock_media_policy_has_matching_faq_copy_and_prompt_rule():
    document = _compiled_tock()
    nodes = document["node_by_id"]
    assert nodes["faq:tock-product-media-delivery"]["data"]["answer"]
    assert nodes["copy:tock-product-media-delivery"]["data"]["content"]
    assert "kind=media" in nodes["rule:tock-product-media-delivery"]["data"]["instruction"]
    policy = nodes["persona:tock-fatal"]["data"]["conversation_policy"]["content_delivery"]
    assert policy["max_items"] == 20
    assert policy["batch_policy"] == "all_or_nothing"
