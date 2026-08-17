from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from schemas.conversation import ConversationContext, ConversationRoute
from schemas.graph_json_v2 import GraphJson
from scripts.publish_aurora_graph import build_graph
from services import conversation_runtime, graph_json_v2_validator, graph_markdown
from services.deterministic_appointment import DeterministicAppointment
from services.deterministic_sdr import catalog_from_graph


# The briefing rewrite of 2026-08-07 dropped every fact the client never stated
# (service prices, durations, business hours). Two source stamps coexist on
# purpose: nodes carried over untouched from the earlier authorized briefing
# keep their original provenance instead of being relabelled.
AURORA_SOURCES = {
    "briefing_atendimento_conversacional_aurora_2026_08_07",
    "briefing_atendimento_conversacional_aurora_2026_08_09",
    "user_authorized_demo_briefing_2026_07_29",
}

# Only Aurora's published payment policy may state a value: the R$ 2.000,00
# threshold above which a 10% deposit reserves the agenda. No service price.
PAYMENT_POLICY_NODE_IDS = {
    "aurora-rule-operation",
    "aurora-faq-payment",
    "aurora-faq-deposit",
}
PAYMENT_POLICY_AMOUNTS = {"R$ 2.000,00"}

MONEY_PATTERNS = (re.compile(r"r\$\s*\d", re.I), re.compile(r"\d+\s*reais", re.I))
MONEY_AMOUNT = re.compile(r"R\$\s*[\d.,]*\d", re.I)


def aurora_graph() -> GraphJson:
    payload = json.loads(
        (ROOT / "api" / "scripts" / "fixtures" / "aurora_graph_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return GraphJson.model_validate(payload)


def canonical_aurora_graph() -> GraphJson:
    """The fixture as the platform stores it.

    The fixture deliberately ships without ``data.markdown``:
    ``graph_markdown.canonicalize_graph`` regenerates it from the data, which
    is what guarantees no rendered document can state a price the data no
    longer carries.
    """
    return graph_markdown.canonicalize_graph(aurora_graph())


def published_aurora_graph() -> GraphJson:
    """Exactly what a release publishes: v2.1 upgrade, materialized
    qualification questions, publication grants, regenerated markdown."""
    return graph_markdown.canonicalize_graph(build_graph())


def node_texts(node) -> str:
    """Everything a node can leak to a customer: its data and its markdown."""
    data = node.data or {}
    return "\n".join([json.dumps(data, ensure_ascii=False), str(data.get("markdown") or "")])


def appointment_policy_of(graph: GraphJson) -> dict:
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    return persona.data["appointment_policy"]


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
    # Validate the canonicalized graph: the fixture authors data only and lets
    # graph_markdown regenerate every document, so raw-fixture validation would
    # (correctly) complain about the missing data.markdown.
    graph = canonical_aurora_graph()
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    assert valid, errors
    assert graph.status == "published"
    assert all(node.data.get("status") == "validated" for node in graph.nodes)
    assert all(node.data.get("source") in AURORA_SOURCES for node in graph.nodes)
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


def test_catalog_reads_quote_only_capacity_and_manual_confirmation():
    """The briefing never published a price or a duration for any service.

    Every product is now ``quote_only`` with no price and no
    ``booking.duration_minutes``; daily capacity is 5 vehicles, and the Equipe
    Aurora still confirms every booking manually.
    """
    catalog = catalog_from_graph(aurora_graph())
    service = next(item for item in catalog.products if item.slug == "higienizacao-interna")
    assert service.price is None
    assert service.price_qualifier == "quote_only"
    assert service.duration_minutes is None
    assert service.capacity == 5
    assert service.confirmation_required is True
    assert service.booking_provider == "manual"
    assert "modelo_veiculo" in service.required_fields
    assert all(item.price is None for item in catalog.products)
    assert all(item.price_qualifier == "quote_only" for item in catalog.products)
    assert all(item.duration_minutes is None for item in catalog.products)


def test_appointment_collects_partial_request_and_always_hands_confirmation_to_human():
    graph = aurora_graph()
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=conversation_runtime._appointment_policy(graph),
    )
    result = engine.handle("Quero agendar higienização interna")
    assert result.intent == "request_booking"
    assert result.handoff is False
    assert result.state["missing_fields"][0] == "nome_cliente"

    for answer in ("Allan", "Quero vender em breve", "Consigo levar até a Aurora", "Onix", "2020"):
        result = engine.handle(answer, state=result.state)
        assert result.handoff is False
    result = engine.handle("Bancos meio manchados", state=result.state)

    assert result.intent == "complete_booking_request"
    assert result.handoff is True
    assert result.handoff_reason == "appointment_confirmation_required"
    assert result.state["missing_fields"] == []
    assert result.state["appointment_request"] == {
        "servico": "higienizacao-interna",
        "nome_cliente": "Allan",
        "modelo_veiculo": "Onix",
        "vehicle_year": "2020",
        "objective": "Quero vender em breve",
        "can_visit_in_person": "Consigo levar até a Aurora",
        "condicao": "Bancos meio manchados",
    }
    assert result.reply == (
        "A higienização interna. Anotei tudo por aqui. A Equipe Aurora vai te "
        "chamar para confirmar o valor e o melhor horário. Tem mais alguma "
        "coisa que você gostaria de melhorar no carro?"
    )
    assert "R$" not in result.reply


def test_already_handed_off_lead_keeps_handoff_flag_on_new_messages():
    """Regression test for the 2026-08-01 production finding.

    Once a lead's conversation_state becomes "handoff" (via the exceptional
    or human-request branches above, both of which correctly pass
    handoff=True), every later message short-circuits at the top of
    handle(). That branch used AppointmentResult's default handoff=False,
    so conversation_runtime.commit() never re-set response.handoff_required
    — the worker treated a silently-empty reply as a normal completed turn
    instead of keeping the lead flagged for a human. Confirmed live: a
    customer messaging an already-escalated conversation got zero reply
    and the lead was not kept paused.
    """
    graph = aurora_graph()
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=conversation_runtime._appointment_policy(graph),
    )
    handoff_result = engine.handle("Quero falar com atendente")
    assert handoff_result.handoff is True
    assert handoff_result.state["conversation_state"] == "handoff"

    result = engine.handle("Oi, ainda estao ai?", state=handoff_result.state)
    assert result.intent == "handoff"
    assert result.reply is None
    assert result.handoff is True


