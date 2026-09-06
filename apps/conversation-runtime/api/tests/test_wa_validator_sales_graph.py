from __future__ import annotations

import json
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import (
    graph_agent_runtime_v3,
    graph_bundle,
    validator_sofia_insights,
    wa_validator_service,
)


def _publication() -> dict:
    bundle = json.loads(
        (REPO_ROOT / "data" / "graph_bundles" / "tock-fatal" / "sdr-qualification-v1.json")
        .read_text(encoding="utf-8")
    )
    document = graph_bundle.compile_bundle(bundle)
    return {
        "version": 1,
        "status": "active",
        "checksum": document["checksum"],
        "document_json": document,
    }


def _v17_publication() -> dict:
    bundle = json.loads(
        (
            REPO_ROOT
            / "data"
            / "graph_bundles"
            / "tock-fatal"
            / "sdr-qualification-v17-sales-conversation-repair.json"
        ).read_text(encoding="utf-8")
    )
    document = graph_bundle.compile_bundle(bundle)
    return {
        "version": 14,
        "status": "candidate",
        "checksum": document["checksum"],
        "document_json": document,
    }


def test_sales_semantic_scripts_select_distinct_graph_branches():
    publication = _publication()

    retail = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_retail"
    )
    reseller = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_reseller"
    )

    assert retail["driver"]["mode"] == "semantic_graph_v1"
    assert retail["driver"]["branch_anchor_node_id"] == "audience:tock-retail"
    assert reseller["driver"]["branch_anchor_node_id"] == "audience:tock-reseller"
    assert retail["driver"]["branch_anchor_node_id"] != reseller["driver"]["branch_anchor_node_id"]
    assert retail["driver"]["doubt"]["forbidden_claim_patterns"]


def test_sales_opening_resolves_and_emits_the_published_selector_field():
    publication = _publication()
    document = publication["document_json"]
    script = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_retail"
    )

    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document,
        script["driver"]["opening"]["text"],
        active_branch_node_id=None,
        active_branch_node_ids=[],
    )
    assert resolution["status"] == "resolved"
    assert resolution["focused_branch_node_id"] == "audience:tock-retail"
    facts = graph_agent_runtime_v3._service_facts_for_operations(
        operations=resolution["operations"],
        document=document,
        grouped_facts={},
        source_message_id="validator:opening",
    )
    assert facts == [{
        "field_key": "purchase_profile",
        "owner_node_id": "audience:tock-retail",
        "status": "known",
        "value": "uso-proprio-varejo",
        "source_message_id": "validator:opening",
        "evidence_span": "uso próprio",
        "confidence": 1.0,
        "metadata": {
            "source": "service_resolution",
            "operation": "add",
            "evidence_type": "exact_catalog",
            "resolution_method": "exact_catalog",
            "score": None,
            "margin": None,
            "branch_path_checksum": document["coordinates"]["audience:tock-retail"]["path_checksum"],
        },
    }]


def test_sales_bundle_publishes_a_safe_unknown_commercial_deferral():
    document = _publication()["document_json"]
    policy = document["common_contract"]["conversation_policy"]

    assert policy["doubt_handling"]["deferred_response"] == (
        "Ainda não tenho uma informação publicada e validada sobre preço, estoque, "
        "prazo, política ou pedido mínimo. Vou encaminhar sua dúvida para a equipe."
    )
    assert policy["safety"][
        "forbid_unpublished_price_stock_deadline_policy"
    ] is True
    assert policy["question_repetition"] == {"max_attempts": 1}


def test_graph_context_falls_back_to_active_v3_without_legacy_v2(monkeypatch):
    publication = _publication()
    monkeypatch.setattr(
        wa_validator_service.graph_json_v2_store, "load_current", lambda _slug: None
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "4acb2739-127e-4143-acf5-f5c3ea1aaa98"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: publication,
    )

    context, version, checksum, graph = wa_validator_service._build_graph_context(
        "tock-fatal"
    )

    assert version == 1
    assert checksum == publication["checksum"]
    assert "persona:tock-fatal" in context
    assert wa_validator_service.conversation_runtime._business_model(graph) == "sales"


def test_graph_context_does_not_mask_invalid_legacy_v2(monkeypatch):
    monkeypatch.setattr(
        wa_validator_service.graph_json_v2_store,
        "load_current",
        lambda _slug: (1, object()),
    )
    monkeypatch.setattr(
        wa_validator_service,
        "_published_graph",
        lambda _slug: (_ for _ in ()).throw(ValueError("Graph JSON v2 publicado não está válido")),
    )
    try:
        wa_validator_service._build_graph_context("tock-fatal")
        raise AssertionError("expected invalid v2 rejection")
    except ValueError as exc:
        assert "não está válido" in str(exc)


