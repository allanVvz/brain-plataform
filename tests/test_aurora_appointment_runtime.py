from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from schemas.conversation import ConversationContext, ConversationRoute
from schemas.graph_json_v2 import GraphJson
from services import conversation_runtime, graph_json_v2_validator
from services.deterministic_appointment import DeterministicAppointment
from services.deterministic_sdr import catalog_from_graph


def aurora_graph() -> GraphJson:
    payload = json.loads(
        (ROOT / "api" / "scripts" / "fixtures" / "aurora_graph_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return GraphJson.model_validate(payload)


def context_for(message: str, *, cart: dict | None = None) -> ConversationContext:
    graph = aurora_graph()
    return ConversationContext(
        persona_slug="aurora",
        agent_slug="aurora",
        graph_version=2,
        graph_checksum="aurora-checksum",
        messages=[{"role": "user", "sender_type": "lead", "texto": message}],
        cart={"_lead_stage": "novo", **(cart or {})},
        rag_nodes=[
            {
                "id": node.id,
                "node_type": node.node_type,
                "slug": node.slug,
                "title": node.label,
                "status": node.data.get("status"),
                "source": node.data.get("source"),
                "data": node.data,
            }
            for node in graph.nodes
        ],
        rag_paths=[[node.id] for node in graph.nodes],
    )


def install_graph(monkeypatch) -> GraphJson:
    graph = aurora_graph()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda _persona_slug: (2, "aurora-checksum", graph),
    )
    return graph


def test_aurora_graph_is_published_valid_and_every_faq_reaches_embedded_once():
    graph = aurora_graph()
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid, errors
    assert graph.status == "published"
    assert all(node.data.get("status") == "validated" for node in graph.nodes)
    assert all(
        node.data.get("source") == "user_authorized_demo_briefing_2026_07_29"
        for node in graph.nodes
    )
    embedded = next(node for node in graph.nodes if node.node_type == "embedded")
    faqs = [node for node in graph.nodes if node.node_type == "faq"]
    for faq in faqs:
        links = [
            edge
            for edge in graph.edges
            if edge.source == faq.id
            and edge.target == embedded.id
            and edge.relation == "visible_to_agent"
            and edge.primary_tree is False
        ]
        assert len(links) == 1
    gallery = next(node for node in graph.nodes if node.node_type == "gallery")
    assert gallery.data["empty"] is True
    assert not any(
        edge.target == gallery.id
        and next(node for node in graph.nodes if node.id == edge.source).node_type == "asset"
        for edge in graph.edges
    )


def test_catalog_reads_duration_price_qualifier_and_manual_confirmation():
    catalog = catalog_from_graph(aurora_graph())
    service = next(item for item in catalog.products if item.slug == "higienizacao-interna")
    assert service.price == 350
    assert service.price_qualifier == "starting_at"
    assert service.duration_minutes == 180
    assert service.capacity == 1
    assert service.confirmation_required is True
    assert service.booking_provider == "manual"
    assert "vehicle_model" in service.required_fields


def test_appointment_collects_partial_request_and_always_hands_confirmation_to_human():
    engine = DeterministicAppointment(catalog_from_graph(aurora_graph()))
    result = engine.handle("Quero agendar higienização interna")
    assert result.intent == "request_booking"
    assert result.handoff is False
    assert result.state["missing_fields"][0] == "customer_name"

    for answer in ("Allan", "Onix", "hatch", "bancos manchados", "10/08"):
        result = engine.handle(answer, state=result.state)
        assert result.handoff is False
    result = engine.handle("manhã", state=result.state)

    assert result.intent == "complete_booking_request"
    assert result.handoff is True
    assert result.handoff_reason == "appointment_confirmation_required"
    assert result.state["missing_fields"] == []
    assert result.state["appointment_request"] == {
        "service_slug": "higienizacao-interna",
        "customer_name": "Allan",
        "vehicle_model": "Onix",
        "vehicle_size": "hatch",
        "condition": "bancos manchados",
        "desired_date": "10/08",
        "time_window": "manhã",
    }
    assert result.reply == (
        "A higienização interna leva cerca de 3 horas e parte de R$ 350,00. "
        "Registrei sua preferência; a equipe confirmará o valor final e o horário."
    )


def test_runtime_selects_appointment_classifier_stage_and_graph_evidence(monkeypatch):
    graph = install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for(
            "manhã",
            cart={
                "business_model": "appointment",
                "conversation_state": "collecting",
                "appointment_request": {
                    "service_slug": "higienizacao-interna",
                    "customer_name": "Allan",
                    "vehicle_model": "Onix",
                    "vehicle_size": "hatch",
                    "condition": "bancos manchados",
                    "desired_date": "10/08",
                },
                "missing_fields": ["time_window"],
                "_lead_stage": "qualificado",
            },
        )
    )
    assert decision.classifier == "deterministic_appointment_v1"
    assert decision.intent == "complete_booking_request"
    assert decision.route == ConversationRoute.HUMAN
    assert decision.lead_stage == "oportunidade"
    assert decision.handoff_reason == "appointment_confirmation_required"
    assert response.handoff_required is True
    evidence_types = {
        node.node_type for node in graph.nodes if node.id in decision.evidence_node_ids
    }
    assert {"product", "faq", "rule"}.issubset(evidence_types)