def test_resumed_lead_actually_retries_instead_of_staying_silent():
    """A human clicking "Resume AI" must make the agent try to answer again.

    api/services/agents_service.py::resume_lead clears the persisted sticky
    "handoff" flag (and clarification_attempts) before flipping ai_paused —
    mirror that reset here and confirm the engine reacts to the next message
    for real (greeting/FAQ/etc.), instead of the "already_handoff" short
    circuit a raw handoff-flagged state would still trigger.
    """
    graph = aurora_graph()
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=conversation_runtime._appointment_policy(graph),
    )
    handoff_result = engine.handle("Quero falar com atendente")
    assert handoff_result.handoff is True

    resumed_state = dict(handoff_result.state)
    resumed_state["conversation_state"] = ""
    resumed_state["clarification_attempts"] = 0

    result = engine.handle("Oi", state=resumed_state)
    assert result.intent == "greeting"
    assert result.reply
    assert result.handoff is False


def test_resumed_lead_falls_back_to_policy_text_and_re_pauses_when_still_unrecognized():
    """After resume, an unanswerable message must still end in an explicit
    fallback message (not silence) and hand off again — same guarantee as a
    first-time handoff, just reachable after a resume too."""
    graph = aurora_graph()
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=conversation_runtime._appointment_policy(graph),
    )
    handoff_result = engine.handle("Quero falar com atendente")
    resumed_state = dict(handoff_result.state)
    resumed_state["conversation_state"] = ""
    resumed_state["clarification_attempts"] = 0

    first = engine.handle("xyzabc123 qwerty", state=resumed_state)
    assert first.handoff is False
    assert first.reply

    second = engine.handle("xyzabc123 qwerty", state=first.state)
    assert second.handoff is True
    assert second.handoff_reason == "missing_approved_evidence"
    assert second.reply
    assert second.state["conversation_state"] == "handoff"


def test_commercial_note_fields_are_declared_per_persona_not_hardcoded():
    """Regression test for the 2026-08-01 finding.

    conversation_runtime used to hardcode the commercial_note field names
    (vehicle_size, condition, desired_date, time_window) and gate the whole
    mechanism to business_model == "appointment" — meaning no other persona
    (e.g. Baita, a sales/cart persona) could ever populate a commercial
    note no matter what its own graph declared. commercial_note_fields is
    now read from each persona's own graph data, any business model.
    """
    context = context_for("Oi", cart={"business_model": "appointment"})
    assert conversation_runtime._commercial_note_fields(context) == [
        "modelo_veiculo", "vehicle_year", "vehicle_color", "vehicle_size",
        "condicao", "objective", "data_desejada", "janela_horario",
    ]


def test_commercial_note_fields_defaults_to_empty_without_graph_declaration():
    context = context_for("Oi")
    for node in context.rag_nodes:
        if node.get("node_type") == "persona":
            node["data"] = {k: v for k, v in node["data"].items() if k != "commercial_note_fields"}
    assert conversation_runtime._commercial_note_fields(context) == []


