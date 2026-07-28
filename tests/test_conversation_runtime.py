from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from schemas.conversation import ConversationContext, ConversationRoute
from services import conversation_runtime
from services.sdr_documents import compile_persona_documents


def graph_fixture():
    return compile_persona_documents(
        ROOT / "docs" / "sdr",
        "baita-conveniencia",
    )


def context_for(message: str, *, cart=None, history=None):
    graph = graph_fixture()
    mandatory = [
        node
        for node in graph.nodes
        if node.node_type in {"persona", "brand", "tone", "rule", "briefing"}
    ]
    messages = list(history or []) + [
        {"role": "user", "sender_type": "lead", "texto": message}
    ]
    return ConversationContext(
        persona_slug="baita-conveniencia",
        agent_slug="vitoria",
        graph_version=1,
        graph_checksum="checksum",
        messages=messages[-20:],
        cart=cart or {"_lead_stage": "novo"},
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
            for node in mandatory
        ],
        rag_paths=[[node.id] for node in mandatory],
    )


def install_graph(monkeypatch):
    graph = graph_fixture()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda persona_slug: (1, "checksum", graph),
    )
    return graph


def test_price_is_grounded_and_routes_to_sdr(monkeypatch):
    graph = install_graph(monkeypatch)
    context = context_for("Quanto custa o Red Bull 250 ml?")
    decision, response = conversation_runtime.decide(context)
    product = next(
        node for node in graph.nodes if node.slug == "red-bull-250ml"
    )
    assert decision.route == ConversationRoute.SDR
    assert decision.product_slug == "red-bull-250ml"
    assert response.reply_text == "Red Bull 250 ml: R$ 15,00."
    assert product.id in response.evidence_node_ids


def test_cart_progresses_to_closer_and_final_handoff(monkeypatch):
    install_graph(monkeypatch)
    history = [
        {
            "role": "user",
            "sender_type": "lead",
            "texto": "Quanto custa o Red Bull 250 ml?",
        }
    ]
    decision, response = conversation_runtime.decide(
        context_for("quero 2", history=history)
    )
    assert decision.route == ConversationRoute.CLOSER
    assert response.cart_state["items"][0]["quantity"] == 2

    _, response = conversation_runtime.decide(
        context_for("Cliente QA", cart=response.cart_state)
    )
    _, response = conversation_runtime.decide(
        context_for("Rua QA, 100, Canoas", cart=response.cart_state)
    )
    decision, response = conversation_runtime.decide(
        context_for("Sim", cart=response.cart_state)
    )
    assert decision.route == ConversationRoute.HUMAN
    assert decision.handoff_reason == "confirmed_pending_human"
    assert response.handoff_required is True
    assert response.cart_state["confirmation_status"] == "confirmed_pending_human"


def test_explicit_human_request_never_generates_ai_route(monkeypatch):
    install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for("Quero falar com um atendente")
    )
    assert decision.route == ConversationRoute.HUMAN
    assert response.handoff_required is True


def test_model_schema_gets_exactly_one_correction_attempt():
    context = context_for("Oi")
    evidence_id = context.rag_nodes[0]["id"]

    class Router:
        def __init__(self):
            self.calls = 0

        def chat(self, model, prompt, max_tokens):
            self.calls += 1
            if self.calls == 1:
                return '{"route":"INVALID"}'
            return (
                "{"
                '"intent":"greeting","route":"SDR","confidence":0.99,'
                '"cart_action":"none","product_slug":null,"quantity":null,'
                '"lead_stage":"contatado","handoff_reason":null,'
                f'"evidence_node_ids":["{evidence_id}"]'
                "}"
            )

    router = Router()
    decision = conversation_runtime.strict_model_decision(
        context,
        router=router,
        model="test-model",
    )
    assert decision.route == ConversationRoute.SDR
    assert router.calls == 2
