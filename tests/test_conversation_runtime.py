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


def test_reply_confirms_price_or_schedule_blocks_only_genuine_confirmations():
    unsafe = conversation_runtime._reply_confirms_price_or_schedule
    assert unsafe("Perfeito, confirmo o agendamento para amanhã às 14h.")
    assert unsafe("Valor fechado em R$ 350,00, pode deixar reservado.")
    assert not unsafe(
        "A higienização interna leva cerca de 3 horas e parte de R$ 350,00."
    )
    assert not unsafe(
        "Não. Toda data e horário dependem de confirmação humana da Equipe Aurora."
    )
    assert not unsafe(None)
    assert not unsafe("")


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


HUMAN_ONLY = {"price_disclosure": "human_only"}
PAYMENT_POLICY_NODE = {
    "id": "rule-operation",
    "node_type": "rule",
    "data": {
        "claims": [
            {
                "claim_type": "payment_policy",
                "policy": {"mode": "informational"},
                "evidence_node_ids": ["rule-operation"],
            }
        ]
    },
}


def test_reply_states_a_price_blocks_every_price_shape():
    blocked = conversation_runtime._reply_states_a_price
    for text in (
        "R$ 650",
        "R$ 1.197,00",
        "650 reais",
        "custa 897",
        "fica em torno de 1.197",
        "a partir de 350",
        "O polimento custa R$ 650,00.",
        "O investimento fica por 1.290,00 dependendo do carro.",
    ):
        assert blocked(text, HUMAN_ONLY), text


def test_reply_states_a_price_allows_non_price_figures():
    blocked = conversation_runtime._reply_states_a_price
    for text in (
        "Reagendamentos precisam de 48 horas de antecedência.",
        "Parcelamos em até 4x sem juros.",
        "o carro é de 2020",
        "A higienização leva cerca de 3 horas.",
        "Atendemos até 5 clientes por dia.",
    ):
        assert not blocked(text, HUMAN_ONLY), text
    assert not blocked(None, HUMAN_ONLY)
    assert not blocked("", HUMAN_ONLY)


def test_reply_states_a_price_carves_out_published_payment_policy():
    """The carve-out is evidence-driven, never wording-driven.

    The same sentence is blocked when nothing in the cited graph evidence
    authorizes stating money, and allowed when a cited node publishes a
    ``payment_policy`` claim (deposit threshold, installment terms).
    """
    blocked = conversation_runtime._reply_states_a_price
    text = (
        "Aceitamos Pix, dinheiro e cartão — até 4x sem juros ou até 10x com "
        "acréscimo. Para serviços acima de R$ 2.000,00 é necessário um sinal "
        "de 10% do valor para reservar a agenda."
    )
    assert not blocked(text, HUMAN_ONLY, cited_nodes=[PAYMENT_POLICY_NODE])
    assert blocked(text, HUMAN_ONLY, cited_nodes=[{"id": "x", "data": {}}])
    # No cited evidence at all is never an authorization.
    assert blocked(text, HUMAN_ONLY)


def test_reply_states_a_price_is_inert_without_the_published_policy():
    """Personas that legitimately quote prices are untouched."""
    blocked = conversation_runtime._reply_states_a_price
    for policy in ({}, {"price_disclosure": "agent"}, {"required_fields": ["nome"]}):
        assert not blocked("Red Bull 250 ml: R$ 15,00.", policy)
        assert not blocked("a partir de 350", policy)


def test_price_disclosure_guard_is_inert_for_a_persona_without_the_policy(monkeypatch):
    """End-to-end: the price-quoting persona still answers with its price."""
    install_graph(monkeypatch)
    context = context_for("Quanto custa o Red Bull 250 ml?")
    decision, response = conversation_runtime.decide(context)
    assert conversation_runtime._context_appointment_policy(context) == {}
    assert not conversation_runtime._reply_states_a_price(
        response.reply_text,
        conversation_runtime._context_appointment_policy(context),
        cited_nodes=conversation_runtime._cited_context_nodes(context, decision),
    )


def test_build_system_prompt_adds_the_price_rule_only_when_the_graph_asks(monkeypatch):
    graph = graph_fixture()
    baseline = conversation_runtime.build_system_prompt(graph)
    assert "Nunca informe preco" not in baseline

    guarded = graph.model_copy(deep=True)
    persona = next(node for node in guarded.nodes if node.node_type == "persona")
    persona.data = {
        **(persona.data or {}),
        "appointment_policy": {"price_disclosure": "human_only"},
    }
    prompt = conversation_runtime.build_system_prompt(guarded)
    assert "Nunca informe preco" in prompt
    assert "parcelamento ou desconto" in prompt


def test_handoff_branch_reset_facts_requires_an_actual_handoff():
    """Regression test for the servico-wipe bug reproduced live 2026-08-09.

    Production evidence (leads 116 and 118, Aurora `sdr_qualificacao_carro`,
    today): `handoff_level` only encodes whether name+service are *known*,
    which becomes "full" as early as turn 2 of any ordinary appointment
    conversation -- the moment the customer's name is captured, right after
    they already named the service in turn one. The DB showed "servico"
    superseded to status="invalid"/value=null at that exact turn, with no
    handoff ever requested or authorized, which is why the agent then
    re-asked "qual serviço você procura" 2-3 times before recovering. The
    reset must require `handoff_required` -- a handoff actually completing
    this turn -- not merely the lead already having a name and a service on
    file.
    """
    branch_contract = {"fields": [
        {"key": "servico", "owner_node_id": "branch:a"},
        {"key": "relato", "owner_node_id": "branch:a"},
    ]}
    branch_facts = {
        "servico": {"status": "known", "value": "Higienização interna"},
        "relato": {"status": "known", "value": "Cheiro forte"},
    }

    # Ordinary turn: name+service are both known ("full"), but no handoff
    # was requested this turn -- must NOT reset anything.
    assert conversation_runtime._handoff_branch_reset_facts(
        handoff_required=False, handoff_level="full", active_branch="branch:a",
        branch_contract=branch_contract, branch_facts=branch_facts,
        correlation_id="corr-1",
    ) == []

    # A genuine handoff completing (handoff_required=True) with full
    # registration IS the documented case this reset exists for.
    reset = conversation_runtime._handoff_branch_reset_facts(
        handoff_required=True, handoff_level="full", active_branch="branch:a",
        branch_contract=branch_contract, branch_facts=branch_facts,
        correlation_id="corr-2",
    )
    assert {fact["field_key"] for fact in reset} == {"servico", "relato"}
    assert all(fact["status"] == "invalid" and fact["value"] is None for fact in reset)

    # A partial handoff (name or service still missing) never resets either.
    assert conversation_runtime._handoff_branch_reset_facts(
        handoff_required=True, handoff_level="partial", active_branch="branch:a",
        branch_contract=branch_contract, branch_facts=branch_facts,
        correlation_id="corr-3",
    ) == []