def test_runtime_selects_appointment_classifier_stage_and_graph_evidence(monkeypatch):
    graph = install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for(
            "Consigo levar até a Aurora",
            cart={
                "business_model": "appointment",
                "conversation_state": "collecting",
                "appointment_request": {
                    "servico": "higienizacao-interna",
                    "nome_cliente": "Allan",
                    "modelo_veiculo": "Onix",
                    "vehicle_year": "2020",
                    "objective": "Quero vender em breve",
                    "condicao": "bancos manchados",
                },
                "missing_fields": ["can_visit_in_person"],
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
    ) == 15
    assert "Serviços da Aurora:" in (response.reply_text or "")


def test_price_always_goes_to_a_human_and_never_states_a_value(monkeypatch):
    """The client's briefing checks only "Perguntar antes de informar" and
    "Somente apos avaliacao" for price, and says explicitly that pricing has
    to stay manual because there are details a person must assess. The graph
    therefore publishes no service price at all and declares
    price_disclosure == "human_only", so a price question is a handoff — not
    a cheaper answer with a smaller number in it.
    """
    graph = install_graph(monkeypatch)
    policy = conversation_runtime._appointment_policy(graph)
    decision, response = conversation_runtime.decide(
        context_for("Quanto custa o polimento técnico?")
    )
    assert decision.intent == "consult_price"
    assert decision.route == ConversationRoute.HUMAN
    assert response.handoff_required is True
    assert response.reply_text == policy["texts"]["preco_humano"]
    assert "R$" not in (response.reply_text or "")

    decision, response = conversation_runtime.decide(
        context_for("Quero reclamar da garantia")
    )
    assert decision.intent == "exceptional_support"
    assert decision.route == ConversationRoute.HUMAN
    assert response.handoff_required is True
    assert response.reply_text == policy["texts"]["encaminhamento_excepcional"]


def test_confirmation_faq_interrupts_collection_without_losing_booking_state(monkeypatch):
    install_graph(monkeypatch)
    cart = {
        "business_model": "appointment",
        "conversation_state": "collecting",
        "appointment_request": {
            "servico": "polimento-tecnico",
            "vehicle_year": "2019",
            "objective": "Quero manter e cuidar do carro",
            "can_visit_in_person": "Consigo ir presencialmente",
        },
        "missing_fields": ["nome_cliente", "modelo_veiculo", "vehicle_color", "condicao"],
        "_lead_stage": "qualificado",
    }

    decision, response = conversation_runtime.decide(
        context_for(
            "O agendamento é confirmado automaticamente?",
            cart=cart,
        )
    )

    assert decision.intent == "answer_faq"
    assert decision.route == ConversationRoute.SDR
    assert response.reply_text == (
        "Não. Toda data e horário dependem de confirmação humana da Equipe Aurora."
    )
    assert response.cart_state["conversation_state"] == "collecting"
    assert response.cart_state["appointment_request"] == cart["appointment_request"]
    assert response.cart_state["missing_fields"] == cart["missing_fields"]
    assert "aurora-faq-confirmation" in decision.evidence_node_ids


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
            "O que está incluído na lavagem detalhada?",
            cart=first.cart_state,
        )
    )
    assert decision.intent == "answer_faq"
    assert understood.cart_state["clarification_attempts"] == 0

    decision, next_unknown = conversation_runtime.decide(
        context_for("plugh", cart=understood.cart_state)
    )
    assert decision.route == ConversationRoute.SDR
    assert next_unknown.cart_state["clarification_attempts"] == 1


def _mock_build_context_deps(monkeypatch, *, rag_chunks_impl=None):
    from services import supabase_client

    install_graph(monkeypatch)
    monkeypatch.setattr(
        supabase_client, "get_lead_by_ref",
        lambda _ref: {"id": 23, "persona_id": "aurora-id", "stage": "novo", "metadata": {}},
    )
    monkeypatch.setattr(supabase_client, "get_persona", lambda _slug: {"id": "aurora-id"})
    monkeypatch.setattr(supabase_client, "get_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(
        supabase_client, "search_active_rag_chunks",
        rag_chunks_impl or (lambda **_k: []),
    )


def test_build_context_wires_golden_dataset_rag_chunks(monkeypatch):
    """The n8n agentic flow needs a real RAG retrieval layer (Golden
    Dataset: knowledge_rag_entries/knowledge_rag_chunks), separate from
    rag_nodes' in-memory graph-node keyword filter used by the
    deterministic engine. build_context() must surface it without
    changing rag_nodes/rag_paths behavior."""
    calls = []

    def fake_search(**kwargs):
        calls.append(kwargs)
        return [{"rag_entry_id": "e1", "chunk_text": "Polimento leva 4 horas.", "source": "golden_dataset"}]

    _mock_build_context_deps(monkeypatch, rag_chunks_impl=fake_search)

    context = conversation_runtime.build_context(
        persona_slug="aurora", lead_ref=23, message="Quanto custa o polimento técnico?",
    )

    assert context.rag_chunks == [
        {"rag_entry_id": "e1", "chunk_text": "Polimento leva 4 horas.", "source": "golden_dataset"}
    ]
    assert calls[0]["persona_id"] == "aurora-id"
    assert calls[0]["query"] == "Quanto custa o polimento técnico?"
    assert calls[0]["branch_anchor_node_id"] == "aurora-product-polish"
    assert "aurora-product-polish" in calls[0]["allowed_node_ids"]
    assert "aurora-product-interior" not in calls[0]["allowed_node_ids"]
    assert context.active_branch_node_id == "aurora-product-polish"