def test_list_services_records_every_product_and_faq_as_graph_evidence(monkeypatch):
    graph = install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for("Quais serviços estão disponíveis?")
    )
    evidence_types = {
        node.node_type for node in graph.nodes if node.id in decision.evidence_node_ids
    }
    assert decision.intent == "list_services"
    assert decision.route == ConversationRoute.SDR
    assert {"product", "faq", "rule"}.issubset(evidence_types)
    assert sum(
        node.node_type == "product" and node.id in decision.evidence_node_ids
        for node in graph.nodes
    ) == 4
    assert "Serviços disponíveis:" in (response.reply_text or "")


def test_price_is_starting_at_and_exceptional_support_goes_directly_to_human(monkeypatch):
    install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for("Quanto custa o polimento técnico?")
    )
    assert decision.intent == "consult_price"
    assert decision.route == ConversationRoute.SDR
    assert "parte de R$ 650,00" in (response.reply_text or "")

    decision, response = conversation_runtime.decide(
        context_for("Quero reclamar da garantia")
    )
    assert decision.intent == "exceptional_support"
    assert decision.route == ConversationRoute.HUMAN
    assert response.handoff_required is True
    assert response.reply_text == "Vou encaminhar sua solicitação para a Equipe Aurora."


def test_unknown_message_clarifies_once_then_hands_off(monkeypatch):
    install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(context_for("xyzzy"))
    assert decision.intent == "ununderstood"
    assert decision.route == ConversationRoute.SDR
    assert response.cart_state["clarification_attempts"] == 1

    decision, response = conversation_runtime.decide(
        context_for("plugh", cart=response.cart_state)
    )
    assert decision.route == ConversationRoute.HUMAN
    assert decision.handoff_reason == "missing_approved_evidence"


def test_successful_turn_resets_unknown_attempt_counter(monkeypatch):
    install_graph(monkeypatch)
    _, first = conversation_runtime.decide(context_for("xyzzy"))
    decision, understood = conversation_runtime.decide(
        context_for(
            "Quanto custa a lavagem detalhada?",
            cart=first.cart_state,
        )
    )
    assert decision.intent == "consult_price"
    assert understood.cart_state["clarification_attempts"] == 0

    decision, next_unknown = conversation_runtime.decide(
        context_for("plugh", cart=understood.cart_state)
    )
    assert decision.route == ConversationRoute.SDR
    assert next_unknown.cart_state["clarification_attempts"] == 1