def test_graph_context_rejects_inconsistent_v3_and_uses_top_level_node_status(monkeypatch):
    publication = _publication()
    document = publication["document_json"]
    for node in document["nodes"]:
        node["data"].pop("status", None)
    unsigned = dict(document)
    unsigned.pop("checksum", None)
    document["checksum"] = wa_validator_service.graph_compiler_v3.canonical_checksum(unsigned)
    publication["checksum"] = document["checksum"]
    monkeypatch.setattr(
        wa_validator_service.graph_json_v2_store, "load_current", lambda _slug: None
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "4acb2739-127e-4143-acf5-f5c3ea1aaa98"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: publication,
    )
    context, _version, _checksum, _graph = wa_validator_service._build_graph_context(
        "tock-fatal"
    )
    assert "persona:tock-fatal" in context

    publication["checksum"] = "sha256:tampered"
    try:
        wa_validator_service._build_graph_context("tock-fatal")
        raise AssertionError("expected inconsistent v3 rejection")
    except ValueError as exc:
        assert "inconsistente" in str(exc)


def test_validator_gaps_become_review_only_sofia_proposals():
    review = validator_sofia_insights.build_sofia_review(
        persona_slug="tock-fatal",
        session_id="session-1",
        gaps=[{
            "topic": "expected_branch_persisted",
            "evidence": "O runtime selecionou o galho errado.",
            "priority": "high",
        }, {
            "topic": "unsupported_claim_not_invented",
            "evidence": "A resposta afirmou preço sem evidência.",
            "priority": "high",
        }],
    )

    assert review["status"] == "pending_human_review"
    assert review["automatic_mutation"] is False
    assert [item["kind"] for item in review["proposals"]] == [
        "branch_resolution_review", "knowledge_gap"
    ]
    assert all(item["publication_allowed"] is False for item in review["proposals"])


def test_question_already_asked_detects_personalized_repeat():
    # The engine-isolation split (309b912) removed this predicate from the
    # agentic proof module but left a call to it in the validator's quality
    # scoring, so every second turn crashed with AttributeError. Keep the
    # validator's own copy wired and matching personalized rewordings.
    canonical = "Qual e a cor do veiculo?"
    assert wa_validator_service._question_already_asked(
        canonical, "Perfeito! Qual e a cor do seu Onix?"
    )
    assert wa_validator_service._question_already_asked(canonical, canonical)
    assert not wa_validator_service._question_already_asked(
        canonical, "Show! Como voce se chama?"
    )


def test_v17_sales_validator_answers_new_fields_and_covers_store_and_shipping():
    publication = _v17_publication()

    retail = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_retail"
    )["driver"]
    reseller = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_reseller"
    )["driver"]

    assert {"nome_cliente", "grau_qualificacao", "forma_recebimento"}.issubset(
        retail["required_fields"]
    )
    assert retail["answers"]["nome_cliente"]["value"] == "Beatriz"
    assert retail["answers"]["forma_recebimento"]["value"] == "visita_loja"
    assert reseller["answers"]["forma_recebimento"]["value"] == "envio"
    assert wa_validator_service._resolve_initial_state(
        "known_name", "sdr_sales_retail"
    ) == "known_name"
    known_name = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_retail", initial_state="known_name"
    )
    assert known_name["expected_dialogue"] == {
        "branch_anchor_node_id": "audience:tock-retail",
        "unsupported_claims_forbidden": True,
        "known_name": "Beatriz",
        "client_name_omitted": True,
    }


def test_v17_sales_validator_builds_exact_photo_and_no_photo_scenarios():
    publication = _v17_publication()

    available = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_photo_available"
    )["steps"][0]
    unavailable = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_photo_unavailable"
    )["steps"][0]

    assert available["photo_expectation"] == "approved_asset"
    assert len(available["expected_evidence_node_ids"]) == 1
    assert "approved-photo" in available["expected_evidence_node_ids"][0]
    assert unavailable["photo_expectation"] == "human_followup"
    assert unavailable["expected_evidence_node_ids"] == ["faq:tock-photo-unavailable"]
    assert unavailable["expected_handoff_now"] is True
    assert unavailable["allow_incomplete_handoff"] is True


def test_v17_sales_validator_requires_ai_identity_and_human_freight_confirmation():
    opening = wa_validator_service._semantic_sales_script(
        publication=_v17_publication(), flow_id="sdr_sales_freight"
    )["steps"][0]

    requirements = wa_validator_service._reply_content_requirements(
        opening,
        "Oi! Eu sou a Vitória, assistente virtual com inteligência artificial da Tock Fatal. "
        "Uma pessoa da equipe confirmará o frete para você.",
    )
    assert all(requirements.values())
    assert not all(wa_validator_service._reply_content_requirements(
        opening, "O frete custa R$ 20 e chega em 2 dias.",
    ).values())


def test_sales_quality_audit_rejects_internal_terms_and_silent_handoff():
    contract = {
        "conversation_policy": {
            "sales_routing": {
                "forbidden_customer_facing_terms": [
                    "serviço", "grupo de produtos", "branch", "node", "retrieval"
                ]
            }
        }
    }

    assert wa_validator_service._sales_internal_language_absent(
        "Entre as opções de conjuntos, temos modelos casuais.", contract
    )
    assert not wa_validator_service._sales_internal_language_absent(
        "Nesse grupo de produtos, escolha um serviço.", contract
    )
    assert wa_validator_service._pre_handoff_notice_observed(
        "Vou avisar uma pessoa da equipe para continuar o atendimento com você."
    )
    assert not wa_validator_service._pre_handoff_notice_observed("")