def test_build_context_survives_rag_search_failure(monkeypatch):
    def broken_search(**_kwargs):
        raise RuntimeError("golden dataset table unavailable")

    _mock_build_context_deps(monkeypatch, rag_chunks_impl=broken_search)

    context = conversation_runtime.build_context(
        persona_slug="aurora", lead_ref=23, message="Oi",
    )

    assert context.rag_chunks == []


def test_graph_publication_preserves_collected_appointment_facts(monkeypatch):
    """A new graph version must rebind policy, not erase customer answers."""
    from services import supabase_client

    _mock_build_context_deps(monkeypatch)
    monkeypatch.setattr(
        supabase_client,
        "get_lead_by_ref",
        lambda _ref: {
            "id": 29,
            "persona_id": "aurora-id",
            "stage": "qualificacao",
            "metadata": {
                "conversation_state": {
                    "business_model": "appointment",
                    "conversation_state": "collecting",
                    "appointment_request": {
                        "servico": "higienizacao-interna",
                        "nome_cliente": "Allan",
                    },
                    "missing_fields": ["modelo_veiculo"],
                },
                "conversation_runtime": {
                    "graph_version": 1,
                    "graph_checksum": "old-checksum",
                },
            },
        },
    )

    context = conversation_runtime.build_context(
        persona_slug="aurora",
        lead_ref=29,
        message="Chevrolet Onix 2020",
    )

    assert context.cart["_graph_changed"] is True
    assert context.cart["appointment_request"] == {
        "servico": "higienizacao-interna",
        "nome_cliente": "Allan",
    }
    assert context.cart["conversation_state"] == "collecting"


def test_published_appointment_graph_requires_a_question_for_every_required_field():
    graph = aurora_graph().model_copy(deep=True)
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = persona.data["appointment_policy"]
    missing_field = policy["required_fields"][0]
    policy["field_questions"].pop(missing_field)

    valid, errors = graph_json_v2_validator.validate_graph_json(graph)

    assert valid is False
    assert any(missing_field in error and "field_questions" in error for error in errors)


def test_runtime_has_no_graph_field_question_copy_fallback():
    import inspect

    source = inspect.getsource(DeterministicAppointment)
    fixture_questions = conversation_runtime._appointment_policy(aurora_graph())["field_questions"]

    assert "DEFAULT_FIELD_QUESTIONS" not in source
    assert "LEGACY_FIELD_QUESTIONS" not in source
    assert all(question not in source for question in fixture_questions.values())

def test_appointment_continues_on_new_graph_version_instead_of_handoff(monkeypatch):
    install_graph(monkeypatch)
    decision, response = conversation_runtime.decide(
        context_for(
            "Chevrolet Onix 2020",
            cart={
                "_graph_changed": True,
                "_previous_graph_version": 1,
                "_previous_graph_checksum": "old-checksum",
                "business_model": "appointment",
                "conversation_state": "collecting",
                "appointment_request": {
                    "servico": "higienizacao-interna",
                    "nome_cliente": "Allan",
                },
                "missing_fields": ["modelo_veiculo"],
            },
        )
    )

    assert decision.intent != "stale_graph"
    assert decision.route == ConversationRoute.SDR
    assert response.handoff_required is False
    assert response.cart_state["appointment_request"]["modelo_veiculo"] == "Chevrolet Onix 2020"
    assert "_previous_graph_version" not in response.cart_state


def test_build_system_prompt_is_persona_agnostic_and_reads_tone_and_rules():
    """The n8n agentic prompt used to be one hardcoded string embedded in
    aurora-conversation.json, reused verbatim by any persona on the
    agentic template. build_system_prompt() reads generic node types
    (persona/tone/rule) from whatever graph it's given — nothing here
    references Aurora, automotive services, or any persona-specific
    vocabulary."""
    prompt = conversation_runtime.build_system_prompt(canonical_aurora_graph())
    assert "Aurora Estética Automotiva" in prompt
    # From the tone node's markdown.
    assert "consultivo" in prompt
    assert "concorrentes" in prompt
    # From the rule node's markdown (operational facts, not invented).
    assert "Pix" in prompt
    assert "sinal de 10%" in prompt
    # Non-negotiable safety instruction, independent of graph content.
    assert "Nunca confirme preco final" in prompt


def test_build_system_prompt_paces_one_question_at_a_time():
    """Regression test for live feedback 2026-08-01: the first agentic
    reply asked for name, service, and vehicle model all at once. A good
    SDR paces the conversation — one question per message, not a form
    dumped in the opener."""
    prompt = conversation_runtime.build_system_prompt(canonical_aurora_graph())
    assert "UMA informacao pendente por mensagem" in prompt
    assert "Nunca liste tres ou mais perguntas" in prompt


def test_build_system_prompt_instructs_multi_field_extraction():
    """The instruction to return extracted_fields (so a customer's single
    message answering several missing fields at once doesn't lose all
    but the first) lives in the generated prompt, not the n8n workflow
    JSON — this is what actually tells DeepSeek the response schema."""
    prompt = conversation_runtime.build_system_prompt(canonical_aurora_graph())
    assert "extracted_fields" in prompt


def test_build_system_prompt_instructs_extraction_from_incidental_mentions():
    """Regression test for the 2026-08-02 finding: a customer wrote 'estou
    pensando em fazer um polimento tecnico no meu fordka' — naming their
    vehicle while asking about a service, not directly answering the last
    question asked — and DeepSeek's own extracted_fields came back empty.
    The prompt must explicitly tell the model to scan the whole message
    for any pending field, not just treat it as an answer to the last
    question."""
    prompt = conversation_runtime.build_system_prompt(canonical_aurora_graph())
    assert "de passagem" in prompt


def test_build_system_prompt_mentions_json_for_deepseek_response_format(monkeypatch):
    """Regression test for a real production 400 confirmed live 2026-08-01:
    DeepSeek (like OpenAI) rejects any request using
    response_format={type: 'json_object'} unless the word 'json' appears
    somewhere in the prompt ("Prompt must contain the word 'json' in some
    form..."). The old hardcoded prompt happened to satisfy this by
    accident ("Responda somente JSON..."); build_system_prompt() must
    keep doing so explicitly, or every agentic reply silently falls back
    to the raw deterministic text with no error surfaced to the user."""
    prompt = conversation_runtime.build_system_prompt(canonical_aurora_graph())
    assert "json" in prompt.lower()


def test_build_system_prompt_never_hardcodes_business_specific_vocabulary():
    """A source-level guard against regressing to the old hardcoded
    prompt: the function body must not contain Aurora-specific business
    vocabulary, so it can never silently leak one persona's identity into
    another persona's graph. (Docstrings/comments may reference Aurora as
    historical context — only the code that actually builds the prompt
    text is checked here.)"""
    import inspect
    source = inspect.getsource(conversation_runtime.build_system_prompt)
    body = source.split('"""', 2)[-1]  # drop the function's own docstring
    lowered = body.lower()
    assert "estetica" not in lowered and "estética" not in lowered
    assert "automotiv" not in lowered
    assert "veiculo" not in lowered and "veículo" not in lowered


def test_build_context_wires_the_generated_system_prompt(monkeypatch):
    _mock_build_context_deps(monkeypatch)
    context = conversation_runtime.build_context(
        persona_slug="aurora", lead_ref=23, message="Oi",
    )
    assert context.system_prompt == conversation_runtime.build_system_prompt(
        aurora_graph(), context.context_cards,
    )
    assert context.system_prompt != ""


def test_explicit_service_interest_starts_qualification_without_booking_keyword():
    """Saying "I want this service" is enough to start qualification.

    The live Aurora E2E used "Quero fazer uma higienizacao interna".  The
    old engine treated that as a one-off catalog consultation, so the next
    answer was parsed outside collecting mode and the lead stalled.
    """
    graph = aurora_graph()
    appointment_policy = conversation_runtime._appointment_policy(graph)
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=appointment_policy,
    )

    result = engine.handle("Quero fazer higienizacao interna")

    assert result.intent == "request_service"
    assert result.handoff is False
    assert result.state["conversation_state"] == "collecting"
    assert result.state["appointment_request"]["servico"] == "higienizacao-interna"
    pending = result.state["missing_fields"][0]
    expected = appointment_policy["field_questions"][pending]
    assert result.reply and result.reply.endswith(expected)


def test_model_identified_service_replaces_stale_service_and_recomputes_fields():
    """A graph-valid service identified in the current turn wins over history."""
    graph = aurora_graph()
    engine = DeterministicAppointment(
        catalog_from_graph(graph),
        policy=conversation_runtime._appointment_policy(graph),
    )
    old_state = {
        "business_model": "appointment",
        "conversation_state": "collecting",
        "appointment_request": {
            "servico": "polimento-tecnico",
            "nome_cliente": "Allan",
            "vehicle_color": "preto",
        },
        "missing_fields": ["modelo_veiculo", "vehicle_year", "objective", "can_visit_in_person", "condicao"],
    }

    result = engine.handle(
        "Quero fazer uma avaliacao e higienizacao interna",
        state=old_state,
        identified_service_slug="higienizacao-interna",
    )

    assert result.state["appointment_request"]["servico"] == "higienizacao-interna"
    assert "vehicle_color" not in result.state["missing_fields"]
    assert result.state["conversation_state"] == "collecting"


def test_merge_extracted_fields_fills_multiple_missing_fields_at_once():
    """Regression test for the 2026-08-01 production finding: a customer
    answering several missing fields in one natural sentence ("meu nome é
    Allan, carro é Tracker 2024") only ever got the first one captured,
    because deterministic_appointment._collect() only fills whichever
    field is next in missing_fields, treating the whole message as that
    one field's value. The agentic engine reads the full message and can
    extract more than one field — this applies that extraction safely."""
    cart_state = {
        "missing_fields": ["modelo_veiculo", "vehicle_year", "condicao"],
        "appointment_request": {"nome_cliente": "Allan Roberto", "servico": "chapeacao"},
    }
    merged = conversation_runtime._merge_extracted_fields(
        cart_state, {"modelo_veiculo": "Tracker", "vehicle_year": "2024"},
    )
    assert merged["appointment_request"]["modelo_veiculo"] == "Tracker"
    assert merged["appointment_request"]["vehicle_year"] == "2024"
    assert merged["appointment_request"]["nome_cliente"] == "Allan Roberto"  # untouched
    assert merged["missing_fields"] == ["condicao"]


def test_merge_extracted_fields_never_overwrites_an_already_filled_field():
    cart_state = {
        "missing_fields": ["modelo_veiculo"],
        "appointment_request": {"modelo_veiculo": "Onix"},
    }
    # vehicle_model isn't even in missing_fields anymore, so this must be a
    # no-op regardless of what the agent claims to have extracted.
    merged = conversation_runtime._merge_extracted_fields(
        cart_state, {"modelo_veiculo": "Civic"},
    )
    assert merged["appointment_request"]["modelo_veiculo"] == "Onix"


def test_merge_extracted_fields_ignores_keys_outside_missing_fields():
    """The agent must never be able to inject a field that isn't
    genuinely on the missing_fields list — no hallucinated or
    out-of-scope key gets accepted."""
    cart_state = {"missing_fields": ["modelo_veiculo"], "appointment_request": {}}
    merged = conversation_runtime._merge_extracted_fields(
        cart_state, {"discount_percent": "50"},
    )
    assert "discount_percent" not in merged["appointment_request"]
    assert merged["missing_fields"] == ["modelo_veiculo"]


def test_merge_extracted_fields_is_noop_without_extraction():
    cart_state = {"missing_fields": ["modelo_veiculo"], "appointment_request": {}}
    assert conversation_runtime._merge_extracted_fields(cart_state, {}) == cart_state


def test_reconciled_model_observation_switches_service_and_advances_pending_field(monkeypatch):
    """The n8n extraction pass is reconciled by deterministic graph policy."""
    install_graph(monkeypatch)
    old_cart = {
        "business_model": "appointment",
        "conversation_state": "collecting",
        "appointment_request": {
            "servico": "polimento-tecnico",
            "nome_cliente": "Allan",
        },
        "missing_fields": [
            "modelo_veiculo",
            "vehicle_year",
            "vehicle_color",
            "objective",
            "can_visit_in_person",
            "condicao",
        ],
    }

    decision, response = conversation_runtime.decide(
        context_for(
            "Chevrolet Onix 2020",
            cart=old_cart,
        ),
        model_observation={
            "fields": {
                "modelo_veiculo": "Chevrolet Onix",
                "vehicle_year": "2020",
            },
            "identified_service_slug": "higienizacao-interna",
        },
    )

    request = response.cart_state["appointment_request"]
    assert request["servico"] == "higienizacao-interna"
    assert request["modelo_veiculo"] == "Chevrolet Onix"
    assert request["vehicle_year"] == "2020"
    assert "vehicle_color" not in response.cart_state["missing_fields"]
    assert response.cart_state["missing_fields"][0] == "objective"
    assert decision.route == ConversationRoute.SDR


def test_first_turn_model_fields_use_graph_required_fields_as_allowlist(monkeypatch):
    install_graph(monkeypatch)
    graph = aurora_graph()
    policy = conversation_runtime._appointment_policy(graph)
    first_field = policy["required_fields"][0]

    _, response = conversation_runtime.decide(
        context_for("Quero fazer higienizacao interna"),
        model_observation={
            "fields": {first_field: "Valor informado pelo cliente"},
            "identified_service_slug": "higienizacao-interna",
        },
    )

    request = response.cart_state["appointment_request"]
    assert request[first_field] == "Valor informado pelo cliente"
    assert first_field not in response.cart_state["missing_fields"]
    pending = response.cart_state["missing_fields"][0]
    assert response.reply_text and response.reply_text.endswith(
        policy["field_questions"][pending]
    )


def test_resolve_identified_service_accepts_a_real_catalog_slug():
    """Regression test for the 2026-08-01 finding: a customer describing
    a symptom ("risco fundo na porta") got a reply correctly recommending
    chapeacao, but 'servico' stayed in missing_fields forever because the
    customer never said the word — extracted_fields only covers answers
    the customer literally gave. identified_service_slug is the model's
    way of reporting what it inferred, accepted only against a real slug.
    """
    resolved = conversation_runtime._resolve_identified_service(
        {}, "chapeacao", [{"slug": "chapeacao", "label": "Chapeação"}],
    )
    assert resolved == {"servico": "chapeacao"}


def test_resolve_identified_service_rejects_an_invented_slug():
    resolved = conversation_runtime._resolve_identified_service(
        {}, "servico-que-nao-existe", [{"slug": "chapeacao", "label": "Chapeação"}],
    )
    assert resolved == {}


def test_resolve_identified_service_never_overrides_an_explicit_answer():
    resolved = conversation_runtime._resolve_identified_service(
        {"servico": "vitrificacao"},
        "chapeacao",
        [{"slug": "chapeacao", "label": "Chapeação"}, {"slug": "vitrificacao", "label": "Vitrificação"}],
    )
    assert resolved == {"servico": "vitrificacao"}


def test_resolve_identified_service_is_noop_without_a_slug():
    assert conversation_runtime._resolve_identified_service({}, None, []) == {}


def test_find_product_ignores_a_generic_word_inside_a_long_description():
    """Regression test for the 2026-08-01 finding: 'pintura' is both the
    word for car paint (the material) and the exact name of Aurora's
    full-repaint service. A customer describing symptoms ('minha pintura
    ta toda fosca e sem brilho') got auto-matched to the repaint service
    before the agentic engine's own symptom-based inference (which
    correctly said polimento tecnico) ever got a chance — because once
    servico is filled, _merge_extracted_fields refuses to overwrite it.
    """
    catalog = catalog_from_graph(aurora_graph())
    result = catalog.find_product(
        "Oi, minha pintura ta toda fosca e sem brilho, da pra resolver?"
    )
    assert result is None


def test_find_product_still_matches_a_short_direct_request():
    """The fix above must not break genuine short, direct requests, where
    a single generic word naming a product is a reliable signal."""
    catalog = catalog_from_graph(aurora_graph())
    assert catalog.find_product("pintura").slug == "pintura"
    assert catalog.find_product("quero fazer pintura no carro").slug == "pintura"


def test_build_context_wires_available_services_from_graph_products(monkeypatch):
    """The n8n Draft node needs the persona's real service catalog (slug +
    label) so the model can report identified_service_slug against
    something real instead of inventing one."""
    _mock_build_context_deps(monkeypatch)

    context = conversation_runtime.build_context(
        persona_slug="aurora", lead_ref=23, message="Oi",
    )

    slugs = {svc["slug"] for svc in context.available_services}
    assert "chapeacao" in slugs
    assert "vitrificacao" in slugs
    assert all("label" in svc for svc in context.available_services)


def test_next_field_question_reads_from_the_graph():
    context = context_for("Oi")
    cart_state = {
        "business_model": "appointment",
        "missing_fields": ["nome_cliente", "modelo_veiculo"],
    }
    assert conversation_runtime._next_field_question(cart_state, context) == (
        "Antes de tudo, qual é o seu nome e sobrenome?"
    )


def test_next_field_question_is_none_without_missing_fields():
    context = context_for("Oi")
    assert conversation_runtime._next_field_question(
        {"business_model": "appointment", "missing_fields": []}, context,
    ) is None


def test_next_field_question_is_none_outside_appointment_business_model():
    context = context_for("Oi")
    assert conversation_runtime._next_field_question(
        {"business_model": "sales", "missing_fields": ["customer_name"]}, context,
    ) is None


def test_ensure_trailing_question_appends_the_next_graph_question():
    """Regression test for the 2026-08-02 finding: DeepSeek's own reply
    correctly asked for the customer's name, but got discarded by an
    overly broad safety fallback and replaced with a plain price fact
    that never asks anything — silently dropping the qualification flow.
    This is now a structural guarantee applied to whatever reply text
    ends up used, not just a prompt instruction that can be skipped.
    """
    context = context_for("Oi")
    cart_state = {
        "business_model": "appointment",
        "missing_fields": ["nome_cliente", "modelo_veiculo"],
    }
    result = conversation_runtime._ensure_trailing_question(
        "Polimento técnico leva cerca de 4 horas e parte de R$ 650,00.",
        cart_state,
        context,
    )
    assert result == (
        "Polimento técnico leva cerca de 4 horas e parte de R$ 650,00. "
        "Antes de tudo, qual é o seu nome e sobrenome?"
    )


def test_ensure_trailing_question_leaves_an_existing_question_alone():
    context = context_for("Oi")
    cart_state = {"business_model": "appointment", "missing_fields": ["nome_cliente"]}
    original = "Entendi! Qual é o seu nome?"
    assert conversation_runtime._ensure_trailing_question(original, cart_state, context) == original


def test_ensure_trailing_question_is_noop_without_missing_fields():
    context = context_for("Oi")
    cart_state = {"business_model": "appointment", "missing_fields": []}
    original = "Perfeito, obrigada."
    assert conversation_runtime._ensure_trailing_question(original, cart_state, context) == original


def test_ensure_trailing_question_preserves_a_deliberate_none_reply():
    context = context_for("Oi")
    cart_state = {"business_model": "appointment", "missing_fields": ["nome_cliente"]}
    assert conversation_runtime._ensure_trailing_question(None, cart_state, context) is None


def test_undocumented_process_hands_off_instead_of_describing_it(monkeypatch):
    """The client wrote, about chapeacao and pintura: "eu nao tenho informacoes
    para passar, nao conheco o processo a fundo". The graph therefore sells both
    services but marks their process as undocumented, and a "how does it work"
    question has to reach a person rather than be answered from nothing.
    """
    graph = install_graph(monkeypatch)
    policy = conversation_runtime._appointment_policy(graph)

    for message in ("Como funciona a pintura?", "Me explica o processo de chapeação"):
        decision, response = conversation_runtime.decide(context_for(message))
        assert decision.route == ConversationRoute.HUMAN, message
        assert response.handoff_required is True, message
        assert decision.handoff_reason == "knowledge_gap_requires_human", message
        assert response.reply_text == policy["texts"]["lacuna_conhecimento"], message

    # A service whose process the briefing does document is answered normally.
    decision, _ = conversation_runtime.decide(context_for("Como funciona o polimento?"))
    assert decision.route == ConversationRoute.SDR


def test_no_published_node_states_a_service_price_duration_or_business_hours():
    """The single invariant this whole rewrite exists to hold."""
    graph = published_aurora_graph()
    for node in graph.nodes:
        text = node_texts(node)
        if node.id not in PAYMENT_POLICY_NODE_IDS:
            for pattern in MONEY_PATTERNS:
                assert not pattern.search(text), f"{node.id} states money"
        else:
            assert set(MONEY_AMOUNT.findall(text)) <= PAYMENT_POLICY_AMOUNTS, node.id
        assert "leva cerca de" not in text, f"{node.id} states a duration"
        assert "duration_minutes" not in text, f"{node.id} states a duration"
        assert not re.search(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", text), node.id
        assert "segunda a sexta" not in text.lower(), f"{node.id} states business hours"

    claim_owners = {
        (node.node_type, claim.get("claim_type"))
        for node in graph.nodes
        for claim in (node.data or {}).get("claims") or []
    }
    assert not ({("product", "price"), ("product", "duration")} & claim_owners)
    assert ("faq", "price") in claim_owners
    assert ("faq", "duration") in claim_owners


def test_every_handoff_target_is_a_globally_reachable_handoff_rule():
    """graph_compiler_v3 rejects a handoff pointing at a node that is not a
    published handoff rule inside the branch closure. Catching it here is far
    cheaper than a failed production compile that splits the two runtimes.
    """
    graph = published_aurora_graph()
    by_id = {node.id: node for node in graph.nodes}
    reachable_rules = {
        node.id for node in graph.nodes
        if (node.data or {}).get("capabilities", {}).get("global_context")
        and (
            (node.data or {}).get("capabilities", {}).get("handoff_rule")
            or isinstance((node.data or {}).get("handoff_rule"), dict)
        )
    }
    for node in graph.nodes:
        handoff = (node.data or {}).get("handoff")
        if not isinstance(handoff, dict):
            continue
        for key, target in handoff.items():
            if not (isinstance(target, str) and key.startswith("on_")):
                continue
            assert target in by_id, f"{node.id}.{key} -> unknown node {target}"
            assert target in reachable_rules, f"{node.id}.{key} -> {target} not reachable"


def test_capacity_and_away_message_come_from_the_briefing():
    policy = appointment_policy_of(published_aurora_graph())
    assert policy["capacity"] == 5
    assert policy["price_disclosure"] == "human_only"
    assert policy["texts"]["mensagem_ausencia"].strip()
    assert "modelo do carro" in policy["texts"]["mensagem_ausencia"]
